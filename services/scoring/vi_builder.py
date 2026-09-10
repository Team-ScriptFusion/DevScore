"""Combines Module 1 (skill_verification) and Module 2 (code_analysis_
summary) outputs into per-skill-category and code-quality Vi values
(module spec §6)."""

UNVERIFIED_FLOOR = 0.1


def build_skill_vi(verified: bool, confidence) -> float:
    """confidence if verified, else a fixed floor (not 0.0 — see module
    spec §6 step 1)."""
    if verified and confidence is not None:
        return confidence
    return UNVERIFIED_FLOOR


def build_category_vi(skill_rows: list) -> dict:
    """Groups skill_rows by category (null -> 'uncategorized') and averages
    build_skill_vi within each group, to keep the regression's input
    dimensionality small (module spec §6 step 2 / §8 step 3)."""
    totals = {}
    counts = {}
    for row in skill_rows:
        category = row["category"] or "uncategorized"
        vi = build_skill_vi(row["verified"], row.get("confidence"))
        totals[category] = totals.get(category, 0.0) + vi
        counts[category] = counts.get(category, 0) + 1
    return {category: round(totals[category] / counts[category], 4) for category in totals}


def _normalize(value, lo, hi) -> float:
    if value is None or hi == lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def build_code_quality_vi(summary, range_hint: dict) -> float:
    """Min-max normalizes avg_complexity_overall/total_loc_overall against
    the training set's own range, averaging the two into one 0-1 feature
    (module spec §6 step 2; the exact normalization is a documented,
    non-load-bearing choice, per design spec §6)."""
    if not summary:
        return 0.0
    complexity_score = _normalize(
        summary.get("avg_complexity_overall"), range_hint["complexity_min"], range_hint["complexity_max"]
    )
    loc_score = _normalize(summary.get("total_loc_overall"), range_hint["loc_min"], range_hint["loc_max"])
    return round(0.5 * complexity_score + 0.5 * loc_score, 4)
