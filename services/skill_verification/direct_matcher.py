"""Phase 1 — deterministic language-tag matching (module spec §6)."""

from synonyms import normalize

# A single auto-generated config file (e.g. a stray .gitignore-tracked
# lockfile) can register a few bytes of a language GitHub didn't mean to
# highlight as real usage — this floor filters that noise out.
MIN_LANGUAGE_BYTES = 200


def direct_match(claimed_skill: str, repos: list) -> dict | None:
    """
    Returns a verified match if `claimed_skill` (or a synonym) appears as a
    GitHub language tag with a non-trivial byte count in any of `repos`,
    else None (caller falls through to semantic matching).
    """
    target = normalize(claimed_skill)
    best_repo = None
    best_bytes = 0

    for repo in repos:
        for lang, byte_count in repo.get("languages", {}).items():
            if normalize(lang) == target and byte_count > best_bytes:
                best_bytes = byte_count
                best_repo = repo["name"]

    if best_repo is not None and best_bytes >= MIN_LANGUAGE_BYTES:
        return {
            "skill": claimed_skill,
            "verified": True,
            "method": "direct_match",
            "confidence": 1.0,
            "evidence_repo": best_repo,
            "reason": None,
        }
    return None
