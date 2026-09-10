from validation import compute_validation


def test_compute_validation_perfect_agreement():
    weights = {"cat_a": 1.0}
    test_rows = [
        {"vi_by_category": {"cat_a": 0.2}, "code_quality_vi": 0.0, "expert_score": 20.0},
        {"vi_by_category": {"cat_a": 0.8}, "code_quality_vi": 0.0, "expert_score": 80.0},
        {"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.0, "expert_score": 50.0},
    ]
    result = compute_validation(test_rows, weights)
    assert result == {"spearman_rho": 1.0, "mae": 0.0, "sample_size": 3}


def test_compute_validation_measures_disagreement():
    weights = {"cat_a": 1.0}
    test_rows = [
        {"vi_by_category": {"cat_a": 0.9}, "code_quality_vi": 0.0, "expert_score": 20.0},
        {"vi_by_category": {"cat_a": 0.1}, "code_quality_vi": 0.0, "expert_score": 80.0},
    ]
    result = compute_validation(test_rows, weights)
    assert result["spearman_rho"] < 0
