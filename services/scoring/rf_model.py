"""
Trained readiness-score predictor — DevScore ML Project 3.

Supersedes Project 2's single untuned RandomForestRegressor. Project 3
(`DevScore_ML_Project_3.ipynb`) diagnosed that Project 2's RF was
overfitting, tuned it (`RandomizedSearchCV`, 5-fold CV), and ran a fair
5-fold CV comparison across every candidate model on the same 97-candidate
dataset (`data/devscore_ml_training_data.csv`) — sourced, as before, from
`semantic_engine`'s real live scoring pipeline
(`semantic_engine/engine/models.py::ReadinessReport.to_dict()`'s `counts`
block), not from the abandoned skill_verification/code_analysis modules.

Per that comparison, an ensemble (0.5 * LinearRegression + 0.5 * tuned
RandomForest) had the best raw numbers (lowest MAE/RMSE, highest Spearman
rho). This module still serves **LinearRegression as the primary
prediction** — the project's own conclusion was that the ensemble's edge
over plain Linear Regression is small (~0.4 MAE) and not worth the loss of
explainability/serving simplicity for production use; the ensemble is
computed and returned alongside as a reported robustness-check number, not
the headline. See DevScore_ML_Project_3.ipynb Section 8 for the full
reasoning.

IMPORTANT CAVEATS, carried forward verbatim from both training notebooks —
do not drop these when this model's output is surfaced or cited:
1. The 97 training labels are themselves the AI-mining pipeline's own
   scores (an LLM-assisted engine mining live GitHub profiles), not
   certified production output and not genuine human industry-expert
   judgment. Every model here learns to reproduce that engine, not ground
   truth.
2. 97 rows is a very small dataset. Treat predictions as
   illustrative/exploratory, not a defensible standalone result.
3. Several underlying CVs were generated from public GitHub profiles
   rather than collected as consenting candidate submissions.
4. Project 3's own Section 8: these five features already explain
   R^2 ~ 0.98-0.99 of the label even in Project 2's untouched baseline, so
   most of the "improvement" fought over here is a few MAE points against
   the AI-mined proxy label, not a qualitative jump in real-world validity.

Given (1), every prediction from this module is a SECONDARY,
comparison-only signal against the primary rule-based
`readiness_reports.score` — never a replacement for it in this pass.
"""

import os
import threading

import joblib

FEATURE_ORDER = ["claimed_skills", "verified", "weakly_verified", "unverified", "verify_ratio"]

_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
_LINEAR_MODEL_PATH = os.path.join(_MODELS_DIR, "linear_regression_model.joblib")
_RF_TUNED_MODEL_PATH = os.path.join(_MODELS_DIR, "random_forest_tuned_model.joblib")

_linear_model = None
_rf_model = None
_model_lock = threading.Lock()


def _load_models():
    global _linear_model, _rf_model
    if _linear_model is None or _rf_model is None:
        with _model_lock:
            if _linear_model is None:
                _linear_model = joblib.load(_LINEAR_MODEL_PATH)
            if _rf_model is None:
                _rf_model = joblib.load(_RF_TUNED_MODEL_PATH)
    return _linear_model, _rf_model


def _clip(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def predict_readiness(features: dict) -> dict:
    """
    `features` must have all of FEATURE_ORDER's keys (counts from a
    ReadinessReport, plus the derived verify_ratio). Returns
    `{"linear_regression": float, "random_forest_tuned": float, "ensemble": float}`,
    each a 0-100 score clipped to that range. `linear_regression` is the
    primary/production number; the other two are reported comparison
    signals (see module docstring).
    """
    linear_model, rf_model = _load_models()
    row = [[features[key] for key in FEATURE_ORDER]]

    linear_score = float(linear_model.predict(row)[0])
    rf_score = float(rf_model.predict(row)[0])
    ensemble_score = 0.5 * linear_score + 0.5 * rf_score

    return {
        "linear_regression": _clip(linear_score),
        "random_forest_tuned": _clip(rf_score),
        "ensemble": _clip(ensemble_score),
    }


def build_features(counts: dict) -> dict:
    """
    Derives the models' 5 features from a ReadinessReport's `counts` block
    (`{"claimed": int, "verified": int, "weakly_verified": int, "unverified": int}`
    — see semantic_engine/engine/models.py). `verify_ratio` matches the
    training notebooks' own definition: verified / claimed_skills, 0 when
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
