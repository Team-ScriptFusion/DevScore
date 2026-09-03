"""
Tier 0 — bind each CV-claimed project to a specific repo, BEFORE checking
any skill. This tier does not exist in the original spec; it's the module's
own contribution, added after the real run found a genuine CV/repo conflict
(MealBridgeLK claimed React+Tailwind, the bound repo was 90% Flutter/Dart)
that a flat, global skill list would have missed entirely.

Binding is fuzzy on purpose: a student writes "MealBridgeLK" on a resume and
names the repo "mealbridge" — exact string equality would silently fail
here, defeating the point.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from models import ProjectBinding, RepoEvidence

# Below this score we don't trust the binding — better to fall through to
# global (unscoped) matching than to bind a project to the wrong repo and
# report a false conflict.
MIN_BINDING_SCORE = 0.55


def bind_projects(cv_projects: list[dict], repos: list[RepoEvidence]) -> list[ProjectBinding]:
    """
    cv_projects: [{"name": "MealBridgeLK", "claimed_stack": ["React", "Firebase", ...]}, ...]
    Returns one ProjectBinding per CV project (repo_name=None if nothing scored above threshold).
    """
    bindings = []
    for project in cv_projects:
        name = project["name"]
        best_repo, best_score = None, 0.0
        for repo in repos:
            score = _score_binding(name, repo)
            if score > best_score:
                best_repo, best_score = repo.repo_name, score
        bindings.append(ProjectBinding(
            cv_project_name=name,
            repo_name=best_repo if best_score >= MIN_BINDING_SCORE else None,
            binding_score=round(best_score, 3),
            cv_claimed_stack=project.get("claimed_stack", []),
        ))
    return bindings


def _score_binding(cv_project_name: str, repo: RepoEvidence) -> float:
    name_score = fuzz.token_sort_ratio(_clean(cv_project_name), _clean(repo.repo_name)) / 100.0
    # A partial-ratio pass catches cases like "Nexus Task Manager" -> "task-manager"
    # where the CV name has extra marketing words the repo name doesn't.
    partial = fuzz.partial_ratio(_clean(cv_project_name), _clean(repo.repo_name)) / 100.0
    return max(name_score, partial * 0.9)  # partial matches are discounted slightly


def _clean(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else " " for ch in s).strip()


def detect_conflicts(binding: ProjectBinding, repo: RepoEvidence) -> str | None:
    """Section 5.2: if a CV project's claimed stack contains a skill with NO
    trace at all in its bound repo (not even structurally), that's worth
    surfacing as a conflict for human review — not an auto-reject."""
    if not binding.repo_name or repo.repo_name != binding.repo_name:
        return None
    repo_langs = {l.lower() for l in repo.languages}
    repo_deps = set()
    for content in repo.manifests.values():
        repo_deps.add(content.lower())
    missing = []
    for claimed in binding.cv_claimed_stack:
        c = claimed.lower()
        if c in repo_langs:
            continue
        if any(c.replace(".", "").replace(" ", "") in dep.replace(" ", "") for dep in repo_deps):
            continue
        missing.append(claimed)
    # Only flag as a conflict when MOST of the claimed stack is absent —
    # one missing minor tool isn't a conflict, a wholesale mismatch is.
    if binding.cv_claimed_stack and len(missing) >= max(2, len(binding.cv_claimed_stack) * 0.6):
        return (f"CV project '{binding.cv_project_name}' claims {binding.cv_claimed_stack}, "
                f"but bound repo '{repo.repo_name}' shows none of {missing}. "
                f"Repo languages: {list(repo.languages)}.")
    return None
