import { supabase } from '../config/db.js';

/**
 * Output of the semantic_engine scoring pipeline for a student's current
 * resume + linked GitHub account (see server/supabase/schema.sql). One row
 * per resume; re-scoring on re-upload overwrites it.
 */

/** Map a DB row to the shape the client expects, or null if never scored. */
export function toPublicReadinessReport(row) {
  if (!row) return null;
  return {
    status: row.status,
    score: row.score,
    band: row.band,
    requestedAt: row.requested_at,
    completedAt: row.completed_at,
  };
}

/** Fetch the readiness report for one resume, or null if scoring was never started. */
export async function findByResumeId(resumeId) {
  const { data, error } = await supabase
    .from('readiness_reports')
    .select('*')
    .eq('resume_id', resumeId)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

/** Fetch readiness reports for many resumes at once, keyed by resume_id. */
export async function findByResumeIds(resumeIds) {
  if (resumeIds.length === 0) return {};
  const { data, error } = await supabase
    .from('readiness_reports')
    .select('*')
    .in('resume_id', resumeIds);
  if (error) throw new Error(error.message);
  return Object.fromEntries(data.map((row) => [row.resume_id, row]));
}

/** Mark scoring as started (or restarted, on re-upload) for a resume. */
export async function markPending(resumeId) {
  const { error } = await supabase.from('readiness_reports').upsert(
    {
      resume_id: resumeId,
      status: 'pending',
      score: null,
      band: null,
      report: null,
      error: null,
      requested_at: new Date().toISOString(),
      completed_at: null,
    },
    { onConflict: 'resume_id' },
  );
  if (error) throw new Error(error.message);
}

/** Record a completed score for a resume. */
export async function markSuccess(resumeId, { score, band, report }) {
  const { error } = await supabase
    .from('readiness_reports')
    .update({ status: 'success', score, band, report, error: null, completed_at: new Date().toISOString() })
    .eq('resume_id', resumeId);
  if (error) throw new Error(error.message);
}

/** Record a failed scoring attempt for a resume (engine down, GitHub unreachable, etc). */
export async function markFailed(resumeId, errorMessage) {
  const { error } = await supabase
    .from('readiness_reports')
    .update({ status: 'failed', error: errorMessage, completed_at: new Date().toISOString() })
    .eq('resume_id', resumeId);
  if (error) throw new Error(error.message);
}
