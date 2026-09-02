from aggregation import build_summary


def test_build_summary_averages_across_included_repos():
    repos = [
        {"included": True, "avg_cyclomatic_complexity": 2.0, "total_lines": 100},
        {"included": True, "avg_cyclomatic_complexity": 4.0, "total_lines": 200},
    ]
    assert build_summary(repos) == {
        "avg_complexity_overall": 3.0,
        "total_loc_overall": 300,
        "qualifying_repo_count": 2,
    }


def test_build_summary_excludes_non_included_repos():
    repos = [
        {"included": True, "avg_cyclomatic_complexity": 2.0, "total_lines": 100},
        {"included": False, "avg_cyclomatic_complexity": None, "total_lines": None},
    ]
    assert build_summary(repos) == {
        "avg_complexity_overall": 2.0,
        "total_loc_overall": 100,
        "qualifying_repo_count": 1,
    }


def test_build_summary_no_included_repos_returns_nulls():
    repos = [{"included": False, "avg_cyclomatic_complexity": None, "total_lines": None}]
    assert build_summary(repos) == {
        "avg_complexity_overall": None,
        "total_loc_overall": 0,
        "qualifying_repo_count": 0,
    }


def test_build_summary_empty_list():
    assert build_summary([]) == {
        "avg_complexity_overall": None,
        "total_loc_overall": 0,
        "qualifying_repo_count": 0,
    }


def test_build_summary_counts_qualifying_repo_with_no_functions_found():
    # An included repo where lizard found nothing to measure (e.g. a repo
    # of only config files that passed the line-count filter) should still
    # count toward qualifying_repo_count, and its LOC (0) still sums in,
    # but it must not be averaged into avg_complexity_overall as if it
    # were a real 0-complexity codebase.
    repos = [
        {"included": True, "avg_cyclomatic_complexity": None, "total_lines": 0},
        {"included": True, "avg_cyclomatic_complexity": 2.0, "total_lines": 50},
    ]
    assert build_summary(repos) == {
        "avg_complexity_overall": 2.0,
        "total_loc_overall": 50,
        "qualifying_repo_count": 2,
    }
