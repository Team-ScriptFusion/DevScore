"""
Data shapes for the skill-verification module.

These mirror the Supabase schema in the module spec (Section 8), plus the
refinements from the real run documented in CV_GitHub_Evidence_Walkthrough.md:

  - `status` replaces the spec's boolean `verified` with a three-state value.
    A boolean conflates "we checked and it failed" with "we had no way to
    check" (e.g. Figma, Agile) — those are different claims and penalising
    them the same way punishes honesty.
  - `method` gains 'structural_match' (Tier 2) and 'project_bound' isn't a
    method on its own — Tier 0 is a pre-step that scopes Tier 1/2 to a
    specific repo, it doesn't verify anything by itself.
  - AuthorshipClass is new: the spec's matcher never asked "whose commit is
    this", so team-project evidence was previously not distinguishable from
    solo evidence. The real run found commits are also not just
    mine/not-mine — a disputed identity (mismatched name+email pair) exists
    and must be excluded from scoring, not guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SkillStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    NOT_VERIFIABLE = "not_verifiable"


class MatchMethod(str, Enum):
    DIRECT_MATCH = "direct_match"
    STRUCTURAL_MATCH = "structural_match"
    SEMANTIC_MATCH = "semantic_match"
    UNVERIFIED = "unverified"


class AuthorshipClass(str, Enum):
    MINE = "mine"
    DISPUTED = "disputed"
    OTHER = "other"


@dataclass
class CommitAuthor:
    name: str
    email: str
    committed_at: datetime


@dataclass
class RepoEvidence:
    """One row of `github_evidence` (Section 8), fetched with zero clones."""
    repo_name: str
    is_fork: bool
    description: Optional[str]
    languages: dict[str, int]          # bytes per language, from GitHub's own API
    manifests: dict[str, str]          # filename -> raw content (package.json, requirements.txt, ...)
    readme_text: str
    commit_count: int
    last_commit_at: Optional[datetime]
    commit_authors: list[CommitAuthor] = field(default_factory=list)
    authorship: dict[AuthorshipClass, int] = field(default_factory=dict)  # counts, this student's view
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    def evidence_text(self) -> str:
        """Corpus chunk for Tier 3: README + description. Commit messages are
        deliberately excluded per Section 7.1 of the spec (noisier, add later
        only if precision is too low without them)."""
        parts = [self.description or "", self.readme_text or ""]
        return "\n".join(p for p in parts if p).strip()


@dataclass
class ProjectBinding:
    """Tier 0 output: a CV-claimed project bound to a specific repo."""
    cv_project_name: str
    repo_name: Optional[str]
    binding_score: float          # 0-1 fuzzy match confidence; 0 = unbound
    cv_claimed_stack: list[str] = field(default_factory=list)


@dataclass
class SkillVerification:
    """One row of `skill_verification` (Section 8)."""
    claimed_skill: str
    status: SkillStatus
    method: MatchMethod
    confidence: float                      # 0-1, always populated (spec 7.5)
    evidence_repo: Optional[str] = None
    project_binding: Optional[str] = None  # which CV project this was scoped to, if any
    reason: Optional[str] = None           # populated when status != verified
    conflict: Optional[str] = None         # populated when the bound repo contradicts the CV (5.2)

    def to_api_dict(self) -> dict:
        """Shape matching Section 9's API contract, with `status` added
        alongside the legacy boolean so existing consumers (recruiter
        dashboard) don't break while they migrate off `verified`."""
        d = {
            "claimed_skill": self.claimed_skill,
            "verified": self.status == SkillStatus.VERIFIED,
            "status": self.status.value,
            "method": self.method.value,
            "confidence": round(self.confidence, 4),
        }
        if self.evidence_repo:
            d["evidence_repo"] = self.evidence_repo
        if self.project_binding:
            d["project_binding"] = self.project_binding
        if self.reason:
            d["reason"] = self.reason
        if self.conflict:
            d["conflict"] = self.conflict
        return d
