"""Orchestrates Phase 1 (direct) then Phase 2 (semantic) matching per skill."""

from direct_matcher import direct_match
from semantic_matcher import semantic_match


def match_skills(claimed_skills: list, repos: list) -> list:
    """
    Runs direct matching first, then falls back to semantic matching for
    anything unresolved. Returns one result dict per claimed skill, in the
    same order as `claimed_skills`.
    """
    results = []
    for skill in claimed_skills:
        direct_result = direct_match(skill, repos)
        if direct_result is not None:
            results.append(direct_result)
            continue

        if not repos:
            results.append({
                "skill": skill,
                "verified": False,
                "method": "unverified",
                "confidence": None,
                "evidence_repo": None,
                "reason": "no_public_repos",
            })
            continue

        results.append(semantic_match(skill, repos))
    return results
