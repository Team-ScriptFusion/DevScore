"""Phase 2 — per-repo -> per-student rollup (module spec section 4/8)."""


def build_summary(repo_results: list) -> dict:
    """
    Aggregates per-repo results into one per-student summary, computed
    ONLY from repos where `included` is True. A qualifying repo with no
    measurable complexity (avg_cyclomatic_complexity is None, e.g. lizard
    found no functions) still counts toward qualifying_repo_count and its
    line count still sums in, but it is excluded from the complexity
    average itself.
    """
    included = [r for r in repo_results if r.get("included")]
    if not included:
        return {"avg_complexity_overall": None, "total_loc_overall": 0, "qualifying_repo_count": 0}

    complexities = [
        r["avg_cyclomatic_complexity"] for r in included
        if r.get("avg_cyclomatic_complexity") is not None
    ]
    avg_complexity_overall = round(sum(complexities) / len(complexities), 2) if complexities else None
    total_loc_overall = sum(r.get("total_lines") or 0 for r in included)

    return {
        "avg_complexity_overall": avg_complexity_overall,
        "total_loc_overall": total_loc_overall,
        "qualifying_repo_count": len(included),
    }
