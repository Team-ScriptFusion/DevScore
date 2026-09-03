"""
Tier 1 — deterministic baseline matcher (Section 6 of the spec).

Two evidence sources, both direct/string-level:
  1. Language byte share (from GitHub's own `languages` field — already
     Linguist-filtered, no local generated/vendored exclusion needed).
  2. Manifest dependency names (synonyms.DEPENDENCY_MARKERS) — this is new
     versus the spec's "language tags only" plan, and is what verifies
     framework/library claims like React or Flask, which never show up as
     a GitHub "language".

`MIN_LANGUAGE_BYTES` exists because the real run's false positives (C++
from Flutter's generated scaffolding, Mobile App Dev from an icons folder)
were both cases of trivial byte counts being treated as real evidence.
Requiring a minimum share, not just non-zero bytes, is the fix.
"""

from __future__ import annotations

from models import MatchMethod, RepoEvidence, SkillStatus, SkillVerification
from synonyms import DEPENDENCY_MARKERS, normalize

MIN_LANGUAGE_BYTES = 500          # a handful of bytes shouldn't count as "using" a language
MIN_LANGUAGE_SHARE = 0.02         # or under 2% of the repo — likely incidental (a single config file)


def match_direct(claimed_skill: str, repos: list[RepoEvidence],
                  scope_repo_name: str | None = None) -> SkillVerification | None:
    """Returns a SkillVerification if directly verified, else None (falls
    through to Tier 2). `scope_repo_name` restricts the check to one repo
    when Tier 0 has bound this skill's project — see main.py."""
    normalized = normalize(claimed_skill)
    candidates = [r for r in repos if scope_repo_name is None or r.repo_name == scope_repo_name]

    # 1. Language byte share
    for repo in candidates:
        total = sum(repo.languages.values()) or 1
        for lang, size in repo.languages.items():
            if normalize(lang) != normalized:
                continue
            share = size / total
            if size >= MIN_LANGUAGE_BYTES and share >= MIN_LANGUAGE_SHARE:
                return SkillVerification(
                    claimed_skill=claimed_skill,
                    status=SkillStatus.VERIFIED,
                    method=MatchMethod.DIRECT_MATCH,
                    confidence=1.0,
                    evidence_repo=repo.repo_name,
                    reason=f"{lang}: {share:.0%} of bytes ({size} bytes)",
                )

    # 2. Manifest dependency markers
    markers = DEPENDENCY_MARKERS.get(normalized, [])
    for repo in candidates:
        manifest_blob = " ".join(repo.manifests.values()).lower()
        for marker in markers:
            if marker.lower() in manifest_blob:
                return SkillVerification(
                    claimed_skill=claimed_skill,
                    status=SkillStatus.VERIFIED,
                    method=MatchMethod.DIRECT_MATCH,
                    confidence=1.0,
                    evidence_repo=repo.repo_name,
                    reason=f"`{marker}` found in a manifest file",
                )

    return None
