from direct_matcher import direct_match


def test_direct_match_exact_language():
    repos = [{"name": "my-app", "languages": {"Python": 8000}}]
    result = direct_match("Python", repos)
    assert result == {
        "skill": "Python",
        "verified": True,
        "method": "direct_match",
        "confidence": 1.0,
        "evidence_repo": "my-app",
        "reason": None,
    }


def test_direct_match_resolves_synonym():
    repos = [{"name": "frontend", "languages": {"JavaScript": 5000}}]
    result = direct_match("JS", repos)
    assert result["verified"] is True
    assert result["evidence_repo"] == "frontend"


def test_direct_match_no_matching_language():
    repos = [{"name": "my-app", "languages": {"Python": 8000}}]
    assert direct_match("Kubernetes", repos) is None


def test_direct_match_ignores_trivial_byte_count():
    repos = [{"name": "my-app", "languages": {"Python": 50}}]
    assert direct_match("Python", repos) is None


def test_direct_match_picks_repo_with_most_bytes():
    repos = [
        {"name": "small", "languages": {"Python": 300}},
        {"name": "big", "languages": {"Python": 9000}},
    ]
    result = direct_match("Python", repos)
    assert result["evidence_repo"] == "big"
