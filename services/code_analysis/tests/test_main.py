from unittest.mock import patch

import pytest
import requests

import repo_fetch
import main


def test_analyze_one_repo_excludes_forks():
    with patch("repo_fetch.fetch_repo_metadata", return_value={"fork": True}):
        result = main.analyze_one_repo("octocat", "some-fork", "token")
    assert result["repo_name"] == "some-fork"
    assert result["included"] is False
    assert result["excluded_reason"] == "fork"
    assert result["avg_cyclomatic_complexity"] is None


def test_analyze_one_repo_excludes_too_large():
    with patch("repo_fetch.fetch_repo_metadata", return_value={"fork": False}), \
         patch("repo_fetch.download_tarball", side_effect=repo_fetch.TarballTooLargeError()):
        result = main.analyze_one_repo("octocat", "huge-repo", "token")
    assert result["included"] is False
    assert result["excluded_reason"] == "too_large"


def test_analyze_one_repo_excludes_empty(tmp_path):
    with patch("repo_fetch.fetch_repo_metadata", return_value={"fork": False}), \
         patch("repo_fetch.download_tarball", return_value=b"fake-tarball-bytes"), \
         patch("repo_fetch.extract_and_filter", return_value=(str(tmp_path), [])), \
         patch("repo_fetch.cleanup") as mock_cleanup, \
         patch("static_analysis.analyze_files", return_value={
             "language": None, "avg_cyclomatic_complexity": None,
             "total_functions": 0, "total_lines": 5, "max_nesting_depth": 0,
         }):
        result = main.analyze_one_repo("octocat", "tiny-repo", "token")
    assert result["included"] is False
    assert result["excluded_reason"] == "empty"
    mock_cleanup.assert_called_once()


def test_analyze_one_repo_flags_tutorial_but_still_returns_metrics(tmp_path):
    fake_metrics = {
        "language": "python", "avg_cyclomatic_complexity": 1.5,
        "total_functions": 3, "total_lines": 40, "max_nesting_depth": 2,
    }
    with patch("repo_fetch.fetch_repo_metadata", return_value={"fork": False}), \
         patch("repo_fetch.download_tarball", return_value=b"fake-tarball-bytes"), \
         patch("repo_fetch.extract_and_filter", return_value=(str(tmp_path), ["a.py"])), \
         patch("repo_fetch.cleanup"), \
         patch("static_analysis.analyze_files", return_value=fake_metrics):
        result = main.analyze_one_repo("octocat", "python-tutorial", "token")
    assert result["included"] is False
    assert result["excluded_reason"] == "tutorial_clone_heuristic"
    assert result["avg_cyclomatic_complexity"] == 1.5
    assert result["total_functions"] == 3


def test_analyze_one_repo_includes_qualifying_repo(tmp_path):
    fake_metrics = {
        "language": "python", "avg_cyclomatic_complexity": 4.0,
        "total_functions": 10, "total_lines": 300, "max_nesting_depth": 3,
    }
    with patch("repo_fetch.fetch_repo_metadata", return_value={"fork": False}), \
         patch("repo_fetch.download_tarball", return_value=b"fake-tarball-bytes"), \
         patch("repo_fetch.extract_and_filter", return_value=(str(tmp_path), ["a.py"])), \
         patch("repo_fetch.cleanup"), \
         patch("static_analysis.analyze_files", return_value=fake_metrics):
        result = main.analyze_one_repo("octocat", "real-project", "token")
    assert result["included"] is True
    assert result["excluded_reason"] is None
    assert result["avg_cyclomatic_complexity"] == 4.0


def test_analyze_one_repo_records_fetch_failed_on_unexpected_error():
    # Anything that isn't one of the modelled exclusions (a 404/403/5xx from
    # GitHub, a corrupt tarball, a malformed Content-Length) must become a
    # per-repo fetch_failed result, never propagate out of this function.
    with patch("repo_fetch.fetch_repo_metadata",
               side_effect=requests.exceptions.HTTPError("404 Client Error: Not Found")):
        result = main.analyze_one_repo("octocat", "deleted-repo", "token")
    assert result["repo_name"] == "deleted-repo"
    assert result["included"] is False
    assert result["excluded_reason"] == "fetch_failed"
    assert result["language"] is None
    assert result["avg_cyclomatic_complexity"] is None
    assert result["total_lines"] is None


def test_analyze_one_repo_still_propagates_invalid_token():
    # A revoked token is not a per-repo failure — it must keep reaching the
    # route so the run answers 401, rather than being swallowed into 15
    # fetch_failed rows and a bogus 200.
    with patch("repo_fetch.fetch_repo_metadata", side_effect=repo_fetch.InvalidTokenError()):
        with pytest.raises(repo_fetch.InvalidTokenError):
            main.analyze_one_repo("octocat", "any-repo", "bad-token")


def test_run_analysis_continues_after_one_repo_fails(tmp_path):
    fake_metrics = {
        "language": "python", "avg_cyclomatic_complexity": 4.0,
        "total_functions": 10, "total_lines": 300, "max_nesting_depth": 3,
    }

    def fake_metadata(full_name, access_token):
        if full_name.endswith("/gone-repo"):
            raise requests.exceptions.HTTPError("404 Client Error: Not Found")
        return {"fork": False}

    with patch("repo_fetch.fetch_repo_metadata", side_effect=fake_metadata), \
         patch("repo_fetch.download_tarball", return_value=b"fake-tarball-bytes"), \
         patch("repo_fetch.extract_and_filter", return_value=(str(tmp_path), ["a.py"])), \
         patch("repo_fetch.cleanup"), \
         patch("static_analysis.analyze_files", return_value=fake_metrics):
        result = main.run_analysis(
            "octocat", ["first-project", "gone-repo", "second-project"], "token",
        )

    assert [r["repo_name"] for r in result["repos"]] == [
        "first-project", "gone-repo", "second-project",
    ]

    failed = result["repos"][1]
    assert failed["included"] is False
    assert failed["excluded_reason"] == "fetch_failed"

    for good in (result["repos"][0], result["repos"][2]):
        assert good["included"] is True
        assert good["excluded_reason"] is None
        assert good["avg_cyclomatic_complexity"] == 4.0
        assert good["total_lines"] == 300

    assert result["summary"] == {
        "avg_complexity_overall": 4.0,
        "total_loc_overall": 600,
        "qualifying_repo_count": 2,
    }


def test_run_analysis_aggregates_across_repos():
    with patch("main.analyze_one_repo") as mock_analyze:
        mock_analyze.side_effect = [
            {
                "repo_name": "a", "included": True, "excluded_reason": None,
                "language": "python", "avg_cyclomatic_complexity": 2.0,
                "total_functions": 5, "total_lines": 100, "max_nesting_depth": 2,
            },
            {
                "repo_name": "b", "included": False, "excluded_reason": "fork",
                "language": None, "avg_cyclomatic_complexity": None,
                "total_functions": None, "total_lines": None, "max_nesting_depth": None,
            },
        ]
        result = main.run_analysis("octocat", ["a", "b"], "token")
    assert len(result["repos"]) == 2
    assert result["summary"] == {
        "avg_complexity_overall": 2.0,
        "total_loc_overall": 100,
        "qualifying_repo_count": 1,
    }
