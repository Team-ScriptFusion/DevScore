from models import MatchMethod, RepoEvidence, SkillStatus
from structural_matcher import match_structural


def _repo(name="repo1", languages=None, manifests=None):
    return RepoEvidence(
        repo_name=name, is_fork=False, description="", languages=languages or {},
        manifests=manifests or {}, readme_text="", commit_count=0, last_commit_at=None,
    )


def test_full_stack_inferred_from_cooccurrence():
    repo = _repo(manifests={
        "requirements.txt": "flask==2.0",
        "package.json": '{"dependencies": {"react": "^18.0.0"}}',
    })
    result = match_structural("Full-Stack Development", [repo])
    assert result is not None
    assert result.status == SkillStatus.VERIFIED
    assert result.method == MatchMethod.STRUCTURAL_MATCH
    assert 0 < result.confidence < 1.0  # inference, not a literal match -> not 1.0


def test_full_stack_not_inferred_from_backend_alone():
    repo = _repo(manifests={"requirements.txt": "flask==2.0"})
    result = match_structural("Full-Stack Development", [repo])
    assert result is None


def test_mobile_dev_requires_minimum_substance():
    # Regression test: a path/extension match alone (e.g. an icons folder)
    # must not verify Mobile App Development without real Dart source.
    repo = _repo(languages={"Dart": 50}, manifests={"pubspec.yaml": "name: app"})
    result = match_structural("Mobile App Development", [repo])
    assert result is None


def test_mobile_dev_verified_with_substantial_dart_source():
    repo = _repo(languages={"Dart": 50000}, manifests={"pubspec.yaml": "name: app\ndependencies:\n  flutter:"})
    result = match_structural("Mobile App Development", [repo])
    assert result is not None
    assert result.status == SkillStatus.VERIFIED
