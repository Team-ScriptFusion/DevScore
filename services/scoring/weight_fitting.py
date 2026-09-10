"""Non-negative least-squares weight-fitting (module spec §8) — plain
linear regression, no Ridge/Lasso escalation in this pass (design spec
§3)."""

import random

import numpy as np
from scipy.optimize import nnls

from wvr_calculator import compute_wvr


def _feature_matrix(rows: list, categories: list) -> np.ndarray:
    return np.array([
        [row["vi_by_category"].get(cat, 0.0) for cat in categories] + [row["code_quality_vi"]]
        for row in rows
    ])


def fit_weights(rows: list, categories: list) -> dict:
    """
    Regresses per-category Vi + code_quality_vi against expert_score/100
    via nnls, which structurally cannot return a negative coefficient.
    """
    x = _feature_matrix(rows, categories)
    y = np.array([row["expert_score"] / 100.0 for row in rows])
    coefficients, _ = nnls(x, y)
    keys = list(categories) + ["code_quality"]
    return dict(zip(keys, (float(c) for c in coefficients)))


def cross_validate(rows: list, categories: list, k: int = 5, seed: int = 0):
    """
    K-fold cross-validation within `rows` (module spec §8 step 6) — fits on
    each fold's training rows, scores R^2 on that fold's held-out rows.
    Returns the average R^2, or None if there's too little data for even
    one usable fold.
    """
    n = len(rows)
    indices = list(range(n))
    random.Random(seed).shuffle(indices)
    folds = np.array_split(indices, k)

    r2_scores = []
    for fold in folds:
        test_idx = set(fold.tolist())
        train_rows = [rows[i] for i in range(n) if i not in test_idx]
        test_rows = [rows[i] for i in range(n) if i in test_idx]
        if not test_rows or len(train_rows) <= len(categories) + 1:
            continue

        weights = fit_weights(train_rows, categories)
        predictions = [
            compute_wvr(weights, row["vi_by_category"], row["code_quality_vi"])
            for row in test_rows
        ]
        actual = [row["expert_score"] for row in test_rows]
        mean_actual = sum(actual) / len(actual)
        ss_res = sum((a - p) ** 2 for a, p in zip(actual, predictions))
        ss_tot = sum((a - mean_actual) ** 2 for a in actual) or 1e-9
        r2_scores.append(1 - ss_res / ss_tot)

    return sum(r2_scores) / len(r2_scores) if r2_scores else None
