import { supabase } from '../config/db.js';

/**
 * Per-repo structural complexity metrics and their per-student rollup
 * (AST-based code analysis module). Both tables are replaced wholesale
 * on each re-run — see replaceForUser/upsertSummary.
 */

/** Fetch stored per-repo results for a user, newest analysis first. */
export async function findByUserId(userId) {
  const { data, error } = await supabase
    .from('code_analysis')
    .select('*')
    .eq('user_id', userId)
    .order('analyzed_at', { ascending: false });
  if (error) throw new Error(error.message);
  return data;
}

/** Fetch the stored summary row for a user, or null if never computed. */
export async function findSummaryByUserId(userId) {
  const { data, error } = await supabase
    .from('code_analysis_summary')
    .select('*')
    .eq('user_id', userId)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

/** The most recent analyzed_at for a user, or null if never analyzed. */
export async function latestAnalyzedAt(userId) {
  const { data, error } = await supabase
    .from('code_analysis')
    .select('analyzed_at')
    .eq('user_id', userId)
    .order('analyzed_at', { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data?.analyzed_at || null;
}

/**
 * Replace all per-repo results for a user with a fresh analysis result.
 * `repoResults` is the code-analysis service's /analyze-repos "repos"
 * array shape: [{ repo_name, included, excluded_reason, language,
 * avg_cyclomatic_complexity, total_functions, total_lines,
 * max_nesting_depth }].
 */
export async function replaceForUser(userId, repoResults) {
  const { error: deleteError } = await supabase
    .from('code_analysis')
    .delete()
    .eq('user_id', userId);
  if (deleteError) throw new Error(deleteError.message);

  if (repoResults.length === 0) return [];

  const rows = repoResults.map((r) => ({
    user_id: userId,
    repo_name: r.repo_name,
    language: r.language,
    avg_cyclomatic_complexity: r.avg_cyclomatic_complexity,
    total_functions: r.total_functions,
    total_lines: r.total_lines,
    max_nesting_depth: r.max_nesting_depth,
    included: r.included,
    excluded_reason: r.excluded_reason,
  }));
  const { data, error } = await supabase.from('code_analysis').insert(rows).select();
  if (error) throw new Error(error.message);
  return data;
}

/**
 * Upsert the per-student summary row. `summary` is the code-analysis
 * service's already-computed { avg_complexity_overall, total_loc_overall,
 * qualifying_repo_count } object — stored as-is, never recomputed here.
 */
export async function upsertSummary(userId, summary) {
  const { data, error } = await supabase
    .from('code_analysis_summary')
    .upsert(
      {
        user_id: userId,
        avg_complexity_overall: summary.avg_complexity_overall,
        total_loc_overall: summary.total_loc_overall,
        qualifying_repo_count: summary.qualifying_repo_count,
        computed_at: new Date().toISOString(),
      },
      { onConflict: 'user_id' },
    )
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}
