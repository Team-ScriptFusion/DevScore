from vi_builder import build_category_vi, build_code_quality_vi, build_skill_vi


def test_build_skill_vi_verified_uses_confidence():
    assert build_skill_vi(True, 0.82) == 0.82


def test_build_skill_vi_unverified_uses_floor_not_zero():
    # "No evidence found" isn't the same claim as "evidence contradicts the
    # claim" — a flat zero would conflate them (module spec §6 step 1).
    assert build_skill_vi(False, None) == 0.1


def test_build_category_vi_averages_within_category():
    rows = [
        {"category": "backend_languages", "verified": True, "confidence": 0.8},
        {"category": "backend_languages", "verified": True, "confidence": 0.6},
        {"category": "frontend_frameworks", "verified": False, "confidence": None},
    ]
    result = build_category_vi(rows)
    assert result == {"backend_languages": 0.7, "frontend_frameworks": 0.1}


def test_build_category_vi_null_category_becomes_uncategorized():
    rows = [{"category": None, "verified": True, "confidence": 0.5}]
    assert build_category_vi(rows) == {"uncategorized": 0.5}


def test_build_category_vi_empty_input():
    assert build_category_vi([]) == {}


def test_build_code_quality_vi_normalizes_within_range():
    summary = {"avg_complexity_overall": 5.0, "total_loc_overall": 500}
    range_hint = {"complexity_min": 1.0, "complexity_max": 9.0, "loc_min": 0, "loc_max": 1000}
    assert build_code_quality_vi(summary, range_hint) == 0.5


def test_build_code_quality_vi_none_summary_returns_zero():
    range_hint = {"complexity_min": 1.0, "complexity_max": 9.0, "loc_min": 0, "loc_max": 1000}
    assert build_code_quality_vi(None, range_hint) == 0.0


def test_build_code_quality_vi_degenerate_range_returns_zero():
    summary = {"avg_complexity_overall": 5.0, "total_loc_overall": 0}
    range_hint = {"complexity_min": 5.0, "complexity_max": 5.0, "loc_min": 0, "loc_max": 0}
    assert build_code_quality_vi(summary, range_hint) == 0.0
