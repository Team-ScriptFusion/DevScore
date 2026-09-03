"""Section 10's 'rate-limit backoff logic (mock the GitHub API response
headers)' — GraphQL reports remaining budget in the response body
(`rateLimit.remaining`), not response headers, since this client uses
GraphQL rather than REST. Mock that instead."""

from unittest.mock import MagicMock, patch

from github_client import GitHubEvidenceClient


def _mock_response(remaining, repositories_nodes, has_next=False, end_cursor=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "data": {
            "user": {
                "repositories": {
                    "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                    "nodes": repositories_nodes,
                }
            },
            "rateLimit": {"remaining": remaining, "resetAt": "2026-01-01T00:00:00Z", "cost": 1},
        }
    }
    resp.raise_for_status = MagicMock()
    return resp


def test_backs_off_when_remaining_is_low():
    client = GitHubEvidenceClient(token="fake-token", min_remaining=200)
    with patch.object(client.session, "post", return_value=_mock_response(50, [])) as mock_post, \
         patch("github_client.time.sleep") as mock_sleep:
        client.fetch_all_public_repos("someuser")
        mock_sleep.assert_called_once()
        mock_post.assert_called_once()


def test_no_backoff_when_remaining_is_healthy():
    client = GitHubEvidenceClient(token="fake-token", min_remaining=200)
    with patch.object(client.session, "post", return_value=_mock_response(4500, [])), \
         patch("github_client.time.sleep") as mock_sleep:
        client.fetch_all_public_repos("someuser")
        mock_sleep.assert_not_called()


def test_missing_user_raises_clear_error():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": {"user": None, "rateLimit": {"remaining": 5000, "resetAt": "", "cost": 1}}}
    resp.raise_for_status = MagicMock()
    client = GitHubEvidenceClient(token="fake-token")
    with patch.object(client.session, "post", return_value=resp):
        try:
            client.fetch_all_public_repos("ghost-user")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "not found" in str(e)


def test_token_required():
    try:
        GitHubEvidenceClient(token="")
        assert False, "expected ValueError"
    except ValueError:
        pass
