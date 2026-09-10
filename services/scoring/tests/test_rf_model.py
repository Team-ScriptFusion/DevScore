from rf_model import build_features, predict_readiness


def test_build_features_computes_verify_ratio():
    counts = {"claimed": 9, "verified": 8, "weakly_verified": 1, "unverified": 0}
    features = build_features(counts)
    assert features == {
        "claimed_skills": 9,
        "verified": 8,
        "weakly_verified": 1,
        "unverified": 0,
        "verify_ratio": 0.889,
    }


def test_build_features_zero_claimed_gives_zero_ratio():
    counts = {"claimed": 0, "verified": 0, "weakly_verified": 0, "unverified": 0}
    features = build_features(counts)
    assert features["verify_ratio"] == 0.0


def test_build_features_missing_keys_default_to_zero():
    assert build_features({}) == {
        "claimed_skills": 0,
        "verified": 0,
        "weakly_verified": 0,
        "unverified": 0,
        "verify_ratio": 0.0,
    }


def test_predict_readiness_returns_all_three_scores_in_bounds():
    features = {
        "claimed_skills": 9,
        "verified": 8,
        "weakly_verified": 1,
        "unverified": 0,
        "verify_ratio": 0.889,
    }
    scores = predict_readiness(features)
    assert set(scores.keys()) == {"linear_regression", "random_forest_tuned", "ensemble"}
    for value in scores.values():
        assert 0.0 <= value <= 100.0


def test_predict_readiness_ensemble_is_midpoint_of_components():
    features = {
        "claimed_skills": 9,
        "verified": 8,
        "weakly_verified": 1,
        "unverified": 0,
        "verify_ratio": 0.889,
    }
    scores = predict_readiness(features)
    expected_ensemble = round((scores["linear_regression"] + scores["random_forest_tuned"]) / 2, 2)
    assert abs(scores["ensemble"] - expected_ensemble) < 0.02


def test_predict_readiness_high_evidence_scores_higher_than_low_evidence():
    high_evidence = predict_readiness(
        {"claimed_skills": 9, "verified": 8, "weakly_verified": 1, "unverified": 0, "verify_ratio": 0.889}
    )
    low_evidence = predict_readiness(
        {"claimed_skills": 20, "verified": 1, "weakly_verified": 0, "unverified": 19, "verify_ratio": 0.05}
    )
    assert high_evidence["linear_regression"] > low_evidence["linear_regression"]
    assert high_evidence["ensemble"] > low_evidence["ensemble"]
