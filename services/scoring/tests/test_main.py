import main


def test_run_build_vi_combines_skill_and_code_signals():
    skill_rows = [{"category": "backend_languages", "verified": True, "confidence": 0.9}]
    summary = {"avg_complexity_overall": 5.0, "total_loc_overall": 500}
    range_hint = {"complexity_min": 1.0, "complexity_max": 9.0, "loc_min": 0, "loc_max": 1000}
    result = main.run_build_vi(skill_rows, summary, range_hint)
    assert result == {"vi_by_category": {"backend_languages": 0.9}, "code_quality_vi": 0.5}


def test_run_assign_split_delegates_to_split_module():
    result = main.run_assign_split(["a", "b", "c", "d"], 0.5, seed=1)
    assert set(result.keys()) == {"a", "b", "c", "d"}
    assert set(result.values()) <= {"train", "test"}


def test_run_fit_returns_expected_shape():
    rows = [
        {"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.5, "expert_score": 50.0},
        {"vi_by_category": {"cat_a": 1.0}, "code_quality_vi": 1.0, "expert_score": 100.0},
        {"vi_by_category": {"cat_a": 0.0}, "code_quality_vi": 0.0, "expert_score": 0.0},
    ]
    result = main.run_fit(rows, ["cat_a"], "v1_test")
    assert result["status"] == "completed"
    assert result["weights_version"] == "v1_test"
    assert {w["category"] for w in result["weights"]} == {"cat_a", "code_quality"}


def test_run_wvr_applies_stored_weight_shape():
    weights_list = [{"category": "cat_a", "weight": 1.0}]
    result = main.run_wvr(weights_list, {"cat_a": 0.5}, code_quality_vi=0.0)
    assert result == 50.0


def test_run_validate_includes_inter_rater_when_pairs_given():
    weights_list = [{"category": "cat_a", "weight": 1.0}]
    test_rows = [{"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.0, "expert_score": 50.0}]
    result = main.run_validate(test_rows, weights_list, expert_pairs=[(80, 82), (60, 58)])
    assert "inter_rater" in result
    assert "spearman_rho" in result["inter_rater"]


def test_run_validate_omits_inter_rater_when_no_pairs():
    weights_list = [{"category": "cat_a", "weight": 1.0}]
    test_rows = [{"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.0, "expert_score": 50.0}]
    result = main.run_validate(test_rows, weights_list)
    assert "inter_rater" not in result
