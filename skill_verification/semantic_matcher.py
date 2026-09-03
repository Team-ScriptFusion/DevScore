"""
Tier 3 — semantic similarity fallback (Section 7 of the spec), for concept
claims that survive Tiers 0-2 unmatched (e.g. "Machine Learning", "Data
Structures", "Agile").

Embedding provider is swappable behind `EmbeddingProvider` on purpose:

  - `TfidfEmbeddingProvider` is what's active TODAY. This sandbox's network
    policy allows pypi.org/api.github.com but blocks huggingface.co, so the
    spec's `sentence-transformers` model weights can't be downloaded here.
    TF-IDF + cosine similarity needs no download (pure scikit-learn, already
    installed) and lets the full pipeline run end-to-end right now against
    real data — but it's a weaker semantic signal than real embeddings: it
    won't catch "Machine Learning" ~ "trained a CNN" the way MiniLM would,
    because there's no shared vocabulary between those phrases.
  - `SentenceTransformerEmbeddingProvider` is the spec's actual design
    (all-MiniLM-L6-v2) and is fully implemented below. Switch to it by
    changing ONE line in main.py once this runs somewhere with Hugging Face
    access — your own machine, or wherever DevScore actually deploys. The
    model is ~90MB; you can also pre-download it once and vendor the folder
    into the repo / set HF_HUB_OFFLINE=1 with a warm cache if the
    production server also has no internet access.

Everything downstream (thresholding, confidence storage, method labelling)
is identical either way — swapping providers doesn't touch main.py's logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from models import MatchMethod, RepoEvidence, SkillStatus, SkillVerification

# Spec's own words: "a rough starting point, not tuned." Per
# scoring-algorithm-decision, this must eventually be FITTED on the expert
# training split, not hand-picked — keep it in one place, in config, so
# swapping it later doesn't mean hunting through the codebase.
DEFAULT_THRESHOLD = 0.68

# Claims that genuinely leave no trace in code, regardless of how good the
# matcher is (Section 3, "not verifiable" finding). Treating these as failed
# Tier 3 matches would penalise honesty — a claim that CANNOT be checked is
# not the same claim as one that WAS checked and failed.
NOT_VERIFIABLE_SKILLS = {
    "figma", "agile", "scrum", "kanban", "ui/ux design", "ux design",
    "ui design", "project management", "communication", "teamwork",
    "leadership", "problem solving", "time management",
}


class EmbeddingProvider(ABC):
    # Overridden per provider: TF-IDF cosine similarity and a real sentence
    # embedding's cosine similarity live on very different scales (sparse
    # keyword overlap vs. dense semantic space) — reusing one hand-picked
    # threshold across both would silently break whichever isn't MiniLM.
    default_threshold: float = DEFAULT_THRESHOLD

    @abstractmethod
    def encode(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def cosine(self, a: list[float], b: list[float]) -> float: ...


class TfidfEmbeddingProvider(EmbeddingProvider):
    """No-download stand-in, active by default in this sandbox. Threshold is
    lower and UNTUNED — TF-IDF only overlaps on shared vocabulary, so even a
    strong conceptual match (e.g. "Machine Learning" vs. a README that says
    "trained a neural network") scores much lower than MiniLM would give it.
    Treat every TF-IDF confidence number as provisional until re-run with
    real embeddings."""

    default_threshold = 0.12

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self._TfidfVectorizer = TfidfVectorizer

    def encode_corpus(self, texts: list[str]):
        """TF-IDF needs the whole corpus fit at once (unlike a true embedding
        model, which encodes each text independently) — so this returns a
        vectorizer + matrix rather than one vector per call. See
        `best_match` below, which is what callers should actually use."""
        vec = self._TfidfVectorizer(stop_words="english", max_features=4096)
        matrix = vec.fit_transform(texts)
        return vec, matrix

    def encode(self, texts: list[str]) -> list[list[float]]:
        _, matrix = self.encode_corpus(texts)
        return matrix.toarray().tolist()

    def cosine(self, a, b) -> float:
        from sklearn.metrics.pairwise import cosine_similarity
        return float(cosine_similarity([a], [b])[0][0])


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """The spec's actual design (Section 7.2). Needs network access to
    huggingface.co on first run to download all-MiniLM-L6-v2 (~90MB), then
    caches locally. Not usable in this sandbox today — see module docstring."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, convert_to_numpy=True).tolist()

    def cosine(self, a, b) -> float:
        from sentence_transformers.util import cos_sim
        return float(cos_sim(a, b)[0][0])


def match_semantic(claimed_skill: str, repos: list[RepoEvidence],
                    provider: EmbeddingProvider,
                    scope_repo_name: str | None = None,
                    threshold: float | None = None) -> SkillVerification:
    """Always returns a SkillVerification (never None) — this is the last
    tier, per Section 7.7 every claim must end in an explicit result."""
    if threshold is None:
        threshold = provider.default_threshold
    normalized = claimed_skill.strip().lower()
    if normalized in NOT_VERIFIABLE_SKILLS:
        return SkillVerification(
            claimed_skill=claimed_skill,
            status=SkillStatus.NOT_VERIFIABLE,
            method=MatchMethod.UNVERIFIED,
            confidence=0.0,
            reason="this kind of claim leaves no trace in a code repository "
                   "(design tools, methodologies, soft skills) — absence of "
                   "evidence is not evidence of absence here",
        )

    candidates = [r for r in repos if scope_repo_name is None or r.repo_name == scope_repo_name]
    chunks, chunk_repo = [], []
    for repo in candidates:
        text = repo.evidence_text()
        if text:
            chunks.append(text)
            chunk_repo.append(repo.repo_name)

    if not chunks:
        return SkillVerification(
            claimed_skill=claimed_skill, status=SkillStatus.UNVERIFIED,
            method=MatchMethod.UNVERIFIED, confidence=0.0,
            reason="no_evidence_found (no README/description text to compare against)",
        )

    best_score, best_repo = _best_match(provider, claimed_skill, chunks, chunk_repo)

    if best_score >= threshold:
        return SkillVerification(
            claimed_skill=claimed_skill, status=SkillStatus.VERIFIED,
            method=MatchMethod.SEMANTIC_MATCH, confidence=best_score,
            evidence_repo=best_repo,
            reason=f"similarity {best_score:.3f} >= threshold {threshold} against {best_repo}'s evidence text",
        )
    return SkillVerification(
        claimed_skill=claimed_skill, status=SkillStatus.UNVERIFIED,
        method=MatchMethod.UNVERIFIED, confidence=best_score,
        reason=f"no_evidence_found (best similarity {best_score:.3f} < threshold {threshold})",
    )


def _best_match(provider: EmbeddingProvider, skill: str,
                 chunks: list[str], chunk_repo: list[str]) -> tuple[float, str]:
    if isinstance(provider, TfidfEmbeddingProvider):
        # Fit TF-IDF over [skill] + all chunks together so they share a
        # vocabulary — fitting separately would make cosine similarity
        # meaningless (different feature spaces).
        vec, matrix = provider.encode_corpus([skill] + chunks)
        skill_vec = matrix[0].toarray()[0]
        best_score, best_repo = 0.0, chunk_repo[0]
        for i, repo_name in enumerate(chunk_repo, start=1):
            chunk_vec = matrix[i].toarray()[0]
            score = provider.cosine(skill_vec, chunk_vec)
            if score > best_score:
                best_score, best_repo = score, repo_name
        return best_score, best_repo

    # True embedding models encode independently, no shared-fit needed.
    skill_vec = provider.encode([skill])[0]
    chunk_vecs = provider.encode(chunks)
    best_score, best_repo = 0.0, chunk_repo[0]
    for vec, repo_name in zip(chunk_vecs, chunk_repo):
        score = provider.cosine(skill_vec, vec)
        if score > best_score:
            best_score, best_repo = score, repo_name
    return best_score, best_repo
