import numpy as np

from fake_data import CATEGORIES, TRUE_WEIGHTS, generate_fake_dataset
from weight_fitting import cross_validate, fit_weights


def test_fit_weights_recovers_known_coefficients_within_tolerance():
    rows = generate_fake_dataset(300, seed=10, noise_scale=1.0)
    weights = fit_weights(rows, CATEGORIES)
    for key, true_value in TRUE_WEIGHTS.items():
        assert abs(weights[key] - true_value) < 0.08


def test_fit_weights_all_non_negative():
    rows = generate_fake_dataset(100, seed=11)
    weights = fit_weights(rows, CATEGORIES)
    assert all(w >= 0 for w in weights.values())


def test_fit_weights_clips_negative_correlation_to_zero_not_negative():
    # A category that's negatively correlated with expert_score: an
    # unconstrained least-squares fit would assign it a negative
    # coefficient. nnls must not (module spec §8 step 5).
    rows = [
        {"vi_by_category": {"cat_a": 0.1}, "code_quality_vi": 0.9, "expert_score": 90.0},
        {"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.5, "expert_score": 50.0},
        {"vi_by_category": {"cat_a": 0.9}, "code_quality_vi": 0.1, "expert_score": 10.0},
    ]
    x = np.array([[0.1, 0.9], [0.5, 0.5], [0.9, 0.1]])
    y = np.array([0.9, 0.5, 0.1])
    unconstrained, *_ = np.linalg.lstsq(x, y, rcond=None)
    assert unconstrained[0] < 0  # sanity: confirms this case is a real trap

    weights = fit_weights(rows, ["cat_a"])
    assert weights["cat_a"] >= 0


def test_cross_validate_recovers_reasonable_fit_quality():
    rows = generate_fake_dataset(200, seed=12, noise_scale=1.5)
    score = cross_validate(rows, CATEGORIES, k=5, seed=0)
    assert score is not None
    assert score > 0.5


def test_cross_validate_returns_none_when_too_little_data():
    rows = generate_fake_dataset(2, seed=13)
    assert cross_validate(rows, CATEGORIES, k=5, seed=0) is None
