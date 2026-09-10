"""Agreement between two experts scoring the same overlapping students
(module spec §7) — computed before investing in weight-fitting, so
'expert judgment' is confirmed to be a stable target first."""

import krippendorff
from scipy.stats import spearmanr


def compute_inter_rater(score_pairs: list) -> dict:
    scores_a = [pair[0] for pair in score_pairs]
    scores_b = [pair[1] for pair in score_pairs]

    rho, _ = spearmanr(scores_a, scores_b)
    alpha = krippendorff.alpha(reliability_data=[scores_a, scores_b], level_of_measurement="interval")

    return {
        "spearman_rho": round(float(rho), 4),
        "alpha": round(float(alpha), 4),
        "sample_size": len(score_pairs),
    }
