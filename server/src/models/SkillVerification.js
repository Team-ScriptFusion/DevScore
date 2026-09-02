import { supabase } from '../config/db.js';

/** Reshape a skill_verification+skills join row into the API's flat shape. */
function toPublic(row) {
  return {
    skill: row.skills.name,
    verified: row.verified,
    method: row.method,
    confidence: row.confidence,
    // The repo name behind the match, so this read path exposes the same
    // per-skill fields the run path does. Null when no evidence row is
    // linked, or when the linked one was cleared by a later re-fetch.
    evidenceRepo: row.github_evidence?.repo_name ?? null,
    reason: row.reason,
    computedAt: row.computed_at,
  };
}

/** Fetch stored verification results for a user, joined to skill names. */
export async function findByUserId(userId) {
  const { data, error } = await supabase
    .from('skill_verification')
    .select(
      'verified, method, confidence, reason, computed_at, skills(name, category), github_evidence(repo_name)',
    )
    .eq('user_id', userId);
  if (error) throw new Error(error.message);
  return data.map(toPublic);
}

/**
 * Replace all verification rows for a user with a fresh result set.
 * `results` items: { skillId, verified, method, confidence, evidenceRepoId, reason }.
 */
export async function replaceForUser(userId, results) {
  const { error: deleteError } = await supabase
    .from('skill_verification')
    .delete()
    .eq('user_id', userId);
  if (deleteError) throw new Error(deleteError.message);

  if (results.length === 0) return [];

  const rows = results.map((r) => ({
    user_id: userId,
    skill_id: r.skillId,
    verified: r.verified,
    method: r.method,
    confidence: r.confidence,
    evidence_repo_id: r.evidenceRepoId || null,
    reason: r.reason || null,
  }));
  const { data, error } = await supabase.from('skill_verification').insert(rows).select();
  if (error) throw new Error(error.message);
  return data;
}
