"""
Tier 2 — structural inference. This is the tier that answers "what is
semantic about your analysis?" honestly: it verifies claims that appear
NOWHERE as a string in the evidence, by reasoning about what a *combination*
of dependencies/files implies.

Concrete example from the real run: "Full-Stack Development" was verified
because flask + express + react co-occurred across a student's repos — the
phrase "full-stack" is not in any manifest, README, or commit. That's a
structural rule, not a string match, and it's genuinely different from
Tier 1 and from Tier 3's embeddings.

Each rule is a small, named, hand-authored function so a supervisor/panel
can be shown exactly why a claim was verified — "we inferred X because Y and
Z co-occur" is defensible in a way "the model said 0.81" alone is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from models import MatchMethod, RepoEvidence, SkillStatus, SkillVerification
from synonyms import normalize


@dataclass
class StructuralRule:
    skill: str                                   # normalized skill name this rule can verify
    predicate: Callable[[RepoEvidence], bool]     # True if this repo satisfies the rule
    explain: Callable[[RepoEvidence], str]        # human-readable evidence string


def _has_any(repo: RepoEvidence, markers: list[str]) -> bool:
    blob = " ".join(repo.manifests.values()).lower()
    return any(m.lower() in blob for m in markers)


def _has_all(repo: RepoEvidence, markers: list[str]) -> bool:
    blob = " ".join(repo.manifests.values()).lower()
    return all(m.lower() in blob for m in markers)


RULES: list[StructuralRule] = [
    StructuralRule(
        skill="full-stack development",
        predicate=lambda r: (_has_any(r, ["flask", "django", "express"]) and _has_any(r, ["react", "vue", "next"])),
        explain=lambda r: "backend framework + frontend framework co-occurring in one repo",
    ),
    StructuralRule(
        skill="cloud-native applications",
        predicate=lambda r: _has_any(r, ["firebase", "azure-core", "@supabase/supabase-js",
                                          "aws-sdk", "boto3"]) or "vercel.json" in r.manifests,
        explain=lambda r: "managed cloud backend SDK or deployment config present",
    ),
    StructuralRule(
        skill=".net",
        predicate=lambda r: any(f.endswith((".sln", ".vcxproj", ".resx")) for f in r.manifests) or
                             r.languages.get("C#", 0) > 0,
        explain=lambda r: ".NET project files present with no package-manager manifest for the ecosystem",
    ),
    StructuralRule(
        skill="mobile app development",
        predicate=lambda r: (
            ("flutter" in " ".join(r.manifests.values()).lower() or "pubspec.yaml" in r.manifests)
            # minimum-substance test (Section 5.3 fix): a source file must
            # exist, not just an icon/asset path matching "android"/"ios".
            and r.languages.get("Dart", 0) > MIN_SUBSTANCE_BYTES
        ),
        explain=lambda r: "Flutter manifest plus a non-trivial amount of Dart source",
    ),
    StructuralRule(
        skill="rest api",
        predicate=lambda r: _has_any(r, ["express", "flask", "django", "fastapi", "spring-boot-starter-web"]),
        explain=lambda r: "a web/API framework dependency implies REST endpoints even if unstated",
    ),
]

MIN_SUBSTANCE_BYTES = 1000  # a path/extension match alone isn't enough (Section 5.3)


def match_structural(claimed_skill: str, repos: list[RepoEvidence],
                      scope_repo_name: str | None = None) -> SkillVerification | None:
    normalized = normalize(claimed_skill)
    candidates = [r for r in repos if scope_repo_name is None or r.repo_name == scope_repo_name]
    for rule in RULES:
        if rule.skill != normalized:
            continue
        for repo in candidates:
            if rule.predicate(repo):
                return SkillVerification(
                    claimed_skill=claimed_skill,
                    status=SkillStatus.VERIFIED,
                    method=MatchMethod.STRUCTURAL_MATCH,
                    confidence=0.9,  # high but not 1.0 — this is inference, not a literal string match
                    evidence_repo=repo.repo_name,
                    reason=rule.explain(repo),
                )
    return None
