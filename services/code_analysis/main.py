"""Orchestrates Phase 1 (fetch) -> Phase 3 (exclude) -> Phase 2 (analyze
+ aggregate) per repo, per module spec section 4."""

import aggregation
import exclusion_rules
import repo_fetch
import static_analysis


def _empty_metrics() -> dict:
    return {
        "language": None,
        "avg_cyclomatic_complexity": None,
        "total_functions": None,
        "total_lines": None,
        "max_nesting_depth": None,
    }


def analyze_one_repo(username: str, repo_name: str, access_token: str) -> dict:
    """Runs the full per-repo pipeline: metadata -> fork check -> tarball
    -> size check -> extract/filter -> empty check -> analyze -> tutorial
    check. Returns one result dict matching the /analyze-repos response's
    per-repo shape."""
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
    to a per-student summary. Returns {"repos": [...], "summary": {...}}."""
    results = [analyze_one_repo(username, name, access_token) for name in repo_names]
    summary = aggregation.build_summary(results)
    return {"repos": results, "summary": summary}
