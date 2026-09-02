from unittest.mock import patch

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
