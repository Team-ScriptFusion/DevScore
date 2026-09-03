"""
Orchestration entrypoint (Section 3.1's `main.py`). Wires Tier 0 -> 1 -> 2 -> 3
in order, per skill, per (optionally bound) project, and returns results
matching Section 9's API contract shape plus the `status`/`conflict` fields.

Usage:
    from main import verify_student

    result = verify_student(
        github_username="sandunMadhushan",
        github_token=TOKEN,
        claimed_skills=["Python", "React.js", "Machine Learning", "Figma"],
        cv_projects=[{"name": "MealBridgeLK", "claimed_stack": ["React.js", "Firebase", "Tailwind CSS"]}],
        known_emails=["sandunhmadhushan@gmail.com", "s22010304@ousl.lk"],
    )
"""

from __future__ import annotations

from authorship import classify_repo_authorship, infer_identities
from direct_matcher import match_direct
from github_client import GitHubEvidenceClient, fill_full_commit_history
from models import RepoEvidence, SkillVerification
from project_binder import bind_projects, detect_conflicts
from semantic_matcher import EmbeddingProvider, TfidfEmbeddingProvider, match_semantic
from structural_matcher import match_structural


def fetch_and_prepare_evidence(github_username: str, github_token: str,
                                known_emails: list[str] | None = None,
                                paginate_commits: bool = True) -> list[RepoEvidence]:
    client = GitHubEvidenceClient(github_token)
    repos = client.fetch_all_public_repos(github_username)

    if paginate_commits:
        for repo in repos:
            fill_full_commit_history(client, github_username, repo)

    identities = infer_identities(repos, github_username, known_emails)
    for repo in repos:
        classify_repo_authorship(repo, identities)

    return repos


def verify_student(github_username: str, github_token: str,
                    claimed_skills: list[str],
                    cv_projects: list[dict] | None = None,
                    known_emails: list[str] | None = None,
                    embedding_provider: EmbeddingProvider | None = None,
                    repos: list[RepoEvidence] | None = None) -> dict:
    """Full pipeline for one student. `repos` can be pre-fetched (e.g. by a
    batch runner reusing evidence across calls) to avoid refetching."""
    if repos is None:
        repos = fetch_and_prepare_evidence(github_username, github_token, known_emails)

    provider = embedding_provider or TfidfEmbeddingProvider()
    cv_projects = cv_projects or []

    bindings = bind_projects(cv_projects, repos)
    binding_by_project = {b.cv_project_name: b for b in bindings}

    conflicts = []
    for binding in bindings:
        if not binding.repo_name:
            continue
        repo = next((r for r in repos if r.repo_name == binding.repo_name), None)
        if repo:
            conflict = detect_conflicts(binding, repo)
            if conflict:
                conflicts.append(conflict)

    # Build a lookup: which project (if any) claims each skill, so Tier 1/2
    # can be scoped to that project's bound repo (Section 5.4's "verify per
    # project, not just globally" — strictly stronger evidence).
    skill_to_project: dict[str, str] = {}
    for project in cv_projects:
        for skill in project.get("claimed_stack", []):
            skill_to_project.setdefault(skill, project["name"])

    results: list[SkillVerification] = []
    for skill in claimed_skills:
        project_name = skill_to_project.get(skill)
        scope_repo = None
        if project_name and binding_by_project.get(project_name):
            scope_repo = binding_by_project[project_name].repo_name

        verification = (
            match_direct(skill, repos, scope_repo_name=scope_repo)
            or match_structural(skill, repos, scope_repo_name=scope_repo)
            or match_semantic(skill, repos, provider, scope_repo_name=scope_repo)
        )
        if project_name:
            verification.project_binding = project_name
        results.append(verification)

    verified = sum(1 for r in results if r.status.value == "verified")
    unverified = sum(1 for r in results if r.status.value == "unverified")
    not_verifiable = sum(1 for r in results if r.status.value == "not_verifiable")

    return {
        "status": "completed",
        "github_username": github_username,
        "repos_analyzed": len(repos),
        "skills_verified": verified,
        "skills_unverified": unverified,
        "skills_not_verifiable": not_verifiable,
        "conflicts": conflicts,
        "project_bindings": [
            {"cv_project": b.cv_project_name, "bound_repo": b.repo_name, "score": b.binding_score}
            for b in bindings
        ],
        "results": [r.to_api_dict() for r in results],
    }
