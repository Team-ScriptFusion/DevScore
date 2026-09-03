"""
The Job Readiness Score.

The Project Proposal defines the Weighted Verification Ratio:

    I = ( Σ Wᵢ · Vᵢ ) / ( Σ Wᵢ ) × 100        Vᵢ ∈ {0, 1}

That formula is kept exactly. What changes is Vᵢ: a boolean cannot express
the difference between a candidate who once imported React and one who has
shipped three React applications with tests, and the SDS already anticipates
this ("tiered refinements: penalties for unverified claims, bonuses for
contribution recency and volume, repository-diversity factors"). So Vᵢ
becomes continuous on [0, 1]:

    Vᵢ = 0.40·E + 0.22·C + 0.18·D + 0.12·R + 0.08·Q

    E  evidence strength   from the matcher's tier (ambient → mastered)
    C  code complexity     banded cyclomatic complexity from static analysis
    D  depth / volume      log-scaled LOC, files, repositories
    R  recency             exponential decay, 14-month half-life
    Q  craft               tests, CI, error handling, typing, duplication

The coefficients say what the model believes: verification dominates (0.40 —
this is a verification system before it is a quality system), how good the
code is comes next (0.22), and how much of it there is comes after that
(0.18). Volume ranks below quality on purpose. Recency and craft are real
but secondary for a population of undergraduates.

Setting E's coefficient to 1.0 and every other to 0.0 reproduces the
proposal's original boolean formula exactly, which makes the extension
testable: `tools/ablation.py` runs both and reports the difference against
the expert baseline. That comparison is the research result.

------------------------------------------------------------------------
FOUR ADJUSTMENTS, AND WHY EACH IS BOUNDED
------------------------------------------------------------------------

SMALL-SAMPLE SHRINKAGE. A weighted ratio over two claims is a ratio computed
from almost no data. Left alone it rewards under-claiming — on the collected
cohort a candidate who listed one verifiable skill and proved it scored 75.0,
ahead of one who listed twelve and proved nine. The ratio is therefore shrunk
toward a prior (see PRIOR_CLAIMS below). Both the smoothed and unsmoothed
values are reported, so the correction is visible rather than baked in.

INTEGRITY PENALTY (≤ 12 points). The base score already handles an
unverified claim by scoring it 0. A separate penalty is only justified for
what the base score cannot express: the difference between "no evidence
because there was nothing to look at" and "no evidence despite twenty active
repositories". Only the second is a credibility signal. So the penalty is
scaled by *evidence capacity* — how much code we actually got to inspect.

    penalty = 12 · unverified_weight_share · capacity

A candidate with no GitHub link has capacity ≈ 0 and takes no penalty at
all. This is not generosity; it is the difference between measuring the
candidate and measuring our own coverage. Charging someone for our blind
spot is precisely the bias the project exists to remove.

BREADTH BONUS (≤ 5 points). Verified skills spanning multiple engineering
areas (frontend, backend, data, mobile, devops). Capped low because breadth
is worth less than depth and an uncapped bonus rewards listing everything.

CONFIDENCE (reported, never applied). How much evidence the score rests on.
It is deliberately NOT folded into the score — a low-confidence 70 and a
high-confidence 70 are the same claim about the candidate and a different
claim about us. Silently deflating uncertain scores would hide that
distinction from the recruiter. It is surfaced instead, and the dashboard is
expected to show it next to the number.
"""

from __future__ import annotations

from .. import ontology
from ..models import (
    TIER_APPLIED,
    TIER_MASTERED,
    TIER_NONE,
    TIER_USED,
    GithubProfile,
    ReadinessReport,
    ResumeProfile,
    SkillVerdict,
)

# Vᵢ composition. Must sum to 1.0 — asserted at import so a bad edit fails
# loudly instead of silently rescaling every score in the study.
SIGNAL_WEIGHTS: dict[str, float] = {
    "evidence_strength": 0.40,
    "complexity": 0.22,
    "depth": 0.18,
    "recency": 0.12,
    "craft": 0.08,
}
assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9, "SIGNAL_WEIGHTS must sum to 1.0"

MAX_INTEGRITY_PENALTY = 12.0
MAX_BREADTH_BONUS = 5.0

# Small-sample shrinkage. A weighted ratio over a handful of claims is a
# ratio computed from almost no data, and it rewards under-claiming: on the
# collected cohort, a candidate who listed ONE verifiable skill and proved it
# scored 75.0, ahead of a candidate who listed twelve and proved nine. That is
# backwards. A CV asserting one technical skill is not stronger evidence of
# job readiness than a CV asserting twelve, whatever the ratio says.
#
# So the ratio is shrunk toward a prior, exactly as one would smooth any
# small-denominator rate:
#
#     base = ( Σ WᵢVᵢ + k·W̄·μ ) / ( Σ Wᵢ + k·W̄ )
#
# k = 1.5 pseudo-claims at μ = 0.30 (roughly the cohort's mean Vᵢ — "an
# unknown claim is probably weakly evidenced"). k was tuned on the curve, not
# picked: at a strong ratio of 81 it costs a 1-claim CV about 31 points, a
# 5-claim CV about 11, and a 12-claim CV under 6. That is the shape wanted —
# decisive where the denominator is meaningless, nearly invisible where it is
# not. Both values are reported in the breakdown, so the correction is never
# silent.
PRIOR_CLAIMS = 1.5
PRIOR_VERIFICATION = 0.30
# Below this many verifiable claims, the recruiter is told the score rests on
# very few assertions.
THIN_CLAIM_THRESHOLD = 4

# Capacity anchors: the amount of mined material at which we consider
# ourselves to have had a fair chance to find evidence.
CAPACITY_FILES = 25
CAPACITY_REPOS = 5


def compute_verification(verdict: SkillVerdict, *, boolean_mode: bool = False) -> float:
    """
    Vᵢ for one skill.

    `boolean_mode` reproduces the proposal's original {0,1} formulation for
    the ablation study: any evidence at USED or above counts as 1.
    """
    if verdict.tier == TIER_NONE:
        return 0.0

    if boolean_mode:
        return 1.0 if verdict.tier in (TIER_USED, TIER_APPLIED, TIER_MASTERED) else 0.0

    if not verdict.content_based:
        # Configuration- and commit-evidenced skills (Git, Docker, CI/CD,
        # Kubernetes, Nginx) have no source files, so C and D are zero by
        # construction rather than by observation. Scoring them on the full
        # five-signal blend would cap a fully verified Dockerfile at ~0.45
        # and quietly report a real skill as half-proven. Renormalise over
        # the three signals that can apply.
        applicable = ("evidence_strength", "recency", "craft")
        denominator = sum(SIGNAL_WEIGHTS[k] for k in applicable)
        value = (
            SIGNAL_WEIGHTS["evidence_strength"] * verdict.evidence_strength
            + SIGNAL_WEIGHTS["recency"] * verdict.recency
            + SIGNAL_WEIGHTS["craft"] * verdict.craft
        ) / denominator
        return round(min(value, verdict.evidence_strength), 4)

    value = (
        SIGNAL_WEIGHTS["evidence_strength"] * verdict.evidence_strength
        + SIGNAL_WEIGHTS["complexity"] * verdict.complexity
        + SIGNAL_WEIGHTS["depth"] * verdict.depth
        + SIGNAL_WEIGHTS["recency"] * verdict.recency
        + SIGNAL_WEIGHTS["craft"] * verdict.craft
    )
    # Evidence strength gates the rest: a skill can never score above what
    # its tier justifies, so a stale-but-huge codebase cannot out-rank a
    # genuinely verified one on volume alone.
    return round(min(value, verdict.evidence_strength), 4)


def _capacity(github: GithubProfile | None) -> float:
    """How much of a chance did we actually have to find evidence? [0,1]."""
    if github is None or not github.found:
        return 0.0
    files = sum(len(r.fetched_files) for r in github.repos)
    repos = sum(1 for r in github.repos if r.languages)
    if files == 0:
        return 0.0
    return round(min(1.0, 0.6 * min(1.0, files / CAPACITY_FILES)
                     + 0.4 * min(1.0, repos / CAPACITY_REPOS)), 4)


def _category_scores(verdicts: list[SkillVerdict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for group, members in ontology.CATEGORY_GROUPS.items():
        relevant = [
            v for v in verdicts
            if v.skill in members and v.claimed and v.verifiable
        ]
        if not relevant:
            continue
        total_weight = sum(v.weight for v in relevant)
        if total_weight <= 0:
            continue
        out[group] = sum(v.weight * v.verification for v in relevant) / total_weight * 100.0
    return out


def _breadth_bonus(verdicts: list[SkillVerdict]) -> float:
    verified_groups: set[str] = set()
    for verdict in verdicts:
        if verdict.tier in (TIER_APPLIED, TIER_MASTERED):
            verified_groups.update(ontology.groups_for(verdict.skill))
    # 1 area = 0, then +1.25 per additional area, capped.
    return round(min(MAX_BREADTH_BONUS, max(0, len(verified_groups) - 1) * 1.25), 2)


def score_candidate(
    candidate: str,
    resume: ResumeProfile,
    github: GithubProfile | None,
    verdicts: list[SkillVerdict],
    *,
    boolean_mode: bool = False,
) -> ReadinessReport:
    from .. import __version__

    report = ReadinessReport(
        candidate=candidate,
        github_username=github.username if github else None,
        resume=resume,
        github=github,
        engine_version=__version__,
    )

    for verdict in verdicts:
        verdict.verification = compute_verification(verdict, boolean_mode=boolean_mode)

    report.verdicts = sorted(
        verdicts,
        key=lambda v: (not v.claimed, -v.weight * max(v.verification, 0.01), v.skill),
    )

    scored = [v for v in verdicts if v.claimed and v.verifiable and v.weight > 0]
    report.claimed_count = sum(1 for v in verdicts if v.claimed)
    report.verifiable_claims = len(scored)
    report.verified_count = sum(1 for v in scored if v.status == "verified")
    report.weakly_verified_count = sum(1 for v in scored if v.status == "weakly_verified")
    report.unverified_count = sum(1 for v in scored if v.status == "unverified")

    capacity = _capacity(github)
    report.confidence = capacity

    if not scored:
        report.warnings.append(
            "No verifiable technical skills were recognised in this CV, so no "
            "readiness score can be computed. This usually means the CV is "
            "non-technical or its text layer failed to extract."
        )
        return report

    total_weight = sum(v.weight for v in scored)
    mean_weight = total_weight / len(scored)
    prior_mass = PRIOR_CLAIMS * mean_weight

    raw_ratio = sum(v.weight * v.verification for v in scored) / total_weight
    report.raw_ratio = raw_ratio * 100.0
    report.base_score = (
        (sum(v.weight * v.verification for v in scored) + prior_mass * PRIOR_VERIFICATION)
        / (total_weight + prior_mass)
    ) * 100.0
    report.shrinkage = report.base_score - report.raw_ratio

    unverified_weight = sum(v.weight for v in scored if v.tier == TIER_NONE)
    unverified_share = unverified_weight / total_weight if total_weight else 0.0
    report.integrity_penalty = round(MAX_INTEGRITY_PENALTY * unverified_share * capacity, 2)

    report.breadth_bonus = _breadth_bonus(verdicts)
    report.score = max(0.0, min(100.0,
                                report.base_score - report.integrity_penalty + report.breadth_bonus))
    report.category_scores = _category_scores(verdicts)

    # -- warnings: everything a recruiter must know before trusting this ----
    if github is None or not github.found:
        report.warnings.append(
            "No GitHub profile was resolved for this candidate, so no claim could be "
            "verified. Treat this score as 'unevidenced', not as 'unqualified'."
        )
    else:
        if github.error:
            report.warnings.append(f"GitHub mining was incomplete: {github.error}")
        if capacity < 0.35:
            report.warnings.append(
                f"Low evidence capacity ({capacity:.0%}): little public code was available "
                "to inspect, so this score rests on a thin sample."
            )
        if any(r.tree_truncated for r in github.repos):
            report.warnings.append(
                "At least one repository tree was truncated by the GitHub API; "
                "some files were not visible to the sampler."
            )

    if report.verifiable_claims < THIN_CLAIM_THRESHOLD:
        report.warnings.append(
            f"This CV asserts only {report.verifiable_claims} verifiable technical "
            f"skill(s), so the ratio behind the score rests on very little. It has "
            f"been shrunk toward the cohort prior by {abs(report.shrinkage):.1f} "
            "points; read the score as provisional."
        )

    unclaimed = [v.skill for v in verdicts if v.unclaimed_evidence]
    if unclaimed:
        report.warnings.append(
            "Demonstrated in code but absent from the CV (not counted in the score): "
            + ", ".join(sorted(unclaimed)[:10])
        )

    if resume.used_ocr:
        report.warnings.append(
            "This CV had no text layer and was read via OCR; skill extraction may be incomplete."
        )

    return report
