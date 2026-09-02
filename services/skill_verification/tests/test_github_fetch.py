import base64
from unittest.mock import patch

import github_fetch
from github_fetch import InvalidTokenError, fetch_repos


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {"X-RateLimit-Remaining": "100"}
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._json

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


def _repo(name, fork=False, private=False, pushed_at="2026-08-01T00:00:00Z"):
    return {
        "name": name,
        "full_name": f"octocat/{name}",
        "fork": fork,
        "private": private,
        "pushed_at": pushed_at,
    }


def test_fetch_repos_happy_path():
    repo_list = [_repo("proj-a")]
    readme_b64 = base64.b64encode(b"# Proj A\nA machine learning project.").decode()

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/user/repos"):
            return FakeResponse(200, repo_list)
        if url.endswith("/languages"):
            return FakeResponse(200, {"Python": 5000})
        if url.endswith("/readme"):
            return FakeResponse(200, {"content": readme_b64})
        raise AssertionError(f"unexpected URL {url}")

    with patch("github_fetch.requests.get", side_effect=fake_get):
        result = fetch_repos("octocat", "token123")

    assert result["rate_limited"] is False
    assert len(result["repos"]) == 1
    repo = result["repos"][0]
    assert repo["name"] == "proj-a"
    assert repo["is_fork"] is False
    assert repo["languages"] == {"Python": 5000}
    assert "machine learning" in repo["readme_text"].lower()
    assert repo["pushed_at"] == "2026-08-01T00:00:00Z"


def test_fetch_repos_filters_private_and_forks():
    repo_list = [
        _repo("public-own"),
        _repo("private-own", private=True),
        _repo("forked", fork=True),
    ]

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/user/repos"):
            return FakeResponse(200, repo_list)
        if url.endswith("/languages"):
            return FakeResponse(200, {})
        if url.endswith("/readme"):
            return FakeResponse(200, {"content": ""})
        raise AssertionError(f"unexpected URL {url}")

    with patch("github_fetch.requests.get", side_effect=fake_get):
        result = fetch_repos("octocat", "token123")

    names = [r["name"] for r in result["repos"]]
    assert names == ["public-own"]


def test_fetch_repos_caps_at_max_repos(monkeypatch):
    monkeypatch.setattr(github_fetch, "MAX_REPOS", 2)
    repo_list = [_repo(f"repo-{i}") for i in range(5)]

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/user/repos"):
            return FakeResponse(200, repo_list)
        if url.endswith("/languages"):
            return FakeResponse(200, {})
        if url.endswith("/readme"):
            return FakeResponse(200, {"content": ""})
        raise AssertionError(f"unexpected URL {url}")

    with patch("github_fetch.requests.get", side_effect=fake_get):
        result = fetch_repos("octocat", "token123")

    assert len(result["repos"]) == 2


def test_fetch_repos_raises_on_invalid_token():
    def fake_get(url, headers=None, params=None, timeout=None):
        return FakeResponse(401, {"message": "Bad credentials"})

    with patch("github_fetch.requests.get", side_effect=fake_get):
        try:
            fetch_repos("octocat", "bad-token")
            assert False, "expected InvalidTokenError"
        except InvalidTokenError:
            pass


def test_fetch_repos_stops_early_when_rate_limited():
    repo_list = [_repo("repo-a"), _repo("repo-b"), _repo("repo-c")]
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/user/repos"):
            return FakeResponse(200, repo_list)
        if url.endswith("/languages"):
            return FakeResponse(200, {"Python": 1000}, headers={"X-RateLimit-Remaining": "5"})
        if url.endswith("/readme"):
            return FakeResponse(200, {"content": ""})
        raise AssertionError(f"unexpected URL {url}")

    with patch("github_fetch.requests.get", side_effect=fake_get):
        result = fetch_repos("octocat", "token123")

    assert result["rate_limited"] is True
    assert len(result["repos"]) == 1
    # repo list + repo-a's languages call only — readme skipped once rate
    # limited, and repo-b/repo-c never reached.
    assert len(calls) == 2


def test_fetch_repos_quota_already_exhausted_on_first_call():
    """
    An exhausted quota answers the very first call with 403/429 — there is no
    successful response carrying a low X-RateLimit-Remaining to trip the floor
    on, so this must degrade to an empty evidence set, not raise.
    """
    for status in (403, 429):
        def fake_get(url, headers=None, params=None, timeout=None, _status=status):
            return FakeResponse(_status, {"message": "API rate limit exceeded"})

        with patch("github_fetch.requests.get", side_effect=fake_get):
            result = fetch_repos("octocat", "token123")

        assert result == {"repos": [], "rate_limited": True}


def test_fetch_repos_quota_exhausted_mid_run_returns_repos_gathered_so_far():
    repo_list = [_repo("repo-a"), _repo("repo-b")]

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/user/repos"):
            return FakeResponse(200, repo_list)
        if url.endswith("/languages"):
            if "repo-b" in url:
                return FakeResponse(403, {"message": "API rate limit exceeded"})
            return FakeResponse(200, {"Python": 1000})
        if url.endswith("/readme"):
            return FakeResponse(200, {"content": ""})
        raise AssertionError(f"unexpected URL {url}")

    with patch("github_fetch.requests.get", side_effect=fake_get):
        result = fetch_repos("octocat", "token123")

    assert result["rate_limited"] is True
    assert [r["name"] for r in result["repos"]] == ["repo-a"]


def test_fetch_repos_quota_exhausted_on_readme_keeps_that_repo():
    repo_list = [_repo("repo-a"), _repo("repo-b")]

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/user/repos"):
            return FakeResponse(200, repo_list)
        if url.endswith("/languages"):
            return FakeResponse(200, {"Python": 1000})
        if url.endswith("/readme"):
            return FakeResponse(429, {"message": "API rate limit exceeded"})
        raise AssertionError(f"unexpected URL {url}")

    with patch("github_fetch.requests.get", side_effect=fake_get):
        result = fetch_repos("octocat", "token123")

    assert result["rate_limited"] is True
    # repo-a's languages were already paid for, so it is kept with no README;
    # repo-b is never reached.
    assert [r["name"] for r in result["repos"]] == ["repo-a"]
    assert result["repos"][0]["languages"] == {"Python": 1000}
    assert result["repos"][0]["readme_text"] == ""
