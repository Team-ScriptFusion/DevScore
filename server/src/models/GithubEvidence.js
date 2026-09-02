import { supabase } from '../config/db.js';

/**
 * Raw per-repo GitHub evidence for a student (Phase 0 output). Replaced
 * wholesale on each re-fetch — see replaceForUser.
 */

/** Fetch stored evidence rows for a user, newest fetch first. */
export async function findByUserId(userId) {
  const { data, error } = await supabase
    .from('github_evidence')
    .select('*')
    .eq('user_id', userId)
    .order('fetched_at', { ascending: false });
  if (error) throw new Error(error.message);
  return data;
}

/** The most recent fetched_at for a user, or null if never fetched. */
export async function latestFetchedAt(userId) {
  const { data, error } = await supabase
    .from('github_evidence')
    .select('fetched_at')
    .eq('user_id', userId)
    .order('fetched_at', { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data?.fetched_at || null;
}

/**
 * Replace all evidence rows for a user with a fresh fetch result. `repos`
 * is the skill-verification service's /fetch-evidence "repos" array shape:
 * [{ name, is_fork, languages, readme_text, pushed_at }].
 */
export async function replaceForUser(userId, repos) {
  const { error: deleteError } = await supabase
    .from('github_evidence')
    .delete()
    .eq('user_id', userId);
  if (deleteError) throw new Error(deleteError.message);

  if (repos.length === 0) return [];

  const rows = repos.map((repo) => ({
    user_id: userId,
    repo_name: repo.name,
    is_fork: repo.is_fork,
    languages: repo.languages,
    readme_text: repo.readme_text,
    last_pushed_at: repo.pushed_at,
  }));
  const { data, error } = await supabase.from('github_evidence').insert(rows).select();
  if (error) throw new Error(error.message);
  return data;
}
