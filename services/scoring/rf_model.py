"""
Trained Random Forest readiness-score predictor.

This is a REAL trained model (unlike weight_fitting.py's synthetic-data
nnls pass) — a scikit-learn RandomForestRegressor fit in
`DevScore_ML_Project_2.ipynb` on 97 real candidates, using counts already
produced by `semantic_engine`'s live scoring pipeline (see
`semantic_engine/engine/models.py::ReadinessReport.to_dict()` — the
`counts` block). It predicts the same 0-100 job-readiness score the
formula-based engine already computes, from a 5-number summary of that
engine's own output.

IMPORTANT CAVEATS, carried forward verbatim from the training notebook —
do not drop these when this model's output is surfaced or cited:
1. The 97 training labels are themselves the AI-mining pipeline's own
   scores (an LLM-assisted engine mining live GitHub profiles), not
   certified production output and not genuine human industry-expert
   judgment. This model learns to reproduce that engine, not ground truth.
2. 97 rows is a very small dataset. Treat predictions as
   illustrative/exploratory, not a defensible standalone result.
3. Several underlying CVs were generated from public GitHub profiles
   rather than collected as consenting candidate submissions.

Given (1), this model's prediction is a SECONDARY, comparison-only signal
against the primary rule-based `readiness_reports.score` — never a
replacement for it in this pass.
"""

import os
import threading

import joblib

FEATURE_ORDER = ["claimed_skills", "verified", "weakly_verified", "unverified", "verify_ratio"]

_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "random_forest_model.joblib")

_model = None
_model_lock = threading.Lock()


def _load_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = joblib.load(_MODEL_PATH)
    return _model


def predict_readiness(features: dict) -> float:
    """
    `features` must have all of FEATURE_ORDER's keys (counts from a
    ReadinessReport, plus the derived verify_ratio). Returns a 0-100
    predicted score, clipped to that range (the trained forest can
    slightly over/undershoot on inputs unlike anything in its 97-row
    training set).
    """
    model = _load_model()
    row = [[features[key] for key in FEATURE_ORDER]]
    prediction = float(model.predict(row)[0])
    return round(max(0.0, min(100.0, prediction)), 2)


def build_features(counts: dict) -> dict:
    """
    Derives the model's 5 features from a ReadinessReport's `counts` block
    (`{"claimed": int, "verified": int, "weakly_verified": int, "unverified": int}`
    — see semantic_engine/engine/models.py). `verify_ratio` matches the
    training notebook's own definition: verified / claimed_skills, 0 when
    there are no claimed skills at all.
    """
    claimed = counts.get("claimed", 0)
    verified = counts.get("verified", 0)
    weakly_verified = counts.get("weakly_verified", 0)
    unverified = counts.get("unverified", 0)
    verify_ratio = round(verified / claimed, 3) if claimed else 0.0
    return {
        "claimed_skills": claimed,
        "verified": verified,
        "weakly_verified": weakly_verified,
        "unverified": unverified,
        "verify_ratio": verify_ratio,
    }
