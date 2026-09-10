import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_build_vi_requires_fields(client):
    resp = client.post("/build-vi", json={})
    assert resp.status_code == 400


def test_build_vi_returns_result(client, monkeypatch):
    monkeypatch.setattr(
        app_module.main, "run_build_vi",
        lambda rows, summary, range_hint: {"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.3},
    )
    resp = client.post(
        "/build-vi",
        json={"skill_verification_rows": [], "code_analysis_summary": None, "range_hint": {}},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.3}


def test_assign_split_requires_fields(client):
    resp = client.post("/assign-split", json={})
    assert resp.status_code == 400


def test_assign_split_returns_result(client, monkeypatch):
    monkeypatch.setattr(app_module.main, "run_assign_split", lambda ids, frac, seed, existing: {"a": "train"})
    resp = client.post("/assign-split", json={"user_ids": ["a"], "train_fraction": 0.7, "seed": 1})
    assert resp.status_code == 200
    assert resp.get_json() == {"assignments": {"a": "train"}}


def test_fit_weights_requires_fields(client):
    resp = client.post("/fit-weights", json={})
    assert resp.status_code == 400


def test_fit_weights_returns_result(client, monkeypatch):
    fake_result = {"status": "completed", "weights_version": "v1", "weights": [], "cv_score": None}
    monkeypatch.setattr(app_module.main, "run_fit", lambda rows, categories, version: fake_result)
    resp = client.post(
        "/fit-weights",
        json={
            "training_rows": [{"vi_by_category": {}, "code_quality_vi": 0, "expert_score": 1}],
            "categories": ["cat_a"],
            "weights_version": "v1",
        },
    )
    assert resp.status_code == 200
    assert resp.get_json() == fake_result


def test_fit_weights_unexpected_error_returns_json_500(client, monkeypatch):
    def raise_boom(rows, categories, version):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module.main, "run_fit", raise_boom)
    resp = client.post(
        "/fit-weights",
        json={"training_rows": [{}], "categories": ["cat_a"], "weights_version": "v1"},
    )
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "fit_failed"


def test_compute_wvr_requires_fields(client):
    resp = client.post("/compute-wvr", json={})
    assert resp.status_code == 400


def test_compute_wvr_returns_result(client, monkeypatch):
    monkeypatch.setattr(app_module.main, "run_wvr", lambda weights, vi, cq: 42.0)
    resp = client.post(
        "/compute-wvr",
        json={
            "weights": [{"category": "cat_a", "weight": 1.0}],
            "vi_by_category": {"cat_a": 0.5},
            "code_quality_vi": 0.0,
        },
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"wvr_score": 42.0}


def test_validate_requires_fields(client):
    resp = client.post("/validate", json={})
    assert resp.status_code == 400


def test_validate_returns_result(client, monkeypatch):
    fake_result = {"spearman_rho": 0.5, "mae": 3.2, "sample_size": 10}
    monkeypatch.setattr(app_module.main, "run_validate", lambda rows, weights, pairs=None: fake_result)
    resp = client.post(
        "/validate",
        json={
            "test_rows": [{"vi_by_category": {}, "code_quality_vi": 0, "expert_score": 1}],
            "weights": [{"category": "cat_a", "weight": 1.0}],
        },
    )
    assert resp.status_code == 200
    assert resp.get_json() == fake_result


def test_unauthorized_without_api_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "secret123")
    resp = client.post("/fit-weights", json={})
    assert resp.status_code == 401


def test_predict_trained_requires_counts(client):
    resp = client.post("/predict-trained", json={})
    assert resp.status_code == 400


def test_predict_trained_returns_result(client, monkeypatch):
    monkeypatch.setattr(app_module.rf_model, "build_features", lambda counts: {"claimed_skills": 9})
    monkeypatch.setattr(app_module.rf_model, "predict_readiness", lambda features: 88.5)
    resp = client.post(
        "/predict-trained",
        json={"counts": {"claimed": 9, "verified": 8, "weakly_verified": 1, "unverified": 0}},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["predicted_score"] == 88.5
    assert body["model"] == "random_forest_v1"


def test_predict_trained_unexpected_error_returns_json_500(client, monkeypatch):
    def raise_boom(counts):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module.rf_model, "build_features", raise_boom)
    resp = client.post("/predict-trained", json={"counts": {}})
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "predict_failed"
