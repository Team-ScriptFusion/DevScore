import * as ReadinessReport from '../models/ReadinessReport.js';
import { scoreGithub } from './semanticEngine.js';
import { predictTrained } from './scoring.js';

/** Flatten getSkills()'s { byCategory, uncategorized } shape into a plain name list. */
export function flattenSkillNames(skills) {
  return [...Object.values(skills.byCategory || {}).flat(), ...(skills.uncategorized || [])];
}

/**
 * Runs the trained ML models (services/scoring/rf_model.py — DevScore ML
 * Project 3's Linear Regression + tuned Random Forest, plus their ensemble)
 * against the rule-based report's own `counts`, as a secondary,
 * comparison-only signal alongside the primary score. Best-effort: the
 * scoring service being down/erroring must never turn an otherwise-
 * successful readiness report into a failure — it just means no
 * `ml_prediction` this time. See rf_model.py's own caveats (AI-mined proxy
 * labels, n=97) before treating this as more than a stored comparison
 * number.
 */
async function tryPredictTrained(counts) {
  try {
    const result = await predictTrained(counts);
    return {
      predicted_score: result.predicted_score,
      ensemble_score: result.ensemble_score,
      random_forest_tuned_score: result.random_forest_tuned_score,
      model: result.model,
    };
  } catch (err) {
    console.error('[readiness] ML prediction skipped (scoring service unavailable):', err.message);
    return null;
  }
}

/**
 * Runs the semantic_engine job-readiness scoring pipeline in the background
 * (always called detached — never awaited by the caller). Mining failure
 * must never surface as an unhandled rejection or crash the request that
 * triggered it; it just leaves the readiness report in a 'failed' state for
 * the student to see, same as the engine's own "mining failure is not
 * scoring failure" philosophy in engine/pipeline.py.
 *
 * Shared by resumeController (upload-time trigger) and githubController
 * (connect-time trigger, for a student who connects GitHub *after* already
 * having an extracted resume — see githubController's completeGithubConnect).
 */
export async function scoreReadinessInBackground(resume, user, githubUsername, skillNames) {
  try {
    const payload = await scoreGithub({
      github: githubUsername,
      skills: skillNames,
      name: user.first_name ? `${user.first_name} ${user.last_name}`.trim() : undefined,
      resumeName: resume.original_name,
    });

    const mlPrediction = await tryPredictTrained(payload.counts);

    await ReadinessReport.markSuccess(resume.id, {
      score: payload.score,
      band: payload.band,
      report: { ...payload, ml_prediction: mlPrediction },
    });
  } catch (err) {
    console.error('[readiness] scoring failed:', err.message);
    try {
      await ReadinessReport.markFailed(resume.id, err.message);
    } catch (markErr) {
      console.error('[readiness] could not record readiness failure:', markErr.message);
    }
  }
}
