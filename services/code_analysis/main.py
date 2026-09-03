"""Orchestrates Phase 1 (fetch) -> Phase 3 (exclude) -> Phase 2 (analyze
+ aggregate) per repo, per module spec section 4."""

import logging

import aggregation
import exclusion_rules
import repo_fetch
import static_analysis

logger = logging.getLogger(__name__)


def _empty_metrics() -> dict:
    return {
        "language": None,
        "avg_cyclomatic_complexity": None,
        "total_functions": None,
        "total_lines": None,
        "max_nesting_depth": None,
    }


def analyze_one_repo(username: str, repo_name: str, access_token: str) -> dict:
    """Runs the full per-repo pipeline and always returns one result dict
    matching the /analyze-repos response's per-repo shape.

    Any failure that is specific to this one repo (a 404/403/5xx from
    GitHub after the repo was renamed or deleted mid-run, a corrupt or
    truncated tarball, a malformed Content-Length header) is recorded as
    `excluded_reason: "fetch_failed"` instead of propagating: per spec
    section 9, a single failed repo must never fail the whole student's
    run. InvalidTokenError is the one deliberate exception — a revoked
    token is not a per-repo problem, and the route must still answer 401
    for the run as a whole."""
    try:
        return _analyze_one_repo(username, repo_name, access_token)
    except repo_fetch.InvalidTokenError:
        raise
    except Exception:  # noqa: BLE001 — deliberate per-repo containment
        logger.exception("code analysis failed for repo %s/%s", username, repo_name)
        return {
            "repo_name": repo_name, "included": False,
            "excluded_reason": "fetch_failed", **_empty_metrics(),
        }


def _analyze_one_repo(username: str, repo_name: str, access_token: str) -> dict:
    """The per-repo pipeline itself: metadata -> fork check -> tarball
    -> size check -> extract/filter -> empty check -> analyze -> tutorial
    check."""
    full_name = f"{username}/{repo_name}"

    metadata = repo_fetch.fetch_repo_metadata(full_name, access_token)
    if exclusion_rules.is_fork(metadata):
        return {"repo_name": repo_name, "included": False, "excluded_reason": "fork", **_empty_metrics()}

    try:
        tarball_bytes = repo_fetch.download_tarball(full_name, access_token)
    except repo_fetch.TarballTooLargeError:
        return {"repo_name": repo_name, "included": False, "excluded_reason": "too_large", **_empty_metrics()}

    tmp_dir, files = repo_fetch.extract_and_filter(tarball_bytes)
    try:
        metrics = static_analysis.analyze_files(files)

        if exclusion_rules.is_empty(metrics["total_lines"]):
            return {"repo_name": repo_name, "included": False, "excluded_reason": "empty", **_empty_metrics()}

        if exclusion_rules.matches_tutorial_heuristic(repo_name):
            return {
                "repo_name": repo_name, "included": False,
                "excluded_reason": "tutorial_clone_heuristic", **metrics,
            }

        return {"repo_name": repo_name, "included": True, "excluded_reason": None, **metrics}
    finally:
        repo_fetch.cleanup(tmp_dir)


def run_analysis(username: str, repo_names: list, access_token: str) -> dict:
    """Runs analyze_one_repo for every repo_names entry, then aggregates
    to a per-student summary. Returns {"repos": [...], "summary": {...}}.

    analyze_one_repo contains its own per-repo failures (returning a
    `fetch_failed` result rather than raising), so one bad repo never
    costs the student the results of the others."""
    results = [analyze_one_repo(username, name, access_token) for name in repo_names]
    summary = aggregation.build_summary(results)
    return {"repos": results, "summary": summary}
