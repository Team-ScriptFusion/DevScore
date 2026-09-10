from wvr_calculator import compute_wvr


def test_compute_wvr_basic_formula():
    weights = {"backend_languages": 0.4, "code_quality": 0.2}
    vi = {"backend_languages": 1.0}
    # (0.4*1.0 + 0.2*0.5) / 0.6 * 100 = 0.5/0.6*100 = 83.33
    assert compute_wvr(weights, vi, code_quality_vi=0.5) == 83.33


def test_compute_wvr_missing_category_in_vi_treated_as_zero():
    weights = {"backend_languages": 0.5, "frontend_frameworks": 0.5}
    vi = {"backend_languages": 1.0}
    assert compute_wvr(weights, vi, code_quality_vi=0.0) == 50.0


def test_compute_wvr_zero_total_weight_returns_zero():
    assert compute_wvr({}, {}, 0.0) == 0.0


def test_compute_wvr_full_marks_gives_one_hundred():
    weights = {"backend_languages": 1.0}
    assert compute_wvr(weights, {"backend_languages": 1.0}, code_quality_vi=0.0) == 100.0
