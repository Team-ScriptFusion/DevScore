"""
HTTP service wrapping the scoring engine.

Deliberately mirrors the shape of `cv_parser/app.py` in the main repository
(Flask, `X-Api-Key` shared secret, degrade-to-open when unconfigured for
local dev) so the Node backend integrates with one more base URL and no new
patterns. Deployed as its own process for the same reason cv_parser is: the
Express server never needs a Python runtime.

Endpoints
    GET  /health              liveness + whether a GitHub token is present
    POST /score               multipart: resume=<pdf>, github=<handle?>
    POST /score-github        json:      {"github": "...", "skills": [...]}
    POST /parse               multipart: resume=<pdf>  — resume side only

Scoring one candidate takes tens of seconds and up to ~100 GitHub calls, so
it is well past what should sit inside a synchronous request in production.
The right shape is a job queue: POST returns 202 with an id, a worker runs
the pipeline, the dashboard polls. That is Implementation 03 work; this
service is the reference implementation the queue will call, and the
NFR budget (15–20 s to render a score) is only reachable with a warm cache.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import __version__  # noqa: E402
from engine.github.client import GitHubClient, GitHubError  # noqa: E402
from engine.github.miner import mine_profile  # noqa: E402
from engine.matching.semantic import match_skills  # noqa: E402
from engine.models import ClaimedSkill, GithubProfile, ResumeProfile  # noqa: E402
from engine.pipeline import score_resume  # noqa: E402
from engine.report.html import render_report  # noqa: E402
from engine.resume.parser import parse_resume  # noqa: E402
from engine.scoring.engine import score_candidate  # noqa: E402
from engine import ontology  # noqa: E402

app = Flask(__name__)

API_KEY = os.environ.get("ENGINE_API_KEY", "")
CACHE_DIR = os.environ.get("ENGINE_CACHE_DIR", ".cache/github")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "10"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def _authorized() -> bool:
    if not API_KEY:
        return True  # unconfigured (local dev) — matches cv_parser's behaviour
    return request.headers.get("X-Api-Key") == API_KEY


def _client() -> GitHubClient:
    return GitHubClient(cache_dir=CACHE_DIR)


def _save_upload(field: str = "resume") -> str | None:
    file = request.files.get(field)
    if file is None:
        return None
    if not (file.filename or "").lower().endswith(".pdf"):
        return None
    handle, path = tempfile.mkstemp(suffix=".pdf")
    os.close(handle)
    file.save(path)
    return path


@app.get("/health")
def health():
    client = GitHubClient(cache_dir=CACHE_DIR)
    return jsonify({
        "status": "ok",
        "engine_version": __version__,
        "github_token_configured": bool(client.token),
        "ontology_skills": len(ontology.SKILLS),
        "verifiable_skills": len(ontology.verifiable_skills()),
    })


@app.post("/parse")
def parse():
    """Resume side only. No GitHub calls, so it is fast and free."""
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401

    path = _save_upload()
    if path is None:
        return jsonify({"error": "expected a PDF in multipart field 'resume'"}), 400
    try:
        return jsonify(parse_resume(path).to_dict())
    finally:
        _cleanup(path)


@app.post("/score")
def score():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401

    path = _save_upload()
    if path is None:
        return jsonify({"error": "expected a PDF in multipart field 'resume'"}), 400

    github = (request.form.get("github") or "").strip() or None
    want_html = request.form.get("format", "").lower() == "html"
    client = _client()

    try:
        report = score_resume(
            path,
            github,
            client=client,
            candidate_name=request.form.get("name") or None,
            max_repos_deep=int(request.form.get("deep_repos", 10)),
            files_per_repo=int(request.form.get("files_per_repo", 8)),
        )
    except GitHubError as exc:
        # The engine already degrades gracefully for most GitHub problems;
        # anything reaching here is a hard failure worth a 502 rather than a
        # silently zeroed score.
        return jsonify({"error": "github_unavailable", "detail": str(exc)}), 502
    finally:
        _cleanup(path)

    if want_html:
        return render_report(report), 200, {"Content-Type": "text/html; charset=utf-8"}

    payload = report.to_dict()
    payload["_meta"] = {
        "github_api_calls": client.calls,
        "cache_hits": client.cache_hits,
        "rate_limit_remaining": client.rate_remaining,
    }
    return jsonify(payload)


@app.post("/score-github")
def score_github():
    """
    Score an already-extracted skill list against a GitHub profile.

    This is the endpoint the Node backend should actually use in production:
    Implementation 01 already stores extracted skills in `resume_skills`, so
    re-uploading and re-parsing the PDF on every recruiter-triggered scoring
    run would be wasted work.
    """
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    username = (body.get("github") or "").strip()
    skill_names = body.get("skills") or []
    if not username:
        return jsonify({"error": "'github' is required"}), 400
    if not isinstance(skill_names, list):
        return jsonify({"error": "'skills' must be an array of skill names"}), 400

    claimed: list[ClaimedSkill] = []
    for raw in skill_names:
        name = str(raw).strip()
        canonical = ontology.ALIAS_INDEX.get(name.lower())
        skill = ontology.get(canonical) if canonical else None
        if skill:
            claimed.append(ClaimedSkill(
                name=skill.name, category=skill.category, weight=skill.weight,
                verifiable=skill.verifiable, recognised=True, sources=["api"],
                raw_terms=[name],
            ))
        else:
            claimed.append(ClaimedSkill(
                name=name, category="uncategorized", weight=0.0, verifiable=False,
                recognised=False, sources=["api"], raw_terms=[name],
            ))

    client = _client()
    resume = ResumeProfile(
        file_name=body.get("resume_name") or "(skills supplied directly)",
        status="success", claimed=claimed, github_username=username,
    )
    try:
        github = mine_profile(
            username,
            [c.name for c in claimed if c.recognised and c.verifiable],
            client,
            max_repos_deep=int(body.get("deep_repos", 10)),
            files_per_repo=int(body.get("files_per_repo", 8)),
        )
    except GitHubError as exc:
        github = GithubProfile(username=username, found=False, error=str(exc))

    verdicts = match_skills(claimed, github)
    report = score_candidate(body.get("name") or username, resume, github, verdicts)
    payload = report.to_dict()
    payload["_meta"] = {
        "github_api_calls": client.calls,
        "cache_hits": client.cache_hits,
        "rate_limit_remaining": client.rate_remaining,
    }
    return jsonify(payload)


@app.get("/ontology")
def get_ontology():
    """
    The skill catalogue with its derived weights — lets the dashboard show a
    recruiter why one claim moves the score more than another, and lets a
    reviewer audit every W_i without reading Python.
    """
    return jsonify({
        "count": len(ontology.SKILLS),
        "skills": [
            {
                "name": s.name, "category": s.category, "weight": s.weight,
                "depth": s.depth, "scarcity": s.scarcity, "verifiable": s.verifiable,
                "evidence_languages": sorted(ontology.evidence_languages(s)),
                "channels": {
                    "languages": len(s.languages), "dependencies": len(s.deps),
                    "imports": len(s.imports), "markers": len(s.markers),
                    "paths": len(s.paths),
                },
            }
            for s in sorted(ontology.SKILLS.values(), key=lambda s: (-s.weight, s.name))
        ],
    })


def _cleanup(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"file exceeds {MAX_UPLOAD_MB} MB"}), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5002)))
