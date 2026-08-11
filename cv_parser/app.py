"""
HTTP wrapper around cv_parser.parse_resume() (FR 28-32 — skill
extraction module). Deployed as its own service so the Node backend
never needs a Python runtime — it just POSTs a PDF here and gets
categorized skills back.
"""

import os
import tempfile

from flask import Flask, jsonify, request

from cv_parser import parse_resume

app = Flask(__name__)

# Shared secret so this isn't an open PDF-processing endpoint for the
# whole internet. The Node backend sends it as a header on every call.
PARSER_API_KEY = os.environ.get("PARSER_API_KEY", "")


def _authorized(req) -> bool:
    if not PARSER_API_KEY:
        # No key configured (e.g. local dev) — allow, matching how the
        # rest of this app degrades to "unconfigured" rather than crashing.
        return True
    return req.headers.get("X-Api-Key") == PARSER_API_KEY


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/parse")
def parse():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    file = request.files.get("resume")
    if file is None:
        return jsonify({"error": "no file provided (expected multipart field 'resume')"}), 400

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        result = parse_resume(tmp_path)
        return jsonify(result)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)))
