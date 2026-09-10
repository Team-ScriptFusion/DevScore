# Design: Scoring Model — WVR + Expert-Informed Weights (Implementation 02, Module 3)

Status: approved for planning — **synthetic-data scope only** (see Section 2)
Date: 2026-09-03

## 1. Problem and origin

DevScore's job-readiness score (`WVR = Σ(Wi·Vi) / ΣWi × 100`) needs two things
nobody has built yet: a way to combine Module 1's (`skill_verification`) and
Module 2's (`code_analysis_summary`) outputs into a per-skill `Vi`, and
learned (not guessed) per-skill importance weights `Wi`, fit against
industry-expert judgment and validated on held-out data.

## 2. Scope of this implementation pass — read this before anything else

**There are no real industry-expert scores yet, and none will be fabricated
by an LLM to fill that gap.** The team has 50 CVs and no committed expert
reviewers. Generating "expert" scores with Claude and presenting them as
industry judgment would be data fabrication under the project's ethical
clearance (which specifies real industry professionals) and would make the
headline research question circular — WVR is built from skill-verification
and code-complexity signals; an LLM scoring the same evidence would agree
with WVR by construction, not because WVR approximates real hiring judgment.

This pass therefore builds and tests the **entire computational pipeline** —
Vi-building, train/test split, weight-fitting, WVR calculation, validation
statistics, inter-rater agreement — against a clearly-labeled **synthetic**
expert-score dataset generated with a known formula (Section 10). This is
the brief's own Section 5 fallback ("build against synthetic/fake data
matching documented schemas... swap in real data once available"), not a
deviation from it. Real expert-score collection is a separate, non-technical
workstream tracked outside this codebase; when it lands, the swap is: seed
`expert_scores` with real rows instead of synthetic ones, re-run the same
fitting/validation code unchanged.

**Explicitly out of scope for this pass:**
- Any UI or API for experts to submit scores (no `expert` role exists in
  `users`; adding real-expert account infrastructure is premature while
  recruitment is unresolved — see Section 8).
- Recruiter-dashboard wiring (the "coming once the scoring engine ships"
  placeholder in `CandidateProfile.jsx` stays as-is; wiring it to a real WVR
  number needs real expert-validated weights, not synthetic ones).
- A committed 70/30 split ratio or count — the brief's ~100/70/30 assumes
  more students than currently exist (50 CVs); the split is a parameter,
  decided when real data exists.

## 3. Deviations from the original module brief

Same category of corrections as Modules 1 and 2's specs, grounded in this
codebase's real, already-built patterns:

- Schema uses `user_id` throughout, not `student_id` (matches every existing
  table, including Modules 1/2's).
- RLS enabled with **zero policies** (service-role key only, authorization
  in Express) — matches every table in this schema, not the brief's
  per-role-policy sketch.
- `expert_scores.expert_id` is a **plain `text` identifier, not a foreign
  key to `users`**. The brief's schema implies experts are DevScore
  accounts; they are not, and won't be built as such in this pass (Section
  2). Real collection will most likely be an out-of-band form/spreadsheet an
  admin imports later — decided when recruitment happens, not now.
- `skills.category` exists but is **nullable and not reliably populated**
  today (seeded ad hoc from `cv_parser`'s dictionary scan — see
  `server/supabase/schema.sql` lines ~101-112). The brief's Section 8 step 3
  assumes clean skill categories are available for dimensionality reduction.
  This pass's synthetic-data generator assigns its own categories so the
  fitting/grouping code can be built and tested now; a real-data run will
  need `skills.category` backfilled first, noted as a prerequisite in
  Section 8 below, not solved by this module.
- Code-complexity (Module 2's output) is modeled as its **own separate
  weighted term** in the WVR sum, not a modifier on skill-level Vi (the
  brief's Section 6 leaves this as an open design choice) — keeps each
  fitted coefficient independently interpretable, which the brief's own
  Section 3/14 says matters more than raw fit quality at this sample size.
- No Ridge/Lasso/gradient-boosting escalation path is built in this pass —
  plain linear regression only, per the brief's Section 8 step 4's default,
  since there's no real cross-validation signal yet to justify escalating.
- The brief's `wvr_scores`/`validation_results` reference `skill_weights
  (weights_version)` as a foreign key, but `skill_weights` has one row per
  *category* per version — `weights_version` isn't unique on that table, so
  that FK could never validate as written. Section 12 below drops the FK and
  keeps `weights_version` a plain matching `text` value on both sides,
  same as how `code_analysis`/`code_analysis_summary` correlate rows by
  `user_id` without a formal FK between them.

## 4. Architecture

```
Node/Express (server/src)
  routes/scoringRoutes.js
  controllers/scoringController.js
      │  1. read skill_verification + code_analysis_summary for training-set
      │     users (real data — both tables already exist and are populated
      │     by Modules 1/2, unlike the brief's "maybe fake both" assumption)
      │  2. read expert_scores (synthetic in this pass)
      │  3. call Python service over HTTP (shared secret header)
      │  4. persist weights / WVR scores / validation results
      ▼
Python service (new)  services/scoring/
  app.py             — Flask, stateless, mirrors cv_parser/skill_verification/code_analysis
  fake_data.py        — synthetic Vi + expert-score generator (dev/test only,
                         never imported by production request-handling code)
  vi_builder.py        — combine skill_verification + code_analysis_summary rows -> per-skill Vi
  split.py             — train/test split, idempotent once assigned
  weight_fitting.py    — non-negative linear regression on training set -> Wi per category
  wvr_calculator.py    — applies frozen weights + a student's Vi's -> WVR
  validation.py        — Spearman/MAE on the test set
  inter_rater.py        — Spearman/Krippendorff agreement between experts on overlapping scores
  main.py               — orchestrates fit -> freeze -> score -> validate
```

Stateless like the other two Python services — no Supabase access inside
`services/scoring/`. Node owns persistence and authorization.

## 5. Python service — API contract (internal only)

`POST /fit-weights`, header `X-Api-Key: <SCORING_API_KEY>` (open-if-unset
local-dev degradation, same as the other services).

Request:
```json
{
  "training_rows": [
    {"user_id": "...", "vi_by_category": {"backend_languages": 0.8, "frontend_frameworks": 0.4}, "code_quality_vi": 0.6, "expert_score": 72.0}
  ],
  "weights_version": "v1_synthetic_2026_09"
}
```
`training_rows` is assembled by Node from real `skill_verification` +
`code_analysis_summary` (or synthetic fixtures in tests) joined against
`expert_scores` for that student — the Python service never touches
Supabase, exactly per Section 4.

Response:
```json
{
  "status": "completed",
  "weights_version": "v1_synthetic_2026_09",
  "weights": [
    {"category": "backend_languages", "weight": 0.34},
    {"category": "code_quality", "weight": 0.18}
  ],
  "cv_score": 0.71
}
```

`POST /compute-wvr` — applies a frozen weight set to one student's Vi
values; `POST /validate` — Spearman/MAE + inter-rater alpha on a
caller-supplied test set. All three return structured JSON errors (never a
raw Flask HTML page) on unexpected exceptions, matching Modules 1/2's fix-
round lesson applied from the start here.

## 6. Vi-building (`vi_builder.py`)

Per Section 3's resolution:
- Per-skill Vi from `skill_verification`: `confidence` if `verified`, else a
  fixed `0.1` (not `0.0` — "no evidence found" isn't the same claim as
  "evidence contradicts this," per the brief's own Section 6 reasoning).
- Skills are grouped into categories (`skills.category`, or `"uncategorized"`
  when null — see Section 3's caveat) and averaged within each category to
  keep the regression's input dimensionality small relative to the training
  set size.
- Code-complexity becomes one additional feature, `code_quality_vi`, derived
  from `code_analysis_summary` (a documented, simple normalization — e.g.
  min-max scaling `avg_complexity_overall`/`total_loc_overall` against the
  training set's own range — refined during implementation, not fixed in
  this spec, since it has no bearing on the pipeline's correctness).

## 7. Train/test split (`split.py`)

`assign_split(user_ids, train_fraction, seed) -> {user_id: 'train'|'test'}`.
Idempotent: calling it again on already-assigned IDs returns the existing
assignment unchanged (Section 12's required test). `train_fraction` and
`seed` are parameters, not hardcoded, per Section 2's note that the real
ratio is undecided until real student/expert counts are known.

## 8. Weight-fitting (`weight_fitting.py`) and WVR (`wvr_calculator.py`)

Non-negative least squares (`scipy.optimize.nnls`, or
`sklearn.linear_model.LinearRegression` with a post-hoc clip + documented
caveat if `nnls` proves awkward during implementation) regressing per-
category Vi + `code_quality_vi` against `expert_score` for the training
split only. K-fold cross-validation within the training split reports a
`cv_score` alongside the frozen weights — both stored, per Section 8 step
6/7 of the brief. `wvr_calculator.apply_weights(weights, vi_by_category,
code_quality_vi) -> float` implements the WVR formula literally, given any
already-frozen weight set.

**Real-data prerequisite, not solved here:** fitting against real students
requires `skills.category` to be populated for the skills actually claimed
(Section 3). This is noted as a blocker for the *real* run, not for this
pass, which supplies its own categories via synthetic data.

## 9. Validation (`validation.py`) and inter-rater agreement (`inter_rater.py`)

`compute_validation(test_rows, weights) -> {"spearman_rho": ..., "mae": ...,
"sample_size": ...}`. `compute_inter_rater(score_pairs) -> {"spearman_rho":
..., "alpha": ..., "sample_size": ...}` — both pure functions over lists of
numbers, no I/O, easily tested against hand-computed expected values.

## 10. Synthetic data generator (`fake_data.py`)

`generate_fake_dataset(n_students, seed) -> list[dict]` — produces
`vi_by_category`/`code_quality_vi`/`expert_score` rows from a **known linear
formula plus noise**, so weight-fitting tests can assert the recovered
weights approximate the known coefficients (the brief's Section 12 "known
relationship" test). This module is dev/test-only: nothing in `app.py`'s
request-handling path imports it — production `/fit-weights` calls always
take `training_rows` from the caller (Node), never generate their own.

## 11. Node integration

`server/src/models/ScoringWeights.js`, `server/src/models/WvrScore.js`,
`server/src/models/ExpertScore.js`, `server/src/models/ValidationResult.js`
— plain Supabase CRUD, mirroring `CodeAnalysis.js`'s style. `server/src/
utils/scoring.js` — HTTP client (`fitWeights`, `computeWvr`, `validate`),
same `fetch` + `AbortSignal.timeout` pattern as the other two utils.
`server/src/controllers/scoringController.js` — for this pass, exposes only
an admin-triggered `POST /api/scoring/fit-weights` (role: `admin`, reusing
`requireRole` — no new auth logic) that assembles training rows from real
`skill_verification`/`code_analysis_summary` joined against **synthetic**
`expert_scores` seeded by a one-off script, and freezes a weight version
explicitly named `v1_synthetic_...` so nobody mistakes it for a real result.
No student- or recruiter-facing endpoint is added in this pass (Section 2).

## 12. Data schema

```sql
create table if not exists public.expert_scores (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.users (id) on delete cascade,
  expert_id    text not null,  -- not a users FK — see Section 3
  score        numeric not null,
  submitted_at timestamptz not null default now()
);
create index if not exists expert_scores_user_id_idx on public.expert_scores (user_id);

create table if not exists public.train_test_split (
  user_id     uuid primary key references public.users (id) on delete cascade,
  split       text not null check (split in ('train', 'test')),
  assigned_at timestamptz not null default now()
);

create table if not exists public.skill_weights (
  id              uuid primary key default gen_random_uuid(),
  category        text not null,
  weight          numeric not null check (weight >= 0),
  weights_version text not null,
  fitted_at       timestamptz not null default now()
);
create index if not exists skill_weights_version_idx on public.skill_weights (weights_version);

create table if not exists public.wvr_scores (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references public.users (id) on delete cascade,
  wvr_score       numeric not null,
  weights_version text not null,
  computed_at     timestamptz not null default now()
);
create index if not exists wvr_scores_user_id_idx on public.wvr_scores (user_id);

create table if not exists public.validation_results (
  id            uuid primary key default gen_random_uuid(),
  weights_version text not null,
  metric_name     text not null check (metric_name in ('spearman_rho', 'mae', 'inter_rater_alpha')),
  metric_value    numeric not null,
  sample_size     int not null,
  computed_at     timestamptz not null default now()
);

alter table public.expert_scores enable row level security;
alter table public.train_test_split enable row level security;
alter table public.skill_weights enable row level security;
alter table public.wvr_scores enable row level security;
alter table public.validation_results enable row level security;
-- No policies — deny-by-default for anon/authenticated, service-role key
-- only, matching every other table in this schema.
```

## 13. Error handling

Same lessons carried forward from Modules 1/2's fix rounds, applied from the
start rather than discovered in review: Python-service unreachable/erroring
→ Node responds 502 `{"error": "scoring_service_unavailable"}`, never a
generic 500; the Python route's own unexpected exceptions are caught and
returned as structured JSON, never Flask's default HTML page; a single
malformed training row must not abort fitting for the rest — skip and count
it, don't silently zero-fill.

## 14. Testing

Python (`services/scoring/tests/`, `pytest`):
- `vi_builder.py`: verified→confidence, unverified→0.1, category averaging,
  null-category → "uncategorized" bucket.
- `split.py`: assignment is deterministic for a given seed; re-running on
  already-assigned IDs is a no-op (idempotency, brief Section 12).
- `weight_fitting.py`: fit against `fake_data.py`'s known-formula dataset,
  assert recovered weights are close to the known coefficients; assert all
  weights are non-negative even when the unconstrained regression would
  produce a negative one.
- `wvr_calculator.py`: formula correctness against fixed weights/Vi's.
- `validation.py` / `inter_rater.py`: Spearman/MAE/alpha against hand-
  computed expected values on small fixed lists.
- `app.py`: route contract tests mirroring Modules 1/2's `test_app.py`
  pattern (missing fields → 400, service exception → structured 500,
  missing API key → 401 when configured).

Node (`server/src`, `node:test`): any pure logic extracted (cache-freshness
style helpers, if this module ends up needing one) — no automated test for
the controller/model themselves, matching the established precedent for
thin I/O-orchestration code in this codebase.

## 15. Milestones

1. `fake_data.py` + `vi_builder.py` — synthetic dataset generation and Vi
   combination, tested.
2. `split.py` — train/test assignment, idempotency tested.
3. `weight_fitting.py` + `wvr_calculator.py` — fit against synthetic data,
   recover known coefficients, non-negativity enforced.
4. `validation.py` + `inter_rater.py` — stats against hand-computed
   expected values.
5. `app.py` wired up; full Python test suite passing.
6. Node integration: five new tables, models, `scoringController.js`'s
   admin-only `fit-weights` endpoint, wired end-to-end against real
   Module 1/2 data joined with a synthetic `expert_scores` seed script.
7. **Explicitly not a milestone in this pass:** any real-expert-data run,
   any student/recruiter-facing score display. Tracked as follow-up work
   once expert-score collection actually happens.
