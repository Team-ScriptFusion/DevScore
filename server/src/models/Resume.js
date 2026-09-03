import { supabase } from '../config/db.js';
import { findOrCreateByName } from './Skill.js';

/**
 * A student's current resume (FR 19-27) plus its extracted skills (FR
 * 28-32, SDS "Skill" entity). One resume row per user; skills live in the
 * resume_skills junction table, joined to the shared skills catalog.
 */

/** Reshape flat resume_skills+skills join rows into the API's grouped shape. */
function shapeSkillRows(rows) {
  const byCategory = {};
  const uncategorized = [];
  for (const row of rows) {
    const { name, category } = row.skills;
    if (category) {
      (byCategory[category] ||= []).push(name);
    } else {
      uncategorized.push(name);
    }
  }
  for (const category of Object.keys(byCategory)) byCategory[category].sort();
  uncategorized.sort();
  return {
    byCategory: Object.keys(byCategory).length ? byCategory : null,
    uncategorized,
  };
}

/** Fetch a user's resume row (no skills), or null if none uploaded. */
export async function findByUserId(userId) {
  const { data, error } = await supabase
    .from('resumes')
    .select('*')
    .eq('user_id', userId)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

/** Fetch resume rows for many users at once (recruiter candidate list). */
export async function findByUserIds(userIds) {
  if (userIds.length === 0) return [];
  const { data, error } = await supabase
    .from('resumes')
    .select('*')
    .in('user_id', userIds);
  if (error) throw new Error(error.message);
  return data;
}

/** Fetch a resume's extracted skills, shaped as { byCategory, uncategorized }. */
export async function getSkills(resumeId) {
  const { data, error } = await supabase
    .from('resume_skills')
    .select('skills(name, category)')
    .eq('resume_id', resumeId);
  if (error) throw new Error(error.message);
  return shapeSkillRows(data);
}

/** Fetch extracted skills for many resumes at once, keyed by resume_id. */
export async function getSkillsForResumes(resumeIds) {
  if (resumeIds.length === 0) return {};
  const { data, error } = await supabase
    .from('resume_skills')
    .select('resume_id, skills(name, category)')
    .in('resume_id', resumeIds);
  if (error) throw new Error(error.message);

  const byResume = {};
  for (const row of data) {
    (byResume[row.resume_id] ||= []).push(row);
  }
  const result = {};
  for (const resumeId of resumeIds) {
    result[resumeId] = shapeSkillRows(byResume[resumeId] || []);
  }
  return result;
}

/** Upload (or replace) a student's resume. Stable row per user (upsert on user_id). */
export async function upsert(userId, { originalName, storagePath, sizeBytes }) {
  const { data, error } = await supabase
    .from('resumes')
    .upsert(
      {
        user_id: userId,
        original_name: originalName,
        storage_path: storagePath,
        size_bytes: sizeBytes,
        uploaded_at: new Date().toISOString(),
        extraction_status: null,
        extracted_at: null,
      },
      { onConflict: 'user_id' },
    )
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

/**
 * Record the outcome of skill extraction for a resume (FR 28-32). Replaces
 * any previously extracted skills for this resume (re-upload = re-parse).
 * `byCategory` is parse_resume()'s shape: { "language": ["Python", ...] }.
 */
export async function setExtraction(resumeId, { status, byCategory = null, uncategorized = null }) {
  const { error: deleteError } = await supabase
    .from('resume_skills')
    .delete()
    .eq('resume_id', resumeId);
  if (deleteError) throw new Error(deleteError.message);

  if (byCategory) {
    for (const [category, names] of Object.entries(byCategory)) {
      for (const name of names) {
        const skill = await findOrCreateByName(name, category);
        const { error } = await supabase
          .from('resume_skills')
          .upsert(
            { resume_id: resumeId, skill_id: skill.id, from_dictionary_scan: true },
            { onConflict: 'resume_id,skill_id' },
          );
        if (error) throw new Error(error.message);
      }
    }
  }

  if (uncategorized) {
    for (const name of uncategorized) {
      const skill = await findOrCreateByName(name, null);
      const { error } = await supabase
        .from('resume_skills')
        .upsert(
          { resume_id: resumeId, skill_id: skill.id, from_skills_section: true },
          { onConflict: 'resume_id,skill_id' },
        );
      if (error) throw new Error(error.message);
    }
  }

  const { data, error } = await supabase
    .from('resumes')
    .update({ extraction_status: status, extracted_at: new Date().toISOString() })
    .eq('id', resumeId)
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}
