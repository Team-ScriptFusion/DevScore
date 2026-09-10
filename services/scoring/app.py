"""
HTTP wrapper around main.py's orchestration functions — the scoring
microservice (Module 3, synthetic-data pass — see design spec §2).
Stateless, like the other three services: it never touches Supabase. Node
assembles rows from real skill_verification/code_analysis_summary data
(joined against expert_scores, synthetic in this pass) and POSTs them
here; Node does all persistence.
"""

import os

from flask import Flask, jsonify, request

import main
import rf_model

app = Flask(__name__)

# Shared secret with the Node backend, same pattern as the other three
# services. No key configured (local dev) degrades to open access.
API_KEY = os.environ.get("SCORING_API_KEY", "")


def _authorized(req) -> bool:
    if not API_KEY:
        return True
    return req.headers.get("X-Api-Key") == API_KEY


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/build-vi")
def build_vi_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    if "skill_verification_rows" not in body or "range_hint" not in body:
        return jsonify({"error": "skill_verification_rows and range_hint are required"}), 400

    try:
        result = main.run_build_vi(
            body["skill_verification_rows"], body.get("code_analysis_summary"), body["range_hint"]
        )
    except Exception as e:
        return jsonify({"error": "build_vi_failed", "detail": str(e)}), 500
    return jsonify(result)


@app.post("/assign-split")
def assign_split_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    user_ids = body.get("user_ids") or []
    train_fraction = body.get("train_fraction")
    seed = body.get("seed")
    if not user_ids or train_fraction is None or seed is None:
        return jsonify({"error": "user_ids, train_fraction and seed are required"}), 400

    try:
        assignments = main.run_assign_split(user_ids, train_fraction, seed, body.get("existing") or {})
    except Exception as e:
        return jsonify({"error": "split_failed", "detail": str(e)}), 500
    return jsonify({"assignments": assignments})


@app.post("/fit-weights")
def fit_weights_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    training_rows = body.get("training_rows") or []
    categories = body.get("categories") or []
    weights_version = body.get("weights_version")
    if not training_rows or not categories or not weights_version:
        return jsonify({"error": "training_rows, categories and weights_version are required"}), 400

    try:
        result = main.run_fit(training_rows, categories, weights_version)
    except Exception as e:
        return jsonify({"error": "fit_failed", "detail": str(e)}), 500
    return jsonify(result)


@app.post("/compute-wvr")
def compute_wvr_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    weights = body.get("weights")
    vi_by_category = body.get("vi_by_category")
    code_quality_vi = body.get("code_quality_vi")
    if weights is None or vi_by_category is None or code_quality_vi is None:
        return jsonify({"error": "weights, vi_by_category and code_quality_vi are required"}), 400

    try:
        wvr_score = main.run_wvr(weights, vi_by_category, code_quality_vi)
    except Exception as e:
        return jsonify({"error": "compute_failed", "detail": str(e)}), 500
    return jsonify({"wvr_score": wvr_score})


@app.post("/validate")
def validate_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    test_rows = body.get("test_rows") or []
    weights = body.get("weights") or []
    if not test_rows or not weights:
        return jsonify({"error": "test_rows and weights are required"}), 400

    try:
        result = main.run_validate(test_rows, weights, body.get("expert_pairs"))
    except Exception as e:
        return jsonify({"error": "validation_failed", "detail": str(e)}), 500
    return jsonify(result)


@app.post("/predict-trained")
def predict_trained_route():
    """
    Predicts a readiness score with the trained RandomForestRegressor
    (rf_model.py) from a ReadinessReport's `counts` block — a real, already
    real-data-trained model, distinct from /fit-weights' synthetic-data
    nnls pass. Comparison-only signal; see rf_model.py's caveats.
    """
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    counts = body.get("counts")
    if counts is None:
        return jsonify({"error": "counts is required"}), 400

    try:
        features = rf_model.build_features(counts)
        predicted_score = rf_model.predict_readiness(features)
    except Exception as e:
        return jsonify({"error": "predict_failed", "detail": str(e)}), 500
    return jsonify({"predicted_score": predicted_score, "features": features, "model": "random_forest_v1"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5004)))
