from exclusion_rules import (
    MAX_TARBALL_BYTES,
    MIN_TOTAL_LINES,
    is_empty,
    is_fork,
    is_too_large,
    matches_tutorial_heuristic,
)


def test_is_fork_true_when_flag_set():
    assert is_fork({"fork": True}) is True


def test_is_fork_false_when_flag_missing():
    assert is_fork({}) is False


def test_is_too_large_true_over_limit():
    assert is_too_large(MAX_TARBALL_BYTES + 1) is True


def test_is_too_large_false_under_limit():
    assert is_too_large(1000) is False


def test_is_too_large_false_when_unknown():
    assert is_too_large(None) is False


def test_is_empty_true_under_minimum():
    assert is_empty(MIN_TOTAL_LINES - 1) is True


def test_is_empty_false_at_minimum():
    assert is_empty(MIN_TOTAL_LINES) is False


def test_matches_tutorial_heuristic_case_insensitive():
    assert matches_tutorial_heuristic("My-Tutorial-App") is True


def test_matches_tutorial_heuristic_various_patterns():
    assert matches_tutorial_heuristic("react-bootcamp-2024") is True
    assert matches_tutorial_heuristic("hello-world") is True
    assert matches_tutorial_heuristic("js-starter") is True


def test_matches_tutorial_heuristic_no_match():
    assert matches_tutorial_heuristic("fraud-detection-model") is False
