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


def test_predict_readiness_returns_score_in_bounds():
    features = {
        "claimed_skills": 9,
        "verified": 8,
        "weakly_verified": 1,
        "unverified": 0,
        "verify_ratio": 0.889,
    }
    score = predict_readiness(features)
    assert 0.0 <= score <= 100.0


def test_predict_readiness_high_evidence_scores_higher_than_low_evidence():
    high_evidence = predict_readiness(
        {"claimed_skills": 9, "verified": 8, "weakly_verified": 1, "unverified": 0, "verify_ratio": 0.889}
    )
    low_evidence = predict_readiness(
        {"claimed_skills": 20, "verified": 1, "weakly_verified": 0, "unverified": 19, "verify_ratio": 0.05}
    )
    assert high_evidence > low_evidence
