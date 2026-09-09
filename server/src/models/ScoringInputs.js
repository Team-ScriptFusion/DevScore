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
