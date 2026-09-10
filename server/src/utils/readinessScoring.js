import * as ReadinessReport from '../models/ReadinessReport.js';
import { scoreGithub } from './semanticEngine.js';

/** Flatten getSkills()'s { byCategory, uncategorized } shape into a plain name list. */
export function flattenSkillNames(skills) {
  return [...Object.values(skills.byCategory || {}).flat(), ...(skills.uncategorized || [])];
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
    await ReadinessReport.markSuccess(resume.id, {
      score: payload.score,
      band: payload.band,
      report: payload,
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
