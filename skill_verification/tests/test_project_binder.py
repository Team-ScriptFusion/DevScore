from models import RepoEvidence
from project_binder import bind_projects, detect_conflicts


def _repo(name, languages=None, manifests=None):
    return RepoEvidence(
        repo_name=name, is_fork=False, description="", languages=languages or {},
        manifests=manifests or {}, readme_text="", commit_count=0, last_commit_at=None,
    )


def test_fuzzy_binding_finds_close_name():
    repos = [_repo("mealbridge"), _repo("task-manager")]
    projects = [{"name": "MealBridgeLK", "claimed_stack": ["React.js"]}]
    bindings = bind_projects(projects, repos)
    assert bindings[0].repo_name == "mealbridge"
    assert bindings[0].binding_score >= 0.55


def test_no_binding_below_threshold():
    repos = [_repo("task-manager")]
    projects = [{"name": "AI Resume Analyzer", "claimed_stack": ["Python"]}]
    bindings = bind_projects(projects, repos)
    assert bindings[0].repo_name is None


def test_conflict_detected_when_stack_wholly_absent():
    # This is the real-run finding (Section 5.2): CV claims React+Tailwind
    # for a project bound to a repo that is actually Flutter/Dart.
    repo = _repo("mealbridge", languages={"Dart": 90000}, manifests={"pubspec.yaml": "firebase_core:"})
    binding = bind_projects(
        [{"name": "MealBridgeLK", "claimed_stack": ["React.js", "Tailwind CSS", "Vite"]}], [repo],
    )[0]
    conflict = detect_conflicts(binding, repo)
    assert conflict is not None
    assert "mealbridge" in conflict


def test_no_conflict_when_stack_present():
    repo = _repo("task-manager", languages={"TypeScript": 90000},
                 manifests={"package.json": '{"dependencies": {"react": "1"}}'})
    binding = bind_projects([{"name": "task-manager", "claimed_stack": ["TypeScript", "React.js"]}], [repo])[0]
    conflict = detect_conflicts(binding, repo)
    assert conflict is None
