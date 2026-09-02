"""Phase 2 — semantic similarity matching (module spec §7)."""

from functools import lru_cache

from sentence_transformers import SentenceTransformer, util

MODEL_NAME = "all-MiniLM-L6-v2"

# Rough starting point, not tuned. Confidence is stored regardless of
# whether it clears this — do not tune this value against the project's
# expert-ranking dataset (reserved for the scoring module).
THRESHOLD = 0.65


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    # Loaded once per process (module-level singleton via lru_cache), not
    # once per request — loading it fresh each call would dominate latency.
    return SentenceTransformer(MODEL_NAME)


def build_evidence_chunks(repos: list) -> list:
    """One evidence chunk per repo: repo name + README text, truncated."""
    chunks = []
    for repo in repos:
        text = f"{repo['name']} {repo.get('readme_text') or ''}".strip()
        if text:
            chunks.append({"repo": repo["name"], "text": text})
    return chunks


def _build_result(claimed_skill: str, best_score: float, best_repo: str) -> dict:
    """Shapes one per-skill semantic result. `best_score` is already clamped."""
    verified = best_score >= THRESHOLD
    return {
        "skill": claimed_skill,
        "verified": verified,
        "method": "semantic_match",
        "confidence": round(best_score, 4),
        "evidence_repo": best_repo,
        "reason": None if verified else "below_confidence_threshold",
    }


def _clamp(score: float) -> float:
    """
    Cosine similarity ranges [-1, 1], but skill_verification.confidence is
    constrained to [0, 1] in the database — a negative score (which happens
    for garbled OCR-extracted skill strings against unrelated evidence) would
    fail the batch insert and lose every other skill's result in that run.
    A negative similarity means "no evidence at all", so 0.0 is the honest
    floor.
    """
    return max(0.0, float(score))


def semantic_match(claimed_skill: str, repos: list) -> dict:
    """
    Embeds `claimed_skill` and every evidence chunk built from `repos`,
    returns the best-scoring chunk's result regardless of whether it clears
    THRESHOLD. Precondition: `repos` is non-empty (callers must handle the
    empty case as "no_public_repos" before reaching here).
    """
    chunks = build_evidence_chunks(repos)
    model = _model()

    skill_embedding = model.encode(claimed_skill, convert_to_tensor=True)
    chunk_embeddings = model.encode([c["text"] for c in chunks], convert_to_tensor=True)
    scores = util.cos_sim(skill_embedding, chunk_embeddings)[0]

    best_idx = int(scores.argmax())
    return _build_result(claimed_skill, _clamp(scores[best_idx]), chunks[best_idx]["repo"])


def semantic_match_batch(claimed_skills: list, repos: list) -> list:
    """
    Like semantic_match, but embeds all repo chunks ONCE and all claimed
    skills ONCE, then computes the full similarity matrix — avoiding the
    O(skills x repos) redundant re-embedding semantic_match incurs when
    called in a loop. Returns one result per claimed_skills entry, same
    order, same per-item shape as semantic_match. Precondition: repos is
    non-empty (same precondition as semantic_match).
    """
    if not claimed_skills:
        return []

    chunks = build_evidence_chunks(repos)
    model = _model()

    skill_embeddings = model.encode(list(claimed_skills), convert_to_tensor=True)
    chunk_embeddings = model.encode([c["text"] for c in chunks], convert_to_tensor=True)
    score_matrix = util.cos_sim(skill_embeddings, chunk_embeddings)

    results = []
    for claimed_skill, scores in zip(claimed_skills, score_matrix):
        best_idx = int(scores.argmax())
        results.append(
            _build_result(claimed_skill, _clamp(scores[best_idx]), chunks[best_idx]["repo"])
        )
    return results
