# Scoring Model (Synthetic-Data Pass) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and test the full WVR weight-fitting/scoring pipeline (Vi-building, train/test split, non-negative weight-fitting, WVR calculation, validation stats, inter-rater agreement) end-to-end against a clearly-labeled **synthetic** expert-score dataset — no real expert data exists yet, and this pass makes no claim otherwise.

**Architecture:** A new stateless Python/Flask microservice (`services/scoring/`) does all the statistics (numpy/scipy, no Supabase access), called over HTTP from a new Node controller (`server/src`) that owns persistence, authorization (admin-only in this pass), and assembling per-student inputs from the already-real `skill_verification`/`code_analysis_summary` tables — mirroring `code_analysis`'s and `skill_verification`'s integration pattern exactly.

**Tech Stack:** Python 3 / Flask / `numpy` / `scipy` / `krippendorff` (new service, no `requests` needed — this service makes no outbound HTTP calls); Node/Express / `@supabase/supabase-js` (existing server, extended); `pytest` (Python tests); Node's built-in `node:test` (Node tests, no new dependency).

**Spec:** `docs/superpowers/specs/2026-09-03-scoring-model-design.md`

## Global Constraints

- The Python service is stateless — it never touches Supabase, exactly like the other three services.
- **This entire pass is synthetic-data scope.** `expert_scores` rows populated in this plan come only from the seed script in Task 12, which refuses to run without an explicit `--confirm` flag and always writes `expert_id` values prefixed `synthetic-`, so no row from this pass can be mistaken for real data.
- No `expert` user role, no expert-facing UI/API, no student- or recruiter-facing endpoint is added — every new route in this module is `requireRole('admin')` only.
- Weight-fitting uses `scipy.optimize.nnls` — never an unconstrained least-squares solve — so weights are structurally non-negative, not merely clipped after the fact.
- Code-complexity (`code_quality_vi`) is its own weighted term in the WVR sum, not a modifier on skill-level Vi.
- New tables (`expert_scores`, `train_test_split`, `skill_weights`, `wvr_scores`, `validation_results`) get RLS enabled with **zero policies** — service-role key only, identical to every existing table in `schema.sql`.
- `expert_scores.expert_id` is a plain `text` column, **not** a foreign key to `users` — experts are not DevScore accounts in this pass.
- `wvr_scores.weights_version` / `validation_results.weights_version` are plain matching `text` values, **not** foreign keys to `skill_weights` — `skill_weights` has one row per category per version, so `weights_version` isn't unique on that table and no FK to it could validate.
- Node ↔ Python auth uses a shared-secret `X-Api-Key` header; an unset key means open access (matches the other three services' local-dev degradation).
- No new Node test-runner dependency — use the built-in `node:test` module.
- This module's Node code only reads `skill_verification`/`code_analysis_summary` (via direct, self-contained queries in its own new model file) — it does not modify `SkillVerification.js`, `CodeAnalysis.js`, or any other existing file outside this module's own new files, `server/supabase/schema.sql`, `server/.env.example`, `server/src/config/env.js`, and `server/src/app.js`.

---

## Part A — Python scoring service

### Task 1: Scaffold the service + synthetic data generator

**Files:**
- Create: `services/scoring/fake_data.py`
- Create: `services/scoring/requirements.txt`
- Create: `services/scoring/requirements-dev.txt`
- Create: `services/scoring/tests/__init__.py` (empty)
- Create: `services/scoring/tests/conftest.py`
- Test: `services/scoring/tests/test_fake_data.py`

**Interfaces:**
- Produces: `fake_data.generate_fake_dataset(n_students: int, seed: int, noise_scale: float = 3.0) -> list[dict]`, each item `{"user_id": str, "vi_by_category": {category: float}, "code_quality_vi": float, "expert_score": float}`. Also exports `fake_data.TRUE_WEIGHTS` (dict, sums to 1.0 including `"code_quality"`) and `fake_data.CATEGORIES` (list of the non-code-quality keys of `TRUE_WEIGHTS`). Used by Task 4's weight-fitting tests to assert recovered coefficients approximate known values (module spec §10/§12's "known relationship" test). **Never imported by `app.py`** — dev/test-only, per design spec §4/§10.

- [ ] **Step 1: Create the service directory and dependency files**

`services/scoring/requirements.txt`:
```
flask==3.1.3
gunicorn==26.0.0
numpy==2.1.3
scipy==1.14.1
krippendorff==0.7.0
```

`services/scoring/requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.4
```

- [ ] **Step 2: Add `tests/conftest.py` so tests can import service modules regardless of cwd**

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

Also create an empty `services/scoring/tests/__init__.py`.

- [ ] **Step 3: Write the failing test**

`services/scoring/tests/test_fake_data.py`:
```python
from fake_data import CATEGORIES, TRUE_WEIGHTS, generate_fake_dataset


def test_generate_fake_dataset_returns_requested_count():
    rows = generate_fake_dataset(20, seed=1)
    assert len(rows) == 20


def test_generate_fake_dataset_is_deterministic_for_seed():
    a = generate_fake_dataset(10, seed=5)
    b = generate_fake_dataset(10, seed=5)
    assert a == b


def test_generate_fake_dataset_scores_within_bounds():
    rows = generate_fake_dataset(50, seed=2)
    for row in rows:
        assert 0.0 <= row["expert_score"] <= 100.0
        assert set(row["vi_by_category"].keys()) == set(CATEGORIES)
        assert 0.0 <= row["code_quality_vi"] <= 1.0


def test_generate_fake_dataset_unique_user_ids():
    rows = generate_fake_dataset(15, seed=3)
    ids = [r["user_id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_true_weights_sum_to_one():
    assert abs(sum(TRUE_WEIGHTS.values()) - 1.0) < 1e-9
```

- [ ] **Step 4: Install dependencies and run the test to verify it fails**

```bash
cd services/scoring
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_fake_data.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'fake_data'`

- [ ] **Step 5: Write the minimal implementation**

`services/scoring/fake_data.py`:
```python
"""
Synthetic training/validation data for this module's dev/test pass (design
spec §2/§10) — there is no real expert-score data yet. Rows are generated
from a KNOWN linear formula plus noise, so weight-fitting tests can assert
the recovered weights approximate the known coefficients. This module is
never imported by app.py's request-handling path; production /fit-weights
calls always take training_rows from the caller (Node), never generate
their own.
"""

import random

CATEGORIES = ["backend_languages", "frontend_frameworks", "testing_devops"]

# Sums to 1.0 so a near-noiseless fit's recovered weights land close to
# these values directly (see design spec §8's fitting approach).
TRUE_WEIGHTS = {
    "backend_languages": 0.40,
    "frontend_frameworks": 0.25,
    "testing_devops": 0.15,
    "code_quality": 0.20,
}


def generate_fake_dataset(n_students: int, seed: int, noise_scale: float = 3.0) -> list:
    """
    Generates `n_students` synthetic rows: random Vi values per category
    plus a random code_quality_vi, with expert_score computed from
    TRUE_WEIGHTS plus Gaussian noise (scaled in 0-100 points), clipped to
    [0, 100].
    """
    rng = random.Random(seed)
    rows = []
    for i in range(n_students):
        vi_by_category = {cat: rng.uniform(0.0, 1.0) for cat in CATEGORIES}
        code_quality_vi = rng.uniform(0.0, 1.0)

        true_score = 100 * (
            sum(TRUE_WEIGHTS[cat] * vi_by_category[cat] for cat in CATEGORIES)
            + TRUE_WEIGHTS["code_quality"] * code_quality_vi
        )
        noisy_score = max(0.0, min(100.0, true_score + rng.gauss(0, noise_scale)))

        rows.append({
            "user_id": f"fake-user-{i}",
            "vi_by_category": vi_by_category,
            "code_quality_vi": code_quality_vi,
            "expert_score": round(noisy_score, 2),
        })
    return rows
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd services/scoring
python -m pytest tests/test_fake_data.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add services/scoring/fake_data.py services/scoring/requirements.txt services/scoring/requirements-dev.txt services/scoring/tests/
git commit -m "Add scoring service scaffold and synthetic data generator"
```

---

### Task 2: Vi-building (`vi_builder.py`)

**Files:**
- Create: `services/scoring/vi_builder.py`
- Test: `services/scoring/tests/test_vi_builder.py`

**Interfaces:**
- Produces:
  - `vi_builder.build_skill_vi(verified: bool, confidence: float | None) -> float`
  - `vi_builder.build_category_vi(skill_rows: list[dict]) -> dict[str, float]` — each item `{"category": str | None, "verified": bool, "confidence": float | None}`; null category groups under `"uncategorized"`.
  - `vi_builder.build_code_quality_vi(summary: dict | None, range_hint: dict) -> float` — `summary` is `{"avg_complexity_overall": float | None, "total_loc_overall": int | None} | None`; `range_hint` is `{"complexity_min", "complexity_max", "loc_min", "loc_max"}`.
- Used by Task 7's `main.run_build_vi`.

- [ ] **Step 1: Write the failing test**

`services/scoring/tests/test_vi_builder.py`:
```python
from vi_builder import build_category_vi, build_code_quality_vi, build_skill_vi


def test_build_skill_vi_verified_uses_confidence():
    assert build_skill_vi(True, 0.82) == 0.82


def test_build_skill_vi_unverified_uses_floor_not_zero():
    # "No evidence found" isn't the same claim as "evidence contradicts the
    # claim" — a flat zero would conflate them (module spec §6 step 1).
    assert build_skill_vi(False, None) == 0.1


def test_build_category_vi_averages_within_category():
    rows = [
        {"category": "backend_languages", "verified": True, "confidence": 0.8},
        {"category": "backend_languages", "verified": True, "confidence": 0.6},
        {"category": "frontend_frameworks", "verified": False, "confidence": None},
    ]
    result = build_category_vi(rows)
    assert result == {"backend_languages": 0.7, "frontend_frameworks": 0.1}


def test_build_category_vi_null_category_becomes_uncategorized():
    rows = [{"category": None, "verified": True, "confidence": 0.5}]
    assert build_category_vi(rows) == {"uncategorized": 0.5}


def test_build_category_vi_empty_input():
    assert build_category_vi([]) == {}


def test_build_code_quality_vi_normalizes_within_range():
    summary = {"avg_complexity_overall": 5.0, "total_loc_overall": 500}
    range_hint = {"complexity_min": 1.0, "complexity_max": 9.0, "loc_min": 0, "loc_max": 1000}
    assert build_code_quality_vi(summary, range_hint) == 0.5


def test_build_code_quality_vi_none_summary_returns_zero():
    range_hint = {"complexity_min": 1.0, "complexity_max": 9.0, "loc_min": 0, "loc_max": 1000}
    assert build_code_quality_vi(None, range_hint) == 0.0


def test_build_code_quality_vi_degenerate_range_returns_zero():
    summary = {"avg_complexity_overall": 5.0, "total_loc_overall": 0}
    range_hint = {"complexity_min": 5.0, "complexity_max": 5.0, "loc_min": 0, "loc_max": 0}
    assert build_code_quality_vi(summary, range_hint) == 0.0
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/scoring
python -m pytest tests/test_vi_builder.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'vi_builder'`

- [ ] **Step 3: Write the minimal implementation**

`services/scoring/vi_builder.py`:
```python
"""Combines Module 1 (skill_verification) and Module 2 (code_analysis_
summary) outputs into per-skill-category and code-quality Vi values
(module spec §6)."""

UNVERIFIED_FLOOR = 0.1


def build_skill_vi(verified: bool, confidence) -> float:
    """confidence if verified, else a fixed floor (not 0.0 — see module
    spec §6 step 1)."""
    if verified and confidence is not None:
        return confidence
    return UNVERIFIED_FLOOR


def build_category_vi(skill_rows: list) -> dict:
    """Groups skill_rows by category (null -> 'uncategorized') and averages
    build_skill_vi within each group, to keep the regression's input
    dimensionality small (module spec §6 step 2 / §8 step 3)."""
    totals = {}
    counts = {}
    for row in skill_rows:
        category = row["category"] or "uncategorized"
        vi = build_skill_vi(row["verified"], row.get("confidence"))
        totals[category] = totals.get(category, 0.0) + vi
        counts[category] = counts.get(category, 0) + 1
    return {category: round(totals[category] / counts[category], 4) for category in totals}


def _normalize(value, lo, hi) -> float:
    if value is None or hi == lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def build_code_quality_vi(summary, range_hint: dict) -> float:
    """Min-max normalizes avg_complexity_overall/total_loc_overall against
    the training set's own range, averaging the two into one 0-1 feature
    (module spec §6 step 2; the exact normalization is a documented,
    non-load-bearing choice, per design spec §6)."""
    if not summary:
        return 0.0
    complexity_score = _normalize(
        summary.get("avg_complexity_overall"), range_hint["complexity_min"], range_hint["complexity_max"]
    )
    loc_score = _normalize(summary.get("total_loc_overall"), range_hint["loc_min"], range_hint["loc_max"])
    return round(0.5 * complexity_score + 0.5 * loc_score, 4)
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/scoring
python -m pytest tests/test_vi_builder.py -v
```
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add services/scoring/vi_builder.py services/scoring/tests/test_vi_builder.py
git commit -m "Add Vi-building logic combining skill-verification and code-analysis signals"
```

---

### Task 3: Train/test split (`split.py`)

**Files:**
- Create: `services/scoring/split.py`
- Test: `services/scoring/tests/test_split.py`

**Interfaces:**
- Produces: `split.assign_split(user_ids: list[str], train_fraction: float, seed: int, existing: dict[str, str] | None = None) -> dict[str, str]` — values are `"train"` or `"test"`. Already-assigned ids in `existing` are carried through unchanged (idempotent — module spec §12). Used by Task 7's `main.run_assign_split`.

- [ ] **Step 1: Write the failing test**

`services/scoring/tests/test_split.py`:
```python
from split import assign_split


def test_assign_split_deterministic_for_seed():
    ids = ["a", "b", "c", "d", "e", "f"]
    first = assign_split(ids, 0.5, seed=7)
    second = assign_split(ids, 0.5, seed=7)
    assert first == second


def test_assign_split_respects_train_fraction():
    ids = [f"u{i}" for i in range(10)]
    result = assign_split(ids, 0.7, seed=3)
    train_count = sum(1 for v in result.values() if v == "train")
    assert train_count == 7
    assert set(result.keys()) == set(ids)


def test_assign_split_is_idempotent_for_already_assigned_ids():
    ids = ["a", "b", "c", "d"]
    first = assign_split(ids, 0.5, seed=1)
    second = assign_split(ids, 0.5, seed=1, existing=first)
    assert second == first


def test_assign_split_only_assigns_new_ids_not_in_existing():
    existing = {"a": "train", "b": "test"}
    result = assign_split(["a", "b", "c"], 0.5, seed=1, existing=existing)
    assert result["a"] == "train"
    assert result["b"] == "test"
    assert result["c"] in ("train", "test")


def test_assign_split_empty_ids_returns_empty():
    assert assign_split([], 0.7, seed=1) == {}
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/scoring
python -m pytest tests/test_split.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'split'`

- [ ] **Step 3: Write the minimal implementation**

`services/scoring/split.py`:
```python
"""Train/test split assignment, locked and idempotent once assigned
(module spec §7/§12)."""

import random


def assign_split(user_ids: list, train_fraction: float, seed: int, existing: dict = None) -> dict:
    """
    Returns a {user_id: "train"|"test"} mapping. Ids already present in
    `existing` keep their assignment unchanged; only new ids are shuffled
    (deterministically, via `seed`) and split by `train_fraction`.
    """
    existing = dict(existing or {})
    new_ids = [uid for uid in user_ids if uid not in existing]

    shuffled = new_ids[:]
    random.Random(seed).shuffle(shuffled)
    cutoff = round(len(shuffled) * train_fraction)

    result = dict(existing)
    for uid in shuffled[:cutoff]:
        result[uid] = "train"
    for uid in shuffled[cutoff:]:
        result[uid] = "test"
    return result
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/scoring
python -m pytest tests/test_split.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add services/scoring/split.py services/scoring/tests/test_split.py
git commit -m "Add idempotent train/test split assignment"
```

---

### Task 4: WVR calculator (`wvr_calculator.py`)

**Files:**
- Create: `services/scoring/wvr_calculator.py`
- Test: `services/scoring/tests/test_wvr_calculator.py`

**Interfaces:**
- Produces: `wvr_calculator.compute_wvr(weights: dict[str, float], vi_by_category: dict[str, float], code_quality_vi: float) -> float`. `weights` keys are category names plus `"code_quality"`. Implements `WVR = Σ(Wi·Vi) / ΣWi × 100` literally (module spec's own formula). Used by Task 5's weight-fitting cross-validation, Task 6's validation, and Task 7's orchestration. Built before Task 5 because Task 5's cross-validation needs it.

- [ ] **Step 1: Write the failing test**

`services/scoring/tests/test_wvr_calculator.py`:
```python
from wvr_calculator import compute_wvr


def test_compute_wvr_basic_formula():
    weights = {"backend_languages": 0.4, "code_quality": 0.2}
    vi = {"backend_languages": 1.0}
    # (0.4*1.0 + 0.2*0.5) / 0.6 * 100 = 0.5/0.6*100 = 83.33
    assert compute_wvr(weights, vi, code_quality_vi=0.5) == 83.33


def test_compute_wvr_missing_category_in_vi_treated_as_zero():
    weights = {"backend_languages": 0.5, "frontend_frameworks": 0.5}
    vi = {"backend_languages": 1.0}
    assert compute_wvr(weights, vi, code_quality_vi=0.0) == 50.0


def test_compute_wvr_zero_total_weight_returns_zero():
    assert compute_wvr({}, {}, 0.0) == 0.0


def test_compute_wvr_full_marks_gives_one_hundred():
    weights = {"backend_languages": 1.0}
    assert compute_wvr(weights, {"backend_languages": 1.0}, code_quality_vi=0.0) == 100.0
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/scoring
python -m pytest tests/test_wvr_calculator.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'wvr_calculator'`

- [ ] **Step 3: Write the minimal implementation**

`services/scoring/wvr_calculator.py`:
```python
"""WVR formula application against an already-frozen weight set (module
spec's WVR = Sigma(Wi*Vi) / SigmaWi * 100)."""


def compute_wvr(weights: dict, vi_by_category: dict, code_quality_vi: float) -> float:
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return 0.0

    weighted_sum = sum(
        weight * vi_by_category.get(category, 0.0)
        for category, weight in weights.items()
        if category != "code_quality"
    )
    weighted_sum += weights.get("code_quality", 0.0) * code_quality_vi

    return round(100 * weighted_sum / total_weight, 2)
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/scoring
python -m pytest tests/test_wvr_calculator.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add services/scoring/wvr_calculator.py services/scoring/tests/test_wvr_calculator.py
git commit -m "Add WVR formula calculator"
```

---

### Task 5: Weight-fitting (`weight_fitting.py`)

**Files:**
- Create: `services/scoring/weight_fitting.py`
- Test: `services/scoring/tests/test_weight_fitting.py`

**Interfaces:**
- Consumes: `wvr_calculator.compute_wvr` (Task 4)
- Produces:
  - `weight_fitting.fit_weights(rows: list[dict], categories: list[str]) -> dict[str, float]` — each `rows` item has `vi_by_category`, `code_quality_vi`, `expert_score` (0-100). Returns one weight per category plus `"code_quality"`, all non-negative (via `scipy.optimize.nnls`).
  - `weight_fitting.cross_validate(rows: list[dict], categories: list[str], k: int = 5, seed: int = 0) -> float | None` — average R² across k folds, or `None` if there's not enough data for even one fold.
- Used by Task 7's `main.run_fit`.

- [ ] **Step 1: Write the failing test**

`services/scoring/tests/test_weight_fitting.py`:
```python
import numpy as np

from fake_data import CATEGORIES, TRUE_WEIGHTS, generate_fake_dataset
from weight_fitting import cross_validate, fit_weights


def test_fit_weights_recovers_known_coefficients_within_tolerance():
    rows = generate_fake_dataset(300, seed=10, noise_scale=1.0)
    weights = fit_weights(rows, CATEGORIES)
    for key, true_value in TRUE_WEIGHTS.items():
        assert abs(weights[key] - true_value) < 0.08


def test_fit_weights_all_non_negative():
    rows = generate_fake_dataset(100, seed=11)
    weights = fit_weights(rows, CATEGORIES)
    assert all(w >= 0 for w in weights.values())


def test_fit_weights_clips_negative_correlation_to_zero_not_negative():
    # A category that's negatively correlated with expert_score: an
    # unconstrained least-squares fit would assign it a negative
    # coefficient. nnls must not (module spec §8 step 5).
    rows = [
        {"vi_by_category": {"cat_a": 0.1}, "code_quality_vi": 0.9, "expert_score": 90.0},
        {"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.5, "expert_score": 50.0},
        {"vi_by_category": {"cat_a": 0.9}, "code_quality_vi": 0.1, "expert_score": 10.0},
    ]
    x = np.array([[0.1, 0.9], [0.5, 0.5], [0.9, 0.1]])
    y = np.array([0.9, 0.5, 0.1])
    unconstrained, *_ = np.linalg.lstsq(x, y, rcond=None)
    assert unconstrained[0] < 0  # sanity: confirms this case is a real trap

    weights = fit_weights(rows, ["cat_a"])
    assert weights["cat_a"] >= 0


def test_cross_validate_recovers_reasonable_fit_quality():
    rows = generate_fake_dataset(200, seed=12, noise_scale=1.5)
    score = cross_validate(rows, CATEGORIES, k=5, seed=0)
    assert score is not None
    assert score > 0.5


def test_cross_validate_returns_none_when_too_little_data():
    rows = generate_fake_dataset(2, seed=13)
    assert cross_validate(rows, CATEGORIES, k=5, seed=0) is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/scoring
python -m pytest tests/test_weight_fitting.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'weight_fitting'`

- [ ] **Step 3: Write the minimal implementation**

`services/scoring/weight_fitting.py`:
```python
"""Non-negative least-squares weight-fitting (module spec §8) — plain
linear regression, no Ridge/Lasso escalation in this pass (design spec
§3)."""

import random

import numpy as np
from scipy.optimize import nnls

from wvr_calculator import compute_wvr


def _feature_matrix(rows: list, categories: list) -> np.ndarray:
    return np.array([
        [row["vi_by_category"].get(cat, 0.0) for cat in categories] + [row["code_quality_vi"]]
        for row in rows
    ])


def fit_weights(rows: list, categories: list) -> dict:
    """
    Regresses per-category Vi + code_quality_vi against expert_score/100
    via nnls, which structurally cannot return a negative coefficient.
    """
    x = _feature_matrix(rows, categories)
    y = np.array([row["expert_score"] / 100.0 for row in rows])
    coefficients, _ = nnls(x, y)
    keys = list(categories) + ["code_quality"]
    return dict(zip(keys, (float(c) for c in coefficients)))


def cross_validate(rows: list, categories: list, k: int = 5, seed: int = 0):
    """
    K-fold cross-validation within `rows` (module spec §8 step 6) — fits on
    each fold's training rows, scores R^2 on that fold's held-out rows.
    Returns the average R^2, or None if there's too little data for even
    one usable fold.
    """
    n = len(rows)
    indices = list(range(n))
    random.Random(seed).shuffle(indices)
    folds = np.array_split(indices, k)

    r2_scores = []
    for fold in folds:
        test_idx = set(fold.tolist())
        train_rows = [rows[i] for i in range(n) if i not in test_idx]
        test_rows = [rows[i] for i in range(n) if i in test_idx]
        if not test_rows or len(train_rows) <= len(categories) + 1:
            continue

        weights = fit_weights(train_rows, categories)
        predictions = [
            compute_wvr(weights, row["vi_by_category"], row["code_quality_vi"])
            for row in test_rows
        ]
        actual = [row["expert_score"] for row in test_rows]
        mean_actual = sum(actual) / len(actual)
        ss_res = sum((a - p) ** 2 for a, p in zip(actual, predictions))
        ss_tot = sum((a - mean_actual) ** 2 for a in actual) or 1e-9
        r2_scores.append(1 - ss_res / ss_tot)

    return sum(r2_scores) / len(r2_scores) if r2_scores else None
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/scoring
python -m pytest tests/test_weight_fitting.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add services/scoring/weight_fitting.py services/scoring/tests/test_weight_fitting.py
git commit -m "Add non-negative weight-fitting with k-fold cross-validation"
```

---

### Task 6: Validation and inter-rater agreement (`validation.py`, `inter_rater.py`)

**Files:**
- Create: `services/scoring/validation.py`
- Create: `services/scoring/inter_rater.py`
- Test: `services/scoring/tests/test_validation.py`
- Test: `services/scoring/tests/test_inter_rater.py`

**Interfaces:**
- Consumes: `wvr_calculator.compute_wvr` (Task 4)
- Produces:
  - `validation.compute_validation(test_rows: list[dict], weights: dict) -> dict` returning `{"spearman_rho": float, "mae": float, "sample_size": int}` (module spec §9).
  - `inter_rater.compute_inter_rater(score_pairs: list[tuple[float, float]]) -> dict` returning `{"spearman_rho": float, "alpha": float, "sample_size": int}` (module spec §7).
- Used by Task 7's `main.run_validate`.

- [ ] **Step 1: Write the failing tests**

`services/scoring/tests/test_validation.py`:
```python
from validation import compute_validation


def test_compute_validation_perfect_agreement():
    weights = {"cat_a": 1.0}
    test_rows = [
        {"vi_by_category": {"cat_a": 0.2}, "code_quality_vi": 0.0, "expert_score": 20.0},
        {"vi_by_category": {"cat_a": 0.8}, "code_quality_vi": 0.0, "expert_score": 80.0},
        {"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.0, "expert_score": 50.0},
    ]
    result = compute_validation(test_rows, weights)
    assert result == {"spearman_rho": 1.0, "mae": 0.0, "sample_size": 3}


def test_compute_validation_measures_disagreement():
    weights = {"cat_a": 1.0}
    test_rows = [
        {"vi_by_category": {"cat_a": 0.9}, "code_quality_vi": 0.0, "expert_score": 20.0},
        {"vi_by_category": {"cat_a": 0.1}, "code_quality_vi": 0.0, "expert_score": 80.0},
    ]
    result = compute_validation(test_rows, weights)
    assert result["spearman_rho"] < 0
```

`services/scoring/tests/test_inter_rater.py`:
```python
from inter_rater import compute_inter_rater


def test_compute_inter_rater_perfect_agreement():
    pairs = [(80, 80), (60, 60), (90, 90), (40, 40)]
    result = compute_inter_rater(pairs)
    assert result == {"spearman_rho": 1.0, "alpha": 1.0, "sample_size": 4}


def test_compute_inter_rater_disagreement_scores_lower_than_agreement():
    agree = compute_inter_rater([(80, 82), (60, 58), (90, 91), (40, 42)])
    disagree = compute_inter_rater([(80, 20), (60, 95), (90, 10), (40, 88)])
    assert agree["spearman_rho"] > disagree["spearman_rho"]
    assert agree["alpha"] > disagree["alpha"]
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd services/scoring
python -m pytest tests/test_validation.py tests/test_inter_rater.py -v
```
Expected: FAIL — `ModuleNotFoundError` for both `validation` and `inter_rater`

- [ ] **Step 3: Write the minimal implementations**

`services/scoring/validation.py`:
```python
"""Test-set validation stats: predicted WVR (frozen weights) vs each
row's expert_score (module spec §9)."""

from scipy.stats import spearmanr

from wvr_calculator import compute_wvr


def compute_validation(test_rows: list, weights: dict) -> dict:
    predictions = [
        compute_wvr(weights, row["vi_by_category"], row["code_quality_vi"])
        for row in test_rows
    ]
    actual = [row["expert_score"] for row in test_rows]

    rho, _ = spearmanr(predictions, actual)
    mae = sum(abs(p - a) for p, a in zip(predictions, actual)) / len(actual)

    return {
        "spearman_rho": round(float(rho), 4),
        "mae": round(mae, 2),
        "sample_size": len(test_rows),
    }
```

`services/scoring/inter_rater.py`:
```python
"""Agreement between two experts scoring the same overlapping students
(module spec §7) — computed before investing in weight-fitting, so
'expert judgment' is confirmed to be a stable target first."""

import krippendorff
from scipy.stats import spearmanr


def compute_inter_rater(score_pairs: list) -> dict:
    scores_a = [pair[0] for pair in score_pairs]
    scores_b = [pair[1] for pair in score_pairs]

    rho, _ = spearmanr(scores_a, scores_b)
    alpha = krippendorff.alpha(reliability_data=[scores_a, scores_b], level_of_measurement="interval")

    return {
        "spearman_rho": round(float(rho), 4),
        "alpha": round(float(alpha), 4),
        "sample_size": len(score_pairs),
    }
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd services/scoring
python -m pytest tests/test_validation.py tests/test_inter_rater.py -v
```
Expected: PASS (4 tests total)

- [ ] **Step 5: Commit**

```bash
git add services/scoring/validation.py services/scoring/inter_rater.py services/scoring/tests/test_validation.py services/scoring/tests/test_inter_rater.py
git commit -m "Add test-set validation and inter-rater agreement statistics"
```

---

### Task 7: Orchestration (`main.py`)

**Files:**
- Create: `services/scoring/main.py`
- Test: `services/scoring/tests/test_main.py`

**Interfaces:**
- Consumes: `vi_builder.build_category_vi`/`build_code_quality_vi` (Task 2), `split.assign_split` (Task 3), `wvr_calculator.compute_wvr` (Task 4), `weight_fitting.fit_weights`/`cross_validate` (Task 5), `validation.compute_validation` (Task 6), `inter_rater.compute_inter_rater` (Task 6)
- Produces:
  - `main.run_build_vi(skill_rows: list[dict], summary: dict | None, range_hint: dict) -> dict` returning `{"vi_by_category": dict, "code_quality_vi": float}`.
  - `main.run_assign_split(user_ids: list[str], train_fraction: float, seed: int, existing: dict | None = None) -> dict[str, str]`.
  - `main.run_fit(training_rows: list[dict], categories: list[str], weights_version: str) -> dict` returning `{"status": "completed", "weights_version": str, "weights": [{"category": str, "weight": float}], "cv_score": float | None}`.
  - `main.run_wvr(weights_list: list[dict], vi_by_category: dict, code_quality_vi: float) -> float` — `weights_list` is the stored/returned `[{"category", "weight"}]` shape.
  - `main.run_validate(test_rows: list[dict], weights_list: list[dict], expert_pairs: list | None = None) -> dict` — includes an `"inter_rater"` key only when `expert_pairs` is given.
- Used by Task 8's Flask routes.

- [ ] **Step 1: Write the failing test**

`services/scoring/tests/test_main.py`:
```python
import main


def test_run_build_vi_combines_skill_and_code_signals():
    skill_rows = [{"category": "backend_languages", "verified": True, "confidence": 0.9}]
    summary = {"avg_complexity_overall": 5.0, "total_loc_overall": 500}
    range_hint = {"complexity_min": 1.0, "complexity_max": 9.0, "loc_min": 0, "loc_max": 1000}
    result = main.run_build_vi(skill_rows, summary, range_hint)
    assert result == {"vi_by_category": {"backend_languages": 0.9}, "code_quality_vi": 0.5}


def test_run_assign_split_delegates_to_split_module():
    result = main.run_assign_split(["a", "b", "c", "d"], 0.5, seed=1)
    assert set(result.keys()) == {"a", "b", "c", "d"}
    assert set(result.values()) <= {"train", "test"}


def test_run_fit_returns_expected_shape():
    rows = [
        {"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.5, "expert_score": 50.0},
        {"vi_by_category": {"cat_a": 1.0}, "code_quality_vi": 1.0, "expert_score": 100.0},
        {"vi_by_category": {"cat_a": 0.0}, "code_quality_vi": 0.0, "expert_score": 0.0},
    ]
    result = main.run_fit(rows, ["cat_a"], "v1_test")
    assert result["status"] == "completed"
    assert result["weights_version"] == "v1_test"
    assert {w["category"] for w in result["weights"]} == {"cat_a", "code_quality"}


def test_run_wvr_applies_stored_weight_shape():
    weights_list = [{"category": "cat_a", "weight": 1.0}]
    result = main.run_wvr(weights_list, {"cat_a": 0.5}, code_quality_vi=0.0)
    assert result == 50.0


def test_run_validate_includes_inter_rater_when_pairs_given():
    weights_list = [{"category": "cat_a", "weight": 1.0}]
    test_rows = [{"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.0, "expert_score": 50.0}]
    result = main.run_validate(test_rows, weights_list, expert_pairs=[(80, 82), (60, 58)])
    assert "inter_rater" in result
    assert "spearman_rho" in result["inter_rater"]


def test_run_validate_omits_inter_rater_when_no_pairs():
    weights_list = [{"category": "cat_a", "weight": 1.0}]
    test_rows = [{"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.0, "expert_score": 50.0}]
    result = main.run_validate(test_rows, weights_list)
    assert "inter_rater" not in result
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/scoring
python -m pytest tests/test_main.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write the minimal implementation**

`services/scoring/main.py`:
```python
"""Orchestrates vi-building, split assignment, fitting, WVR application,
and validation for the scoring service's Flask routes."""

from inter_rater import compute_inter_rater
from split import assign_split
from validation import compute_validation
from vi_builder import build_category_vi, build_code_quality_vi
from weight_fitting import cross_validate, fit_weights
from wvr_calculator import compute_wvr


def run_build_vi(skill_rows: list, summary, range_hint: dict) -> dict:
    return {
        "vi_by_category": build_category_vi(skill_rows),
        "code_quality_vi": build_code_quality_vi(summary, range_hint),
    }


def run_assign_split(user_ids: list, train_fraction: float, seed: int, existing: dict = None) -> dict:
    return assign_split(user_ids, train_fraction, seed, existing or {})


def run_fit(training_rows: list, categories: list, weights_version: str) -> dict:
    weights = fit_weights(training_rows, categories)
    cv_score = cross_validate(training_rows, categories)
    return {
        "status": "completed",
        "weights_version": weights_version,
        "weights": [{"category": category, "weight": weight} for category, weight in weights.items()],
        "cv_score": cv_score,
    }


def run_wvr(weights_list: list, vi_by_category: dict, code_quality_vi: float) -> float:
    weights = {item["category"]: item["weight"] for item in weights_list}
    return compute_wvr(weights, vi_by_category, code_quality_vi)


def run_validate(test_rows: list, weights_list: list, expert_pairs: list = None) -> dict:
    weights = {item["category"]: item["weight"] for item in weights_list}
    result = compute_validation(test_rows, weights)
    if expert_pairs:
        result["inter_rater"] = compute_inter_rater(expert_pairs)
    return result
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/scoring
python -m pytest tests/test_main.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add services/scoring/main.py services/scoring/tests/test_main.py
git commit -m "Add scoring-service orchestration"
```

---

### Task 8: Flask app (routes + shared-secret auth + catch-all error handling)

**Files:**
- Create: `services/scoring/app.py`
- Test: `services/scoring/tests/test_app.py`

**Interfaces:**
- Consumes: `main.run_build_vi`/`run_assign_split`/`run_fit`/`run_wvr`/`run_validate` (Task 7)
- Produces: HTTP routes `GET /health`, `POST /build-vi`, `POST /assign-split`, `POST /fit-weights`, `POST /compute-wvr`, `POST /validate` — consumed by Node's `server/src/utils/scoring.js` (Task 10).

- [ ] **Step 1: Write the failing test**

`services/scoring/tests/test_app.py`:
```python
import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_build_vi_requires_fields(client):
    resp = client.post("/build-vi", json={})
    assert resp.status_code == 400


def test_build_vi_returns_result(client, monkeypatch):
    monkeypatch.setattr(
        app_module.main, "run_build_vi",
        lambda rows, summary, range_hint: {"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.3},
    )
    resp = client.post(
        "/build-vi",
        json={"skill_verification_rows": [], "code_analysis_summary": None, "range_hint": {}},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"vi_by_category": {"cat_a": 0.5}, "code_quality_vi": 0.3}


def test_assign_split_requires_fields(client):
    resp = client.post("/assign-split", json={})
    assert resp.status_code == 400


def test_assign_split_returns_result(client, monkeypatch):
    monkeypatch.setattr(app_module.main, "run_assign_split", lambda ids, frac, seed, existing: {"a": "train"})
    resp = client.post("/assign-split", json={"user_ids": ["a"], "train_fraction": 0.7, "seed": 1})
    assert resp.status_code == 200
    assert resp.get_json() == {"assignments": {"a": "train"}}


def test_fit_weights_requires_fields(client):
    resp = client.post("/fit-weights", json={})
    assert resp.status_code == 400


def test_fit_weights_returns_result(client, monkeypatch):
    fake_result = {"status": "completed", "weights_version": "v1", "weights": [], "cv_score": None}
    monkeypatch.setattr(app_module.main, "run_fit", lambda rows, categories, version: fake_result)
    resp = client.post(
        "/fit-weights",
        json={
            "training_rows": [{"vi_by_category": {}, "code_quality_vi": 0, "expert_score": 1}],
            "categories": ["cat_a"],
            "weights_version": "v1",
        },
    )
    assert resp.status_code == 200
    assert resp.get_json() == fake_result


def test_fit_weights_unexpected_error_returns_json_500(client, monkeypatch):
    def raise_boom(rows, categories, version):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module.main, "run_fit", raise_boom)
    resp = client.post(
        "/fit-weights",
        json={"training_rows": [{}], "categories": ["cat_a"], "weights_version": "v1"},
    )
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "fit_failed"


def test_compute_wvr_requires_fields(client):
    resp = client.post("/compute-wvr", json={})
    assert resp.status_code == 400


def test_compute_wvr_returns_result(client, monkeypatch):
    monkeypatch.setattr(app_module.main, "run_wvr", lambda weights, vi, cq: 42.0)
    resp = client.post(
        "/compute-wvr",
        json={
            "weights": [{"category": "cat_a", "weight": 1.0}],
            "vi_by_category": {"cat_a": 0.5},
            "code_quality_vi": 0.0,
        },
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"wvr_score": 42.0}


def test_validate_requires_fields(client):
    resp = client.post("/validate", json={})
    assert resp.status_code == 400


def test_validate_returns_result(client, monkeypatch):
    fake_result = {"spearman_rho": 0.5, "mae": 3.2, "sample_size": 10}
    monkeypatch.setattr(app_module.main, "run_validate", lambda rows, weights, pairs=None: fake_result)
    resp = client.post(
        "/validate",
        json={
            "test_rows": [{"vi_by_category": {}, "code_quality_vi": 0, "expert_score": 1}],
            "weights": [{"category": "cat_a", "weight": 1.0}],
        },
    )
    assert resp.status_code == 200
    assert resp.get_json() == fake_result


def test_unauthorized_without_api_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "secret123")
    resp = client.post("/fit-weights", json={})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/scoring
python -m pytest tests/test_app.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write the minimal implementation**

`services/scoring/app.py`:
```python
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5004)))
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/scoring
python -m pytest tests/test_app.py -v
```
Expected: PASS (13 tests)

- [ ] **Step 5: Run the full Python test suite**

```bash
cd services/scoring
python -m pytest -v
```
Expected: all tests across all files PASS.

- [ ] **Step 6: Commit**

```bash
git add services/scoring/app.py services/scoring/tests/test_app.py
git commit -m "Add scoring Flask app with shared-secret auth and catch-all error handling"
```

---

## Part B — Node integration

### Task 9: Database schema and environment configuration

**Files:**
- Modify: `server/supabase/schema.sql`
- Modify: `server/.env.example`
- Modify: `server/src/config/env.js`

**Interfaces:**
- Produces: Supabase tables `expert_scores`, `train_test_split`, `skill_weights`, `wvr_scores`, `validation_results`; `env.scoring.url` / `env.scoring.apiKey` — consumed by Task 10.

- [ ] **Step 1: Check whether `server/.env` exists with real Supabase credentials**

```bash
ls server/.env
```
Whether or not it exists, proceed with the steps below (the schema file is edited either way). **Do not** apply the migration to a live database yourself — note in your report whether `server/.env` exists, so the next step (Task 12's seed script) is understood as "ready to run" vs. "credentials also still needed."

- [ ] **Step 2: Append the new tables to `server/supabase/schema.sql`**

Add after the existing `code_analysis_summary` block and before the final RLS-enabling section (this is the exact schema from design spec §12):

```sql
-- ---------------------------------------------------------------------------
-- expert_scores  — industry-expert judgment per student, the training/
-- validation target for weight-fitting. SYNTHETIC ONLY as of this schema's
-- introduction (design spec §2) — expert_id is a plain text identifier,
-- not a users FK, since experts are not DevScore accounts in this pass.
-- ---------------------------------------------------------------------------
create table if not exists public.expert_scores (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.users (id) on delete cascade,
  expert_id    text not null,
  score        numeric not null,
  submitted_at timestamptz not null default now()
);
create index if not exists expert_scores_user_id_idx on public.expert_scores (user_id);

-- ---------------------------------------------------------------------------
-- train_test_split  — locked, immutable-once-assigned train/train split
-- for weight-fitting (module spec §10).
-- ---------------------------------------------------------------------------
create table if not exists public.train_test_split (
  user_id     uuid primary key references public.users (id) on delete cascade,
  split       text not null check (split in ('train', 'test')),
  assigned_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- skill_weights  — one row per skill-category (plus 'code_quality') per
-- frozen weights_version. Never recomputed in place; a new version is a
-- new set of rows.
-- ---------------------------------------------------------------------------
create table if not exists public.skill_weights (
  id              uuid primary key default gen_random_uuid(),
  category        text not null,
  weight          numeric not null check (weight >= 0),
  weights_version text not null,
  fitted_at       timestamptz not null default now()
);
create index if not exists skill_weights_version_idx on public.skill_weights (weights_version);

-- ---------------------------------------------------------------------------
-- wvr_scores  — computed WVR per student for a given weights_version.
-- weights_version is a plain text match against skill_weights, not a FK
-- (skill_weights has multiple rows per version, so weights_version isn't
-- unique there — design spec §3).
-- ---------------------------------------------------------------------------
create table if not exists public.wvr_scores (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references public.users (id) on delete cascade,
  wvr_score       numeric not null,
  weights_version text not null,
  computed_at     timestamptz not null default now()
);
create index if not exists wvr_scores_user_id_idx on public.wvr_scores (user_id);

-- ---------------------------------------------------------------------------
-- validation_results  — headline agreement statistics for a given
-- weights_version (spearman_rho/mae on the test split, inter_rater_alpha
-- on overlapping expert scores).
-- ---------------------------------------------------------------------------
create table if not exists public.validation_results (
  id              uuid primary key default gen_random_uuid(),
  weights_version text not null,
  metric_name     text not null check (metric_name in ('spearman_rho', 'mae', 'inter_rater_alpha')),
  metric_value    numeric not null,
  sample_size     int not null,
  computed_at     timestamptz not null default now()
);
```

And add these five lines alongside the existing `alter table ... enable row level security;` block at the bottom of the file:
```sql
alter table public.expert_scores enable row level security;
alter table public.train_test_split enable row level security;
alter table public.skill_weights enable row level security;
alter table public.wvr_scores enable row level security;
alter table public.validation_results enable row level security;
```

- [ ] **Step 3: Add environment variables to `server/.env.example`**

Append after the existing `CODE_ANALYSIS_API_KEY=` line:
```
# Scoring microservice (WVR weight-fitting, synthetic-data pass — see
# docs/superpowers/specs/2026-09-03-scoring-model-design.md section 2).
SCORING_URL=http://localhost:5004
SCORING_API_KEY=
```

- [ ] **Step 4: Add the config block to `server/src/config/env.js`**

Modify the `env` object — add after the existing `codeAnalysis` block:
```js
  scoring: {
    url: process.env.SCORING_URL || 'http://localhost:5004',
    apiKey: process.env.SCORING_API_KEY || '',
  },
```

- [ ] **Step 5: Verify JS syntax**

```bash
cd server
node --check src/config/env.js
```

- [ ] **Step 6: Commit**

```bash
git add server/supabase/schema.sql server/.env.example server/src/config/env.js
git commit -m "Add scoring-model tables and service config"
```

---

### Task 10: Node HTTP client for the Python service

**Files:**
- Create: `server/src/utils/scoring.js`

**Interfaces:**
- Consumes: `env.scoring` (Task 9)
- Produces: `buildVi(skillRows, summary, rangeHint) -> Promise<{vi_by_category, code_quality_vi}>`, `assignSplit(userIds, trainFraction, seed, existing) -> Promise<{assignments}>`, `fitWeights(trainingRows, categories, weightsVersion) -> Promise<{status, weights_version, weights, cv_score}>`, `computeWvr(weights, viByCategory, codeQualityVi) -> Promise<{wvr_score}>`, `validateWeights(testRows, weights, expertPairs) -> Promise<object>`. Consumed by Task 13's controller.

No automated test for this file — thin HTTP-call wrapper with no branching logic beyond status-code checks, matching the other three services' Node clients in this codebase.

- [ ] **Step 1: Write the implementation**

`server/src/utils/scoring.js`:
```js
import { env } from '../config/env.js';

const REQUEST_TIMEOUT_MS = 60_000;

function headers() {
  return {
    'Content-Type': 'application/json',
    ...(env.scoring.apiKey ? { 'X-Api-Key': env.scoring.apiKey } : {}),
  };
}

async function post(path, body) {
  const res = await fetch(`${env.scoring.url}${path}`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!res.ok) {
    throw new Error(`scoring ${path} responded ${res.status}`);
  }
  return res.json();
}

/** Calls the scoring service's /build-vi route. */
export function buildVi(skillVerificationRows, codeAnalysisSummary, rangeHint) {
  return post('/build-vi', {
    skill_verification_rows: skillVerificationRows,
    code_analysis_summary: codeAnalysisSummary,
    range_hint: rangeHint,
  });
}

/** Calls the scoring service's /assign-split route. */
export async function assignSplit(userIds, trainFraction, seed, existing) {
  const result = await post('/assign-split', {
    user_ids: userIds,
    train_fraction: trainFraction,
    seed,
    existing,
  });
  return result.assignments;
}

/** Calls the scoring service's /fit-weights route. */
export function fitWeights(trainingRows, categories, weightsVersion) {
  return post('/fit-weights', {
    training_rows: trainingRows,
    categories,
    weights_version: weightsVersion,
  });
}

/** Calls the scoring service's /compute-wvr route. */
export async function computeWvr(weights, viByCategory, codeQualityVi) {
  const result = await post('/compute-wvr', {
    weights,
    vi_by_category: viByCategory,
    code_quality_vi: codeQualityVi,
  });
  return result.wvr_score;
}

/** Calls the scoring service's /validate route. */
export function validateWeights(testRows, weights, expertPairs) {
  return post('/validate', { test_rows: testRows, weights, expert_pairs: expertPairs });
}
```

- [ ] **Step 2: Verify syntax**

```bash
cd server
node --check src/utils/scoring.js
```

- [ ] **Step 3: Commit**

```bash
git add server/src/utils/scoring.js
git commit -m "Add Node HTTP client for the scoring service"
```

---

### Task 11: Data-access models

**Files:**
- Create: `server/src/models/ScoringInputs.js`
- Create: `server/src/models/ScoringResults.js`

Design spec §11 names four separate files (`ScoringWeights.js`, `WvrScore.js`, `ExpertScore.js`, `ValidationResult.js`) while also saying to mirror `CodeAnalysis.js`'s style — but `CodeAnalysis.js` is itself one consolidated file for two related tables (`code_analysis`/`code_analysis_summary`). This task resolves that in favor of the actual precedent it points to: two files, one per related table group (inputs vs. outputs), not four.

**Interfaces:**
- Produces (`ScoringInputs.js` — reads/writes this module's own input tables, plus **read-only** queries against `skill_verification`/`code_analysis_summary`, kept self-contained here per this plan's Global Constraints rather than modifying `SkillVerification.js`/`CodeAnalysis.js`):
  - `listExpertScoredUserIds() -> Promise<string[]>`
  - `findExpertScoresByUserIds(userIds) -> Promise<{[userId]: number}>`
  - `insertExpertScore(userId, expertId, score) -> Promise<row>`
  - `getSplitAssignments() -> Promise<{[userId]: 'train'|'test'}>`
  - `saveSplitAssignments(assignments) -> Promise<void>`
  - `fetchSkillVerificationForUsers(userIds) -> Promise<{[userId]: Array<{category, verified, confidence}>}>`
  - `fetchCodeAnalysisSummariesForUsers(userIds) -> Promise<{[userId]: {avg_complexity_overall, total_loc_overall} | null}>`
- Produces (`ScoringResults.js`):
  - `saveWeights(weightsVersion, weights) -> Promise<row[]>` (`weights` = `[{category, weight}]`)
  - `findWeights(weightsVersion) -> Promise<Array<{category, weight}>>`
  - `saveWvrScore(userId, wvrScore, weightsVersion) -> Promise<row>`
  - `saveValidationResults(weightsVersion, results) -> Promise<row[]>` (`results` = `[{metric_name, metric_value, sample_size}]`)
- Consumed by Task 13's controller. No automated tests — plain Supabase CRUD with no branching logic beyond the joins themselves, following the exact style of the existing untested `CodeAnalysis.js`/`SkillVerification.js` models.

- [ ] **Step 1: Create `server/src/models/ScoringInputs.js`**

```js
import { supabase } from '../config/db.js';

/**
 * Inputs to the scoring pipeline: this module's own expert_scores/
 * train_test_split tables, plus read-only access to Module 1/2's
 * skill_verification/code_analysis_summary tables (kept self-contained
 * here rather than modifying those modules' own model files).
 */

/** Every user_id that has at least one expert_scores row. */
export async function listExpertScoredUserIds() {
  const { data, error } = await supabase.from('expert_scores').select('user_id');
  if (error) throw new Error(error.message);
  return [...new Set(data.map((row) => row.user_id))];
}

/** One expert_scores row per user (the average, if more than one expert scored them). */
export async function findExpertScoresByUserIds(userIds) {
  const { data, error } = await supabase
    .from('expert_scores')
    .select('user_id, score')
    .in('user_id', userIds);
  if (error) throw new Error(error.message);

  const totals = {};
  const counts = {};
  for (const row of data) {
    totals[row.user_id] = (totals[row.user_id] || 0) + row.score;
    counts[row.user_id] = (counts[row.user_id] || 0) + 1;
  }
  return Object.fromEntries(
    Object.keys(totals).map((userId) => [userId, totals[userId] / counts[userId]]),
  );
}

/** Insert one expert_scores row. `expertId` must be a synthetic-* identifier in this pass. */
export async function insertExpertScore(userId, expertId, score) {
  const { data, error } = await supabase
    .from('expert_scores')
    .insert({ user_id: userId, expert_id: expertId, score })
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

/** All train_test_split rows, as a {userId: split} map. */
export async function getSplitAssignments() {
  const { data, error } = await supabase.from('train_test_split').select('user_id, split');
  if (error) throw new Error(error.message);
  return Object.fromEntries(data.map((row) => [row.user_id, row.split]));
}

/** Upsert every {userId: split} pair in `assignments`. */
export async function saveSplitAssignments(assignments) {
  const rows = Object.entries(assignments).map(([userId, split]) => ({ user_id: userId, split }));
  if (rows.length === 0) return;
  const { error } = await supabase.from('train_test_split').upsert(rows, { onConflict: 'user_id' });
  if (error) throw new Error(error.message);
}

/** Per-user skill_verification rows (joined to skills.category), for vi-building. */
export async function fetchSkillVerificationForUsers(userIds) {
  const { data, error } = await supabase
    .from('skill_verification')
    .select('user_id, verified, confidence, skills(category)')
    .in('user_id', userIds);
  if (error) throw new Error(error.message);

  const byUser = {};
  for (const row of data) {
    const entry = { category: row.skills?.category ?? null, verified: row.verified, confidence: row.confidence };
    (byUser[row.user_id] ||= []).push(entry);
  }
  return byUser;
}

/** Per-user code_analysis_summary row (or null if never analyzed), for vi-building. */
export async function fetchCodeAnalysisSummariesForUsers(userIds) {
  const { data, error } = await supabase
    .from('code_analysis_summary')
    .select('user_id, avg_complexity_overall, total_loc_overall')
    .in('user_id', userIds);
  if (error) throw new Error(error.message);

  const byUser = Object.fromEntries(userIds.map((id) => [id, null]));
  for (const row of data) {
    byUser[row.user_id] = {
      avg_complexity_overall: row.avg_complexity_overall,
      total_loc_overall: row.total_loc_overall,
    };
  }
  return byUser;
}
```

- [ ] **Step 2: Create `server/src/models/ScoringResults.js`**

```js
import { supabase } from '../config/db.js';

/** Outputs of the scoring pipeline: frozen weights, computed WVR scores, validation stats. */

/** Replace-wholesale write of one weights_version's category rows. */
export async function saveWeights(weightsVersion, weights) {
  const rows = weights.map((w) => ({
    category: w.category,
    weight: w.weight,
    weights_version: weightsVersion,
  }));
  const { data, error } = await supabase.from('skill_weights').insert(rows).select();
  if (error) throw new Error(error.message);
  return data;
}

/** Read back one weights_version's category rows. */
export async function findWeights(weightsVersion) {
  const { data, error } = await supabase
    .from('skill_weights')
    .select('category, weight')
    .eq('weights_version', weightsVersion);
  if (error) throw new Error(error.message);
  return data;
}

/** Store one student's computed WVR score for a given weights_version. */
export async function saveWvrScore(userId, wvrScore, weightsVersion) {
  const { data, error } = await supabase
    .from('wvr_scores')
    .insert({ user_id: userId, wvr_score: wvrScore, weights_version: weightsVersion })
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

/** Store this weights_version's validation metrics (spearman_rho, mae, inter_rater_alpha). */
export async function saveValidationResults(weightsVersion, results) {
  const rows = results.map((r) => ({
    weights_version: weightsVersion,
    metric_name: r.metric_name,
    metric_value: r.metric_value,
    sample_size: r.sample_size,
  }));
  const { data, error } = await supabase.from('validation_results').insert(rows).select();
  if (error) throw new Error(error.message);
  return data;
}
```

- [ ] **Step 3: Verify syntax**

```bash
cd server
node --check src/models/ScoringInputs.js
node --check src/models/ScoringResults.js
```

- [ ] **Step 4: Commit**

```bash
git add server/src/models/ScoringInputs.js server/src/models/ScoringResults.js
git commit -m "Add scoring-model data-access models"
```

---

### Task 12: Synthetic expert-score seed script

**Files:**
- Create: `server/scripts/seedSyntheticExpertScores.js`

**Interfaces:**
- Consumes: `supabase` (`server/src/config/db.js`), `ROLES` (`server/src/models/User.js`)
- Produces: a standalone script (not part of the Express app) that populates `expert_scores` with clearly-labeled synthetic rows for real student `user_id`s, so the rest of this module's pipeline has something to run against. Never runs without an explicit `--confirm` flag; every row it writes has `expert_id` prefixed `synthetic-` (design spec §2 / this plan's Global Constraints).

- [ ] **Step 1: Write the script**

`server/scripts/seedSyntheticExpertScores.js`:
```js
/**
 * Seeds expert_scores with SYNTHETIC rows for every existing student, so
 * this module's pipeline (split -> fit -> validate) has something to run
 * against. This is dev/test data ONLY — every row's expert_id is prefixed
 * "synthetic-" specifically so it can never be mistaken for real
 * industry-expert judgment in a query or a report (design spec section 2).
 *
 * Usage: node server/scripts/seedSyntheticExpertScores.js --confirm
 */
import { supabase } from '../src/config/db.js';
import { ROLES } from '../src/models/User.js';

const SYNTHETIC_EXPERT_ID = 'synthetic-v1';

function randomScore(seedable) {
  // Simple deterministic-ish spread (not cryptographic, not statistically
  // rigorous) — this only needs to be plausible enough to exercise the
  // pipeline's mechanics, per design spec section 2's scope.
  const hash = [...seedable].reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  return Math.round(((hash % 100) + 100) % 100 * 10) / 10;
}

async function main() {
  if (!process.argv.includes('--confirm')) {
    console.error('Refusing to run without --confirm. This writes SYNTHETIC data, not real expert scores.');
    process.exit(1);
  }

  const { data: students, error } = await supabase
    .from('users')
    .select('id')
    .eq('role', ROLES.STUDENT);
  if (error) throw new Error(error.message);

  if (students.length === 0) {
    console.log('No students found — nothing to seed.');
    return;
  }

  const rows = students.map((student) => ({
    user_id: student.id,
    expert_id: SYNTHETIC_EXPERT_ID,
    score: randomScore(student.id),
  }));

  const { error: insertError } = await supabase.from('expert_scores').insert(rows);
  if (insertError) throw new Error(insertError.message);

  console.log(`Seeded ${rows.length} SYNTHETIC expert_scores rows (expert_id="${SYNTHETIC_EXPERT_ID}").`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

- [ ] **Step 2: Verify syntax**

```bash
cd server
node --check scripts/seedSyntheticExpertScores.js
```

- [ ] **Step 3: Commit**

```bash
git add server/scripts/seedSyntheticExpertScores.js
git commit -m "Add synthetic expert-score seed script (dev/test data only)"
```

---

### Task 13: Controller, routes, and app.js mounting

**Files:**
- Create: `server/src/controllers/scoringController.js`
- Create: `server/src/routes/scoringRoutes.js`
- Modify: `server/src/app.js`

**Interfaces:**
- Consumes: `ScoringInputs.*`/`ScoringResults.*` (Task 11), `buildVi`/`assignSplit`/`fitWeights`/`validateWeights` (Task 10)
- Produces: `POST /api/scoring/assign-split`, `POST /api/scoring/fit-weights`, `POST /api/scoring/validate` — all `requireRole('admin')` only (design spec §2/§11: no student/recruiter endpoint in this pass). No automated test — orchestrates several already-tested I/O-bound pieces with no new pure logic of its own, matching the established precedent for this shape of controller in this codebase.

- [ ] **Step 1: Create `server/src/controllers/scoringController.js`**

```js
import * as ScoringInputs from '../models/ScoringInputs.js';
import * as ScoringResults from '../models/ScoringResults.js';
import { assignSplit, buildVi, fitWeights, validateWeights } from '../utils/scoring.js';

const DEFAULT_TRAIN_FRACTION = 0.7;

/** A 502 for the Node error handler to surface when the Python service is unreachable or errors. */
function serviceUnavailableError() {
  const err = new Error('scoring_service_unavailable');
  err.status = 502;
  err.expose = true;
  return err;
}

/** Min/max of avg_complexity_overall/total_loc_overall across a set of summaries, for vi_builder normalization. */
function rangeHintFrom(summaries) {
  const complexities = summaries.map((s) => s?.avg_complexity_overall).filter((v) => v != null);
  const locs = summaries.map((s) => s?.total_loc_overall).filter((v) => v != null);
  return {
    complexity_min: complexities.length ? Math.min(...complexities) : 0,
    complexity_max: complexities.length ? Math.max(...complexities) : 0,
    loc_min: locs.length ? Math.min(...locs) : 0,
    loc_max: locs.length ? Math.max(...locs) : 0,
  };
}

/** Admin-only: assigns any not-yet-split scored students into train/test groups. */
export async function runAssignSplit(req, res, next) {
  try {
    const trainFraction = req.body?.trainFraction ?? DEFAULT_TRAIN_FRACTION;
    const seed = req.body?.seed ?? 42;

    const [existing, allUserIds] = await Promise.all([
      ScoringInputs.getSplitAssignments(),
      ScoringInputs.listExpertScoredUserIds(),
    ]);
    if (allUserIds.length === 0) {
      return res.status(400).json({ error: 'No students with expert scores to split' });
    }

    let assignments;
    try {
      assignments = await assignSplit(allUserIds, trainFraction, seed, existing);
    } catch {
      return next(serviceUnavailableError());
    }

    await ScoringInputs.saveSplitAssignments(assignments);
    res.json({ status: 'completed', assignments });
  } catch (err) {
    next(err);
  }
}

/** Admin-only: fits weights on the current training split and freezes them under weightsVersion. */
export async function runFitWeights(req, res, next) {
  try {
    const weightsVersion = req.body?.weightsVersion;
    const categories = req.body?.categories;
    if (!weightsVersion || !Array.isArray(categories) || categories.length === 0) {
      return res.status(400).json({ error: 'weightsVersion and categories are required' });
    }

    const split = await ScoringInputs.getSplitAssignments();
    const trainUserIds = Object.entries(split)
      .filter(([, group]) => group === 'train')
      .map(([userId]) => userId);
    if (trainUserIds.length === 0) {
      return res.status(400).json({ error: 'No training-split students assigned yet' });
    }

    const [skillRowsByUser, summaryByUser, expertScoreByUser] = await Promise.all([
      ScoringInputs.fetchSkillVerificationForUsers(trainUserIds),
      ScoringInputs.fetchCodeAnalysisSummariesForUsers(trainUserIds),
      ScoringInputs.findExpertScoresByUserIds(trainUserIds),
    ]);
    const rangeHint = rangeHintFrom(Object.values(summaryByUser));
    const scoredUserIds = trainUserIds.filter((userId) => expertScoreByUser[userId] != null);
    if (scoredUserIds.length === 0) {
      return res.status(400).json({ error: 'No training-split students have expert scores yet' });
    }

    let trainingRows;
    try {
      trainingRows = await Promise.all(
        scoredUserIds.map(async (userId) => {
          const vi = await buildVi(skillRowsByUser[userId] || [], summaryByUser[userId] || null, rangeHint);
          return {
            vi_by_category: vi.vi_by_category,
            code_quality_vi: vi.code_quality_vi,
            expert_score: expertScoreByUser[userId],
          };
        }),
      );
    } catch {
      return next(serviceUnavailableError());
    }

    let result;
    try {
      result = await fitWeights(trainingRows, categories, weightsVersion);
    } catch {
      return next(serviceUnavailableError());
    }

    await ScoringResults.saveWeights(weightsVersion, result.weights);
    res.json(result);
  } catch (err) {
    next(err);
  }
}

/** Admin-only: validates a frozen weights_version against the test split's expert scores. */
export async function runValidate(req, res, next) {
  try {
    const weightsVersion = req.body?.weightsVersion;
    if (!weightsVersion) {
      return res.status(400).json({ error: 'weightsVersion is required' });
    }

    const [weights, split] = await Promise.all([
      ScoringResults.findWeights(weightsVersion),
      ScoringInputs.getSplitAssignments(),
    ]);
    if (weights.length === 0) {
      return res.status(404).json({ error: 'Unknown weightsVersion' });
    }

    const testUserIds = Object.entries(split)
      .filter(([, group]) => group === 'test')
      .map(([userId]) => userId);
    const [skillRowsByUser, summaryByUser, expertScoreByUser] = await Promise.all([
      ScoringInputs.fetchSkillVerificationForUsers(testUserIds),
      ScoringInputs.fetchCodeAnalysisSummariesForUsers(testUserIds),
      ScoringInputs.findExpertScoresByUserIds(testUserIds),
    ]);
    const rangeHint = rangeHintFrom(Object.values(summaryByUser));
    const scoredUserIds = testUserIds.filter((userId) => expertScoreByUser[userId] != null);
    if (scoredUserIds.length === 0) {
      return res.status(400).json({ error: 'No test-split students have expert scores yet' });
    }

    let testRows;
    let result;
    try {
      testRows = await Promise.all(
        scoredUserIds.map(async (userId) => {
          const vi = await buildVi(skillRowsByUser[userId] || [], summaryByUser[userId] || null, rangeHint);
          return {
            vi_by_category: vi.vi_by_category,
            code_quality_vi: vi.code_quality_vi,
            expert_score: expertScoreByUser[userId],
          };
        }),
      );
      result = await validateWeights(testRows, weights);
    } catch {
      return next(serviceUnavailableError());
    }

    await ScoringResults.saveValidationResults(weightsVersion, [
      { metric_name: 'spearman_rho', metric_value: result.spearman_rho, sample_size: result.sample_size },
      { metric_name: 'mae', metric_value: result.mae, sample_size: result.sample_size },
    ]);
    res.json(result);
  } catch (err) {
    next(err);
  }
}
```

- [ ] **Step 2: Create `server/src/routes/scoringRoutes.js`**

```js
import { Router } from 'express';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { runAssignSplit, runFitWeights, runValidate } from '../controllers/scoringController.js';

const router = Router();

// Admin-only in this pass — no student/recruiter endpoint yet (design spec §2).
router.post('/assign-split', requireAuth, requireRole('admin'), runAssignSplit);
router.post('/fit-weights', requireAuth, requireRole('admin'), runFitWeights);
router.post('/validate', requireAuth, requireRole('admin'), runValidate);

export default router;
```

- [ ] **Step 3: Mount the router in `server/src/app.js`**

Add the import alongside the other route imports:
```js
import scoringRoutes from './routes/scoringRoutes.js';
```
And mount it alongside the other `app.use('/api/...')` lines:
```js
  app.use('/api/scoring', scoringRoutes);
```

- [ ] **Step 4: Verify syntax and import resolution**

```bash
cd server
node --check src/controllers/scoringController.js
node --check src/routes/scoringRoutes.js
node --check src/app.js
node -e "import('./src/app.js').then(() => console.log('app.js imports resolved OK')).catch(e => { console.error(e); process.exit(1); })"
```

- [ ] **Step 5: Confirm the app.js diff is purely additive**

```bash
git diff server/src/app.js
```
Only two new lines (one import, one `app.use`) should appear.

- [ ] **Step 6: Commit**

```bash
git add server/src/controllers/scoringController.js server/src/routes/scoringRoutes.js server/src/app.js
git commit -m "Wire up scoring API endpoints (admin-only, synthetic-data pass)"
```

---

### Task 14: Full test suite run + manual smoke test

**Files:** None created — confirms Tasks 1-13 work together, then a manual sanity pass (no exact metric values are asserted here; this is a smoke check against the synthetic pipeline, mirroring the other two modules' final task).

- [ ] **Step 1: Run the full Python test suite**

```bash
cd services/scoring
python -m pytest -v
```
Expected: PASS — all tests from Tasks 1-8.

- [ ] **Step 2: Run the full Node test suite**

```bash
cd server
npm test
```
Expected: PASS — this module adds no new `*.test.js` files (Task 11's models and Task 13's controller/routes are untested by design, matching precedent), so this confirms no regression in the existing suite.

- [ ] **Step 3: Start the scoring service and smoke-test it without Supabase**

```bash
cd services/scoring
python app.py
```
In another terminal:
```bash
curl -s http://localhost:5004/health
curl -s -X POST http://localhost:5004/fit-weights \
  -H "Content-Type: application/json" \
  -d '{"training_rows": [{"vi_by_category": {"cat_a": 0.8}, "code_quality_vi": 0.6, "expert_score": 75}, {"vi_by_category": {"cat_a": 0.2}, "code_quality_vi": 0.1, "expert_score": 20}], "categories": ["cat_a"], "weights_version": "smoke_test"}'
```
Confirm the response's `weights` array has non-negative values for both `cat_a` and `code_quality`, and `status` is `"completed"`.

- [ ] **Step 4: If `server/.env` has real Supabase credentials, run the seed script and one real end-to-end pass**

```bash
node server/scripts/seedSyntheticExpertScores.js --confirm
```
Then, as an admin (a real session cookie from logging in as an admin account):
```bash
curl -X POST http://localhost:5000/api/scoring/assign-split \
  -H "Content-Type: application/json" \
  -H "Cookie: devscore_session=<admin session cookie>" \
  -d '{"trainFraction": 0.7, "seed": 42}'

curl -X POST http://localhost:5000/api/scoring/fit-weights \
  -H "Content-Type: application/json" \
  -H "Cookie: devscore_session=<admin session cookie>" \
  -d '{"weightsVersion": "v1_synthetic_2026_09", "categories": ["backend_languages", "frontend_frameworks", "testing_devops"]}'

curl -X POST http://localhost:5000/api/scoring/validate \
  -H "Content-Type: application/json" \
  -H "Cookie: devscore_session=<admin session cookie>" \
  -d '{"weightsVersion": "v1_synthetic_2026_09"}'
```
Confirm each call returns `200` and plausible-shaped JSON. **Do not** interpret the `spearman_rho`/`mae` numbers from this run as a real result — the underlying `expert_scores` are synthetic (Task 12), so this step only confirms the pipeline runs end-to-end, not that it says anything about real hiring judgment.

- [ ] **Step 5: If real credentials aren't available in this environment, skip Step 4 and note the limitation**

Same pattern as the prior two modules' final task — report what could and couldn't be exercised, rather than fabricating results.

- [ ] **Step 6: Note findings**

No commit for this task. If this surfaces a real bug, fix it as a follow-up task with its own test (per this plan's TDD approach) rather than patching silently.
