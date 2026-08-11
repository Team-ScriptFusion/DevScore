import { supabase } from '../config/db.js';

/**
 * User data-access module — Member 1 database ownership (Users; OAuth sessions).
 * Backed by the Supabase `users` table (see server/supabase/schema.sql).
 */

/** Roles enforced across the system (SRS §1.1.1 primary actors). */
export const ROLES = Object.freeze({
  STUDENT: 'student',
  RECRUITER: 'recruiter',
  ADMIN: 'admin',
});

/** Map a DB row (snake_case) to the public shape returned to the client. */
export function toPublicUser(row) {
  return {
    id: row.id,
    email: row.email,
    firstName: row.first_name,
    lastName: row.last_name,
    fullName: `${row.first_name} ${row.last_name}`.trim(),
    avatarUrl: row.avatar_url,
    role: row.role,
    createdAt: row.created_at,
    githubUsername: row.github_username || null,
    githubConnectedAt: row.github_connected_at || null,
    resumeFilename: row.resume_original_name || null,
    resumeSizeBytes: row.resume_size_bytes || null,
    resumeUploadedAt: row.resume_uploaded_at || null,
    claimedSkills: row.claimed_skills || null,
    skillsUncategorized: row.skills_uncategorized || null,
    skillsExtractionStatus: row.skills_extraction_status || null,
    skillsExtractedAt: row.skills_extracted_at || null,
  };
}

/** Detect an existing account by provider identity (FR 4/6). */
export async function findByProviderId(provider, oauthId) {
  const { data, error } = await supabase
    .from('users')
    .select('*')
    .eq('oauth_provider', provider)
    .eq('oauth_id', oauthId)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

/** Look up a user by email (local email/password login, and provider account detection). */
export async function findByEmail(email) {
  const { data, error } = await supabase
    .from('users')
    .select('*')
    .eq('email', email.toLowerCase())
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

/** Look up a user by primary key. */
export async function findById(id) {
  const { data, error } = await supabase
    .from('users')
    .select('*')
    .eq('id', id)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

/** Record a student's linked GitHub identity (FR 9/10). */
export async function setGithubProfile(userId, githubUsername) {
  const { data, error } = await supabase
    .from('users')
    .update({
      github_username: githubUsername,
      github_connected_at: new Date().toISOString(),
    })
    .eq('id', userId)
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

/** Clear a student's linked GitHub identity (disconnect). */
export async function clearGithubProfile(userId) {
  const { data, error } = await supabase
    .from('users')
    .update({ github_username: null, github_connected_at: null })
    .eq('id', userId)
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

/** Record a student's uploaded resume (FR 19-27). Re-uploading overwrites these fields. */
export async function setResumeInfo(userId, { originalName, storagePath, sizeBytes }) {
  const { data, error } = await supabase
    .from('users')
    .update({
      resume_original_name: originalName,
      resume_storage_path: storagePath,
      resume_size_bytes: sizeBytes,
      resume_uploaded_at: new Date().toISOString(),
    })
    .eq('id', userId)
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

/** Clear a student's resume record (used if the storage upload fails after a prior success, or on delete). */
export async function clearResumeInfo(userId) {
  const { data, error } = await supabase
    .from('users')
    .update({
      resume_original_name: null,
      resume_storage_path: null,
      resume_size_bytes: null,
      resume_uploaded_at: null,
    })
    .eq('id', userId)
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

/**
 * Record the outcome of skill extraction for a student's resume (FR 28-32).
 * Called once immediately after upload (status 'pending'), then again once
 * the parser responds (or fails) with the final status and results.
 */
export async function setSkillsExtraction(
  userId,
  { status, byCategory = null, uncategorized = null },
) {
  const { data, error } = await supabase
    .from('users')
    .update({
      skills_extraction_status: status,
      claimed_skills: byCategory,
      skills_uncategorized: uncategorized,
      skills_extracted_at: new Date().toISOString(),
    })
    .eq('id', userId)
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

/** Set (or replace) a user's password hash — admin create/reset flows. */
export async function setPasswordHash(userId, passwordHash) {
  const { data, error } = await supabase
    .from('users')
    .update({ password_hash: passwordHash })
    .eq('id', userId)
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

/** List all users of a given role, newest first (admin recruiter management; recruiter candidate list). */
export async function listUsersByRole(role) {
  const { data, error } = await supabase
    .from('users')
    .select('*')
    .eq('role', role)
    .order('created_at', { ascending: false });
  if (error) throw new Error(error.message);
  return data;
}

/** Count users of a given role without fetching rows (dashboard stats). */
export async function countUsersByRole(role) {
  const { count, error } = await supabase
    .from('users')
    .select('id', { count: 'exact', head: true })
    .eq('role', role);
  if (error) throw new Error(error.message);
  return count || 0;
}

/** Delete a user account outright (admin CRUD, FR 47-50). Cascades to oauth_sessions. */
export async function deleteUser(id) {
  const { error } = await supabase.from('users').delete().eq('id', id);
  if (error) throw new Error(error.message);
}

/**
 * Create a new user account (FR 5). Accepts camelCase input. Either
 * (oauthProvider + oauthId) or passwordHash must be supplied — enforced by
 * the users_has_credential check constraint as well.
 */
export async function createUser({
  email,
  firstName = '',
  lastName = '',
  avatarUrl = '',
  role = ROLES.STUDENT,
  oauthProvider = null,
  oauthId = null,
  passwordHash = null,
}) {
  const { data, error } = await supabase
    .from('users')
    .insert({
      email: email.toLowerCase(),
      first_name: firstName,
      last_name: lastName,
      avatar_url: avatarUrl,
      role,
      oauth_provider: oauthProvider,
      oauth_id: oauthId,
      password_hash: passwordHash,
    })
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}
