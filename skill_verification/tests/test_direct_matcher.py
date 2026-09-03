from datetime import datetime

from direct_matcher import match_direct
from models import MatchMethod, RepoEvidence, SkillStatus


def _repo(name="repo1", languages=None, manifests=None):
    return RepoEvidence(
        repo_name=name, is_fork=False, description="", languages=languages or {},
        manifests=manifests or {}, readme_text="", commit_count=0, last_commit_at=None,
    )


def test_direct_language_match():
    repo = _repo(languages={"Python": 8000, "HTML": 200})
    result = match_direct("Python", [repo])
    assert result is not None
    assert result.status == SkillStatus.VERIFIED
    assert result.method == MatchMethod.DIRECT_MATCH
    assert result.confidence == 1.0
    assert result.evidence_repo == "repo1"


def test_trivial_byte_count_is_not_a_match():
    # Regression test for the real-run false positive: a handful of bytes
    # (e.g. a single generated file) must not verify a language claim.
    repo = _repo(languages={"C++": 40, "Dart": 39960})
    result = match_direct("C++", [repo])
    assert result is None


def test_low_share_below_threshold_is_not_a_match():
    repo = _repo(languages={"CSS": 100, "JavaScript": 9900})
    result = match_direct("CSS", [repo])
    # 1% share, below MIN_LANGUAGE_SHARE
    assert result is None


def test_dependency_marker_match():
    repo = _repo(manifests={"package.json": '{"dependencies": {"react": "^18.0.0"}}'})
    result = match_direct("React.js", [repo])
    assert result is not None
    assert result.status == SkillStatus.VERIFIED
    assert "react" in result.reason.lower()


def test_no_match_returns_none():
    repo = _repo(languages={"Python": 8000})
    result = match_direct("Kubernetes", [repo])
    assert result is None


def test_scoped_to_repo_ignores_other_repos():
    repo_a = _repo(name="repo-a", languages={"Python": 8000})
    repo_b = _repo(name="repo-b", languages={"JavaScript": 8000})
    result = match_direct("Python", [repo_a, repo_b], scope_repo_name="repo-b")
    assert result is None
