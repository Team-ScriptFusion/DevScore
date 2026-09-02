"""
HTTP wrapper around main.run_analysis() — the code-analysis microservice
(Module 2). Stateless, like cv_parser and skill_verification: it never
touches Supabase. Node POSTs a GitHub token + repo name list here and
gets per-repo metrics + a summary back; Node does all persistence.
"""

import os

from flask import Flask, jsonify, request

from main import run_analysis
from repo_fetch import InvalidTokenError

app = Flask(__name__)

# Shared secret with the Node backend, same pattern as cv_parser/skill_verification.
# No key configured (local dev) degrades to open access.
API_KEY = os.environ.get("CODE_ANALYSIS_API_KEY", "")


def _authorized(req) -> bool:
    if not API_KEY:
        return True
    return req.headers.get("X-Api-Key") == API_KEY


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/analyze-repos")
def analyze_repos_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    username = body.get("github_username")
    token = body.get("access_token")
    repo_names = body.get("repo_names") or []
    if not username or not token:
        return jsonify({"error": "github_username and access_token are required"}), 400

    try:
        result = run_analysis(username, repo_names, token)
    except InvalidTokenError:
        return jsonify({"error": "invalid_token"}), 401
    except Exception as e:
        # A single unparseable file or one bad repo is already handled
        # inside main.py/static_analysis.py — reaching here means something
        # truly unexpected happened. Return structured JSON, never Flask's
        # default HTML error page (lesson carried over from Module 1's
        # final review, which found exactly this gap).
        return jsonify({"error": "analysis_failed", "detail": str(e)}), 500

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5003)))
