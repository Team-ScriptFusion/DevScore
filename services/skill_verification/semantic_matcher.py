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
    best_score = float(scores[best_idx])
    verified = best_score >= THRESHOLD

    return {
        "skill": claimed_skill,
        "verified": verified,
        "method": "semantic_match",
        "confidence": round(best_score, 4),
        "evidence_repo": chunks[best_idx]["repo"],
        "reason": None if verified else "below_confidence_threshold",
    }
