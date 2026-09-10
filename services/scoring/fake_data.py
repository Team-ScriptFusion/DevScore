"""
Synthetic training/validation data for this module's dev/test pass (design
spec §2/§10) — there is no real expert-score data yet. Rows are generated
from a KNOWN linear formula plus noise, so weight-fitting tests can assert
the recovered weights approximate the known coefficients. This module is
never imported by app.py's request-handling path; production /fit-weights
calls always take training_rows from the caller (Node), never generate
their own.
"""

import random

CATEGORIES = ["backend_languages", "frontend_frameworks", "testing_devops"]

# Sums to 1.0 so a near-noiseless fit's recovered weights land close to
# these values directly (see design spec §8's fitting approach).
TRUE_WEIGHTS = {
    "backend_languages": 0.40,
    "frontend_frameworks": 0.25,
    "testing_devops": 0.15,
    "code_quality": 0.20,
}


def generate_fake_dataset(n_students: int, seed: int, noise_scale: float = 3.0) -> list:
    """
    Generates `n_students` synthetic rows: random Vi values per category
    plus a random code_quality_vi, with expert_score computed from
    TRUE_WEIGHTS plus Gaussian noise (scaled in 0-100 points), clipped to
    [0, 100].
    """
    rng = random.Random(seed)
    rows = []
    for i in range(n_students):
        vi_by_category = {cat: rng.uniform(0.0, 1.0) for cat in CATEGORIES}
        code_quality_vi = rng.uniform(0.0, 1.0)

        true_score = 100 * (
            sum(TRUE_WEIGHTS[cat] * vi_by_category[cat] for cat in CATEGORIES)
            + TRUE_WEIGHTS["code_quality"] * code_quality_vi
        )
        noisy_score = max(0.0, min(100.0, true_score + rng.gauss(0, noise_scale)))

        rows.append({
            "user_id": f"fake-user-{i}",
            "vi_by_category": vi_by_category,
            "code_quality_vi": code_quality_vi,
            "expert_score": round(noisy_score, 2),
        })
    return rows
