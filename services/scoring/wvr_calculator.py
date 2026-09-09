"""WVR formula application against an already-frozen weight set (module
spec's WVR = Sigma(Wi*Vi) / SigmaWi * 100)."""


def compute_wvr(weights: dict, vi_by_category: dict, code_quality_vi: float) -> float:
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return 0.0

    weighted_sum = sum(
        weight * vi_by_category.get(category, 0.0)
        for category, weight in weights.items()
        if category != "code_quality"
    )
    weighted_sum += weights.get("code_quality", 0.0) * code_quality_vi

    return round(100 * weighted_sum / total_weight, 2)
