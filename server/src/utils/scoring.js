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

/**
 * Calls the scoring service's /predict-trained route — a real trained
 * RandomForestRegressor (see services/scoring/rf_model.py), distinct from
 * /fit-weights' synthetic-data nnls pass. `counts` is a ReadinessReport's
 * `counts` block (claimed/verified/weakly_verified/unverified), already
 * produced by semantic_engine for every scored resume.
 */
export function predictTrained(counts) {
  return post('/predict-trained', { counts });
}
