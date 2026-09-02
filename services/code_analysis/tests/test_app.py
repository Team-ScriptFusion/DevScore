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


def test_analyze_repos_requires_fields(client):
    resp = client.post("/analyze-repos", json={})
    assert resp.status_code == 400


def test_analyze_repos_returns_result(client, monkeypatch):
    fake_result = {
        "repos": [],
        "summary": {"avg_complexity_overall": None, "total_loc_overall": 0, "qualifying_repo_count": 0},
    }
    monkeypatch.setattr(app_module, "run_analysis", lambda username, repo_names, token: fake_result)
    resp = client.post(
        "/analyze-repos",
        json={"github_username": "octocat", "access_token": "tok", "repo_names": []},
    )
    assert resp.status_code == 200
    assert resp.get_json() == fake_result


def test_analyze_repos_invalid_token_returns_401(client, monkeypatch):
    def raise_invalid(username, repo_names, token):
        raise app_module.InvalidTokenError()

    monkeypatch.setattr(app_module, "run_analysis", raise_invalid)
    resp = client.post(
        "/analyze-repos",
        json={"github_username": "octocat", "access_token": "bad", "repo_names": ["a"]},
    )
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "invalid_token"}


def test_analyze_repos_unexpected_error_returns_json_500(client, monkeypatch):
    def raise_boom(username, repo_names, token):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "run_analysis", raise_boom)
    resp = client.post(
        "/analyze-repos",
        json={"github_username": "octocat", "access_token": "tok", "repo_names": ["a"]},
    )
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "analysis_failed"


def test_unauthorized_without_api_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "secret123")
    resp = client.post("/analyze-repos", json={})
    assert resp.status_code == 401
