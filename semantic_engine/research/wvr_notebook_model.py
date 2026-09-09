"""
wvr_notebook_model.py

The DevScore_ML_Project_2.ipynb coursework model (ICT3411/COM3405), as a
plain script. This is NOT the production scorer -- that's
`engine/scoring/engine.py`, which is already implemented, tested
(tests/test_engine.py, 74/74 passing), and validated via
`tools/ablation.py`. This file exists so the notebook's methodology is
version-controlled and reviewable, not to be imported by the running
service.

WHY THIS CAN'T REPLACE engine.py
---------------------------------
This model was fit on 5 coarse, candidate-level numbers -- how many skills a
resume claims, how many of those verify/partially-verify/fail to verify in
GitHub, and the resulting ratio -- against an AI-mined proxy score (not a
real recruited-expert score; see the caveat printed below).

engine.py scores each of the ~89 skills in `engine/ontology.py`
individually, from signals this dataset does not contain at all: per-skill
evidence tier (none/ambient/declared/used/applied/mastered), AST-derived
cyclomatic-complexity banding, usage depth, recency, and code-craft quality
-- then combines those per-skill Vi values with a Wi weight
(0.55*depth + 0.45*scarcity, the scarcity half recalibrated from real
job-posting demand vs. verified supply by `tools/calibrate_weights.py`).

Refitting engine.py's actual weights the way this script fits weights would
need per-skill training data (the job-posting corpus and a verdicts.csv of
real per-skill verdicts) that isn't checked into this repo -- it's collected
separately and, where it touches real candidates, deliberately gitignored
(see `semantic_engine/.gitignore` and the ethics-clearance note in the top
level README). So this script is kept as a labelled, honest record of the
coursework exploration, not adapted to pretend it operates at engine.py's
granularity.

DATA
----
Expects a CSV with columns:
    candidate, claimed_skills, verified, weakly_verified, unverified,
    verify_ratio, job_readiness_score
This is candidate-identifying (names, sometimes GitHub handles) -- it is
NOT included in this repo. Point TRAINING_DATA_PATH at your own local copy.

METHOD
------
- Non-negative constrained linear regression (`LinearRegression(positive=True)`),
  matching the sign constraint the project's own Wi weights are defined
  under (a skill cannot subtract from readiness).
- Spearman rank correlation as the primary validation metric (rank agreement
  matters more than absolute error for a ranking-facing score).
- 5-fold cross-validated out-of-fold predictions, since a single 70/30 split
  is unstable at this sample size (n=97 in the original run).

CAVEAT (also printed at runtime, don't drop this if you edit the script)
--------------------------------------------------------------------------
`job_readiness_score` in the training CSV is an AI-mined proxy label, not a
real human industry-expert score. A high correlation here shows the
regression pipeline works, not that the model agrees with expert judgment.
Real validation is `tools/ablation.py` run against a genuine
`candidate,expert_score` CSV once the expert-scoring round is complete.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_predict, train_test_split
from scipy.stats import spearmanr

TRAINING_DATA_PATH = "devscore_ml_training_data.csv"  # not checked in; see DATA above
FEATURES = ["claimed_skills", "verified", "weakly_verified", "unverified", "verify_ratio"]
TARGET = "job_readiness_score"
RANDOM_SEED = 42


def load_training_table(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in FEATURES + [TARGET] if c not in df.columns]
    if missing:
        raise ValueError(f"Training CSV is missing expected columns: {missing}")
    return df


def fit_and_validate(df: pd.DataFrame) -> None:
    X = df[FEATURES].values
    y = df[TARGET].values

    # Held-out split, non-negative constrained regression
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.30, random_state=RANDOM_SEED
    )
    model = LinearRegression(positive=True)
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    rho, p = spearmanr(y_test, pred)

    print(f"Training rows: {len(df)}")
    print("\nHeld-out 70/30 split (non-negative constrained regression):")
    print("  MAE         :", round(mean_absolute_error(y_test, pred), 2))
    print("  RMSE        :", round(mean_squared_error(y_test, pred) ** 0.5, 2))
    print("  R^2         :", round(r2_score(y_test, pred), 3))
    print("  Spearman rho:", round(rho, 3), " (p=%.4f)" % p)
    for f, coef in zip(FEATURES, model.coef_):
        print(f"    coef[{f}] = {coef:.3f}")

    # 5-fold CV out-of-fold predictions -- a single split is unstable at this n
    kf = KFold(n_splits=5, shuffle=True, random_state=RANDOM_SEED)
    cv_pred = cross_val_predict(LinearRegression(positive=True), X, y, cv=kf)
    rho_cv, _ = spearmanr(y, cv_pred)

    print("\n5-fold CV, out-of-fold predictions:")
    print("  MAE         :", round(mean_absolute_error(y, cv_pred), 2))
    print("  RMSE        :", round(mean_squared_error(y, cv_pred) ** 0.5, 2))
    print("  Spearman rho:", round(rho_cv, 3))

    print(
        "\nCAVEAT: job_readiness_score here is an AI-mined proxy label, not a "
        "real human expert score. This validates the pipeline, not agreement "
        "with expert judgment -- see tools/ablation.py for that once real "
        "expert scores exist, and see the module docstring for why this model "
        "isn't a drop-in for engine.py's per-skill scoring."
    )


def main() -> None:
    try:
        df = load_training_table(TRAINING_DATA_PATH)
    except FileNotFoundError:
        print(
            f"No training data at {TRAINING_DATA_PATH!r}. This file is "
            "candidate-identifying and intentionally not checked into the "
            "repo -- point TRAINING_DATA_PATH at your own local copy.",
            file=sys.stderr,
        )
        sys.exit(1)
    fit_and_validate(df)


if __name__ == "__main__":
    main()
