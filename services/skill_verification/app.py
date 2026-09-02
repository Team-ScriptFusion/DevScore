"""
HTTP wrapper around github_fetch.fetch_repos() and main.match_skills() —
the skill-verification microservice (Module 1). Stateless, like cv_parser:
it never touches Supabase. Node POSTs a GitHub token or evidence here and
gets JSON back; Node does all persistence.
"""

import os

from flask import Flask, jsonify, request

from github_fetch import InvalidTokenError, fetch_repos
from main import match_skills

app = Flask(__name__)

# Shared secret with the Node backend, same pattern as cv_parser's
# PARSER_API_KEY. No key configured (local dev) degrades to open access.
API_KEY = os.environ.get("SKILL_VERIFICATION_API_KEY", "")


def _authorized(req) -> bool:
    if not API_KEY:
        return True
    return req.headers.get("X-Api-Key") == API_KEY


def _server_error(code: str):
    """
    Structured 500 for any unexpected failure. Node treats a non-2xx from
    here as skill_verification_service_unavailable (502), so the body being
    JSON rather than Flask's default HTML page keeps the failure legible in
    logs no matter what went wrong upstream.
    """
    app.logger.exception("skill-verification route failed: %s", code)
    return jsonify({"error": code}), 500


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/fetch-evidence")
def fetch_evidence_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    username = body.get("github_username")
    token = body.get("access_token")
    if not username or not token:
        return jsonify({"error": "github_username and access_token are required"}), 400

    try:
        result = fetch_repos(username, token)
    except InvalidTokenError:
        return jsonify({"error": "invalid_token"}), 401
    except Exception:  # noqa: BLE001 — see _server_error
        return _server_error("fetch_evidence_failed")
    return jsonify(result)


@app.post("/match-skills")
def match_skills_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    claimed_skills = body.get("claimed_skills") or []
    repos = body.get("repos") or []
    try:
        return jsonify(match_skills(claimed_skills, repos))
    except Exception:  # noqa: BLE001 — see _server_error
        return _server_error("match_skills_failed")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5002)))
