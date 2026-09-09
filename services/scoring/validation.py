"""Test-set validation stats: predicted WVR (frozen weights) vs each
row's expert_score (module spec §9)."""

from scipy.stats import spearmanr

from wvr_calculator import compute_wvr


def compute_validation(test_rows: list, weights: dict) -> dict:
    predictions = [
        compute_wvr(weights, row["vi_by_category"], row["code_quality_vi"])
        for row in test_rows
    ]
    actual = [row["expert_score"] for row in test_rows]

    rho, _ = spearmanr(predictions, actual)
    mae = sum(abs(p - a) for p, a in zip(predictions, actual)) / len(actual)

    return {
        "spearman_rho": round(float(rho), 4),
        "mae": round(mae, 2),
        "sample_size": len(test_rows),
    }
