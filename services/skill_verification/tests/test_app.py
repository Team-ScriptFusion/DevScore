import base64
from unittest.mock import patch

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


def test_fetch_evidence_requires_fields(client):
    resp = client.post("/fetch-evidence", json={})
    assert resp.status_code == 400


def test_fetch_evidence_returns_repos(client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "fetch_repos",
        lambda username, token: {"repos": [{"name": "a"}], "rate_limited": False},
    )
    resp = client.post(
        "/fetch-evidence",
        json={"github_username": "octocat", "access_token": "tok"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["repos"] == [{"name": "a"}]


def test_fetch_evidence_invalid_token_returns_401(client, monkeypatch):
    def raise_invalid(username, token):
        raise app_module.InvalidTokenError()

    monkeypatch.setattr(app_module, "fetch_repos", raise_invalid)
    resp = client.post(
        "/fetch-evidence",
        json={"github_username": "octocat", "access_token": "bad"},
    )
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "invalid_token"}


def test_match_skills_route(client):
    repos = [{"name": "app", "languages": {"Python": 5000}, "readme_text": ""}]
    resp = client.post(
        "/match-skills",
        json={"claimed_skills": ["Python"], "repos": repos},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body[0]["method"] == "direct_match"


def test_fetch_evidence_unexpected_error_returns_json_500(client, monkeypatch):
    def boom(username, token):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(app_module, "fetch_repos", boom)
    resp = client.post(
        "/fetch-evidence",
        json={"github_username": "octocat", "access_token": "tok"},
    )
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "fetch_evidence_failed"}


def test_match_skills_unexpected_error_returns_json_500(client, monkeypatch):
    def boom(claimed_skills, repos):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(app_module, "match_skills", boom)
    resp = client.post(
        "/match-skills",
        json={"claimed_skills": ["Python"], "repos": []},
    )
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "match_skills_failed"}


def test_unauthorized_without_api_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "secret123")
    resp = client.get("/fetch-evidence")
    resp = client.post("/fetch-evidence", json={})
    assert resp.status_code == 401
