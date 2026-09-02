"""Orchestrates Phase 1 (direct) then Phase 2 (semantic) matching per skill."""

from direct_matcher import direct_match
from semantic_matcher import semantic_match_batch


def match_skills(claimed_skills: list, repos: list) -> list:
    """
    Runs direct matching first, then falls back to semantic matching for
    anything unresolved. Returns one result dict per claimed skill, in the
    same order as `claimed_skills`.

    Everything that falls through to Phase 2 is matched in a single
    semantic_match_batch call: calling semantic_match per skill would
    re-embed every repo once per skill (O(skills x repos) encodes), which
    for a long claimed-skill list risks blowing the Node client's 60s
    request timeout.
    """
    results = [None] * len(claimed_skills)
    pending_indices = []
    pending_skills = []

    for index, skill in enumerate(claimed_skills):
        direct_result = direct_match(skill, repos)
        if direct_result is not None:
            results[index] = direct_result
            continue

        if not repos:
            results[index] = {
                "skill": skill,
                "verified": False,
                "method": "unverified",
                "confidence": None,
                "evidence_repo": None,
                "reason": "no_public_repos",
            }
            continue

        pending_indices.append(index)
        pending_skills.append(skill)

    for index, semantic_result in zip(pending_indices, semantic_match_batch(pending_skills, repos)):
        results[index] = semantic_result

    return results
