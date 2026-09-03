"""
Data model for the whole pipeline.

Everything here is a plain dataclass with `to_dict()` so a report can be
serialised to JSON, persisted into Supabase (`job_readiness_scores`), or
handed to the recruiter dashboard without any ORM in the middle.

The important design property: a ReadinessReport is *self-explaining*. Given
only the JSON, a recruiter (or an examiner) can answer "why did this
candidate score 61 and not 80?" down to the individual file that did or did
not prove a claim. That is the project's transparency requirement, and it is
enforced structurally — every score carries its own evidence list rather than
being computed and discarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Resume side  (the Claimed Skills set, C)
# ---------------------------------------------------------------------------

@dataclass
class ClaimedSkill:
    """One skill the resume asserts."""

    name: str                      # canonical name, or the raw term if unknown
    category: str
    weight: float                  # W_i — 0.0 for unrecognised terms
    verifiable: bool
    recognised: bool               # False = term found but not in the ontology
    sources: list[str] = field(default_factory=list)  # dictionary_scan | skills_section | project_text
    raw_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResumeProfile:
    file_name: str
    status: str                    # success | success_no_skills_found | failed
    reason: str = ""
    # The candidate's own name, read from the top of the CV. Never taken from
    # the filename — see engine/resume/parser.py for why that matters.
    person_name: str | None = None
    # "cv" when the name came from the document, "filename" when we had to fall
    # back (image-only PDFs). Surfaced so a recruiter can see which identities
    # are asserted by the document and which are inferred from a file listing.
    name_source: str = "unknown"
    claimed: list[ClaimedSkill] = field(default_factory=list)
    github_urls: list[str] = field(default_factory=list)
    github_username: str | None = None
    text_chars: int = 0
    used_ocr: bool = False
    skills_section_found: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["claimed"] = [c.to_dict() for c in self.claimed]
        return d


# ---------------------------------------------------------------------------
# GitHub side  (the raw evidence pool)
# ---------------------------------------------------------------------------

@dataclass
class SourceFile:
    repo: str
    path: str
    language: str                  # our own classification, from extension
    size_bytes: int
    text: str = ""                 # populated only for files we actually fetch

    @property
    def ext(self) -> str:
        return "." + self.path.rsplit(".", 1)[-1].lower() if "." in self.path else ""


@dataclass
class RepoEvidence:
    name: str
    full_name: str
    description: str = ""
    is_fork: bool = False
    stars: int = 0
    size_kb: int = 0
    created_at: str = ""
    pushed_at: str = ""
    default_branch: str = "main"
    languages: dict[str, int] = field(default_factory=dict)   # linguist name -> bytes
    topics: list[str] = field(default_factory=list)
    # Declared dependencies discovered across every manifest in the repo,
    # lowercased. Union, not per-manifest — we only need membership tests.
    dependencies: set[str] = field(default_factory=set)
    manifests: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    fetched_files: list[SourceFile] = field(default_factory=list)
    commits_by_owner: int = 0
    last_owner_commit: str = ""
    # Repo-level craft signals, computed once in the miner.
    has_tests: bool = False
    has_ci: bool = False
    has_readme: bool = False
    has_docker: bool = False
    has_lockfile: bool = False
    tree_truncated: bool = False

    @property
    def total_language_bytes(self) -> int:
        return sum(self.languages.values()) or 1

    def language_share(self, linguist_name: str) -> float:
        return self.languages.get(linguist_name, 0) / self.total_language_bytes

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["dependencies"] = sorted(self.dependencies)
        # Source text is large and privacy-sensitive; never serialise it.
        d["fetched_files"] = [
            {"repo": f.repo, "path": f.path, "language": f.language, "size_bytes": f.size_bytes}
            for f in self.fetched_files
        ]
        return d


@dataclass
class GithubProfile:
    username: str
    found: bool = True
    error: str = ""
    name: str = ""
    public_repos: int = 0
    followers: int = 0
    created_at: str = ""
    repos: list[RepoEvidence] = field(default_factory=list)
    api_calls: int = 0
    rate_limit_remaining: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "found": self.found,
            "error": self.error,
            "name": self.name,
            "public_repos": self.public_repos,
            "followers": self.followers,
            "created_at": self.created_at,
            "api_calls": self.api_calls,
            "rate_limit_remaining": self.rate_limit_remaining,
            "repos": [r.to_dict() for r in self.repos],
        }


# ---------------------------------------------------------------------------
# Static analysis
# ---------------------------------------------------------------------------

@dataclass
class CodeMetrics:
    """
    Language-agnostic complexity and craft measurements for one file.

    `analyzed_with` records which analyser produced these — "python_ast" is a
    real AST walk and is exact; "brace_heuristic" is a token-level
    approximation and is explicitly labelled as such so a reviewer never
    mistakes an estimate for a parse.
    """

    path: str = ""
    language: str = ""
    analyzed_with: str = ""
    loc: int = 0                   # non-blank, non-comment lines
    raw_lines: int = 0
    cyclomatic: int = 0            # total decision points + 1 per unit
    max_nesting: int = 0
    functions: int = 0
    classes: int = 0
    avg_function_loc: float = 0.0
    max_function_loc: int = 0
    comment_lines: int = 0
    # Craft signals
    has_error_handling: bool = False
    has_docstrings: bool = False
    has_type_annotations: bool = False
    uses_async: bool = False
    magic_numbers: int = 0
    longest_line: int = 0
    duplicate_block_ratio: float = 0.0
    parse_error: str = ""

    @property
    def comment_ratio(self) -> float:
        total = self.loc + self.comment_lines
        return self.comment_lines / total if total else 0.0

    @property
    def cyclomatic_per_function(self) -> float:
        return self.cyclomatic / self.functions if self.functions else float(self.cyclomatic)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["comment_ratio"] = round(self.comment_ratio, 3)
        d["cyclomatic_per_function"] = round(self.cyclomatic_per_function, 2)
        return d


# ---------------------------------------------------------------------------
# Matching + scoring
# ---------------------------------------------------------------------------

@dataclass
class EvidenceHit:
    """A single concrete reason we believe a skill is real."""

    channel: str        # language | dependency | import | marker
    repo: str
    detail: str         # file path, dependency name, or the idiom matched
    count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Evidence tiers, weakest → strongest. The numeric value is E_i in the
# per-skill verification formula (see scoring/engine.py).
TIER_NONE = "none"
TIER_AMBIENT = "ambient"        # language share only — the repo contains the language
TIER_DECLARED = "declared"      # a manifest declares it, but no code uses it
TIER_USED = "used"              # imported/required in code the candidate wrote
TIER_APPLIED = "applied"        # imported AND idiomatic usage at volume
TIER_MASTERED = "mastered"      # applied across multiple repos, with real complexity

TIER_STRENGTH: dict[str, float] = {
    TIER_NONE: 0.00,
    TIER_AMBIENT: 0.25,
    TIER_DECLARED: 0.45,
    TIER_USED: 0.70,
    TIER_APPLIED: 0.90,
    TIER_MASTERED: 1.00,
}

TIER_ORDER = [TIER_NONE, TIER_AMBIENT, TIER_DECLARED, TIER_USED, TIER_APPLIED, TIER_MASTERED]


@dataclass
class SkillVerdict:
    """
    The full claim-vs-evidence judgement for one skill — this is the row the
    recruiter dashboard's Evidence Gap table renders.
    """

    skill: str
    category: str
    weight: float                      # W_i
    claimed: bool
    verifiable: bool

    tier: str = TIER_NONE
    verification: float = 0.0          # V_i ∈ [0,1] — the final per-skill value

    # The five sub-signals that compose V_i, kept separately so the dashboard
    # can show *why* a verified skill still scored low (e.g. real but stale).
    evidence_strength: float = 0.0     # E — from tier
    depth: float = 0.0                 # D — volume of code
    complexity: float = 0.0            # C — from static analysis
    recency: float = 0.0               # R — decay on last touch
    craft: float = 0.0                 # Q — tests/docs/structure

    repos: list[str] = field(default_factory=list)
    # Subset of `repos` where the skill appeared in actual code rather than
    # only in a language percentage or a manifest entry.
    code_repos: list[str] = field(default_factory=list)
    evidence: list[EvidenceHit] = field(default_factory=list)
    metrics: list[CodeMetrics] = field(default_factory=list)
    loc_analyzed: int = 0
    files_analyzed: int = 0
    last_activity: str = ""
    explanation: str = ""
    # Set when GitHub shows real work in a skill the resume never claimed.
    unclaimed_evidence: bool = False
    # False for skills whose evidence is configuration or commit history
    # rather than source files (Git, Docker, CI/CD). Their complexity and
    # depth signals are structurally zero, so the scorer renormalises Vi over
    # the signals that can actually apply instead of scoring them as if they
    # were shallow code.
    content_based: bool = True

    @property
    def status(self) -> str:
        if not self.claimed and self.tier != TIER_NONE:
            return "unclaimed_strength"
        if not self.verifiable:
            return "not_verifiable"
        if self.tier == TIER_NONE:
            return "unverified"
        if self.tier in (TIER_AMBIENT, TIER_DECLARED):
            return "weakly_verified"
        return "verified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "category": self.category,
            "weight": self.weight,
            "claimed": self.claimed,
            "verifiable": self.verifiable,
            "status": self.status,
            "tier": self.tier,
            "verification": round(self.verification, 4),
            "signals": {
                "evidence_strength": round(self.evidence_strength, 3),
                "depth": round(self.depth, 3),
                "complexity": round(self.complexity, 3),
                "recency": round(self.recency, 3),
                "craft": round(self.craft, 3),
            },
            "repos": self.repos,
            "code_repos": self.code_repos,
            "loc_analyzed": self.loc_analyzed,
            "files_analyzed": self.files_analyzed,
            "last_activity": self.last_activity,
            "evidence": [e.to_dict() for e in self.evidence[:40]],
            "metrics": [m.to_dict() for m in self.metrics[:10]],
            "explanation": self.explanation,
            "unclaimed_evidence": self.unclaimed_evidence,
        }


@dataclass
class ReadinessReport:
    candidate: str
    github_username: str | None
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    score: float = 0.0                 # the headline Job Readiness Score, 0–100
    base_score: float = 0.0            # the shrunk weighted ratio, before adjustments
    raw_ratio: float = 0.0             # Σ W·V / Σ W × 100 — the proposal's formula, unsmoothed
    shrinkage: float = 0.0             # base_score − raw_ratio (negative when claims are few)
    integrity_penalty: float = 0.0     # deduction for weight-heavy unverified claims
    breadth_bonus: float = 0.0
    confidence: float = 0.0            # how much evidence this score rests on

    verdicts: list[SkillVerdict] = field(default_factory=list)
    category_scores: dict[str, float] = field(default_factory=dict)

    claimed_count: int = 0
    verifiable_claims: int = 0
    verified_count: int = 0
    weakly_verified_count: int = 0
    unverified_count: int = 0

    resume: ResumeProfile | None = None
    github: GithubProfile | None = None
    warnings: list[str] = field(default_factory=list)
    engine_version: str = ""

    @property
    def band(self) -> str:
        """Coarse label for the dashboard chip. Thresholds documented in README."""
        s = self.score
        if s >= 80:
            return "Strong evidence"
        if s >= 65:
            return "Solid evidence"
        if s >= 45:
            return "Partial evidence"
        if s >= 25:
            return "Thin evidence"
        return "Largely unevidenced"

    def gap_view(self) -> dict[str, list[str]]:
        """The Evidence Gap visualisation, reduced to three buckets."""
        out: dict[str, list[str]] = {"verified": [], "weakly_verified": [], "unverified": []}
        for v in self.verdicts:
            if v.claimed and v.verifiable and v.status in out:
                out[v.status].append(v.skill)
        return out

    def to_dict(self, include_raw: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "candidate": self.candidate,
            "github_username": self.github_username,
            "generated_at": self.generated_at,
            "engine_version": self.engine_version,
            "score": round(self.score, 2),
            "band": self.band,
            "confidence": round(self.confidence, 3),
            "breakdown": {
                "raw_ratio": round(self.raw_ratio, 2),
                "shrinkage": round(self.shrinkage, 2),
                "base_score": round(self.base_score, 2),
                "integrity_penalty": round(self.integrity_penalty, 2),
                "breadth_bonus": round(self.breadth_bonus, 2),
            },
            "counts": {
                "claimed": self.claimed_count,
                "verifiable_claims": self.verifiable_claims,
                "verified": self.verified_count,
                "weakly_verified": self.weakly_verified_count,
                "unverified": self.unverified_count,
            },
            "category_scores": {k: round(v, 1) for k, v in self.category_scores.items()},
            "evidence_gap": self.gap_view(),
            "verdicts": [v.to_dict() for v in self.verdicts],
            "warnings": self.warnings,
        }
        if include_raw:
            d["resume"] = self.resume.to_dict() if self.resume else None
            d["github"] = self.github.to_dict() if self.github else None
        return d
