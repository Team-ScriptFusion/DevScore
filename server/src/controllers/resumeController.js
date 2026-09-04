import { supabase } from '../config/db.js';
import * as Resume from '../models/Resume.js';
import * as ReadinessReport from '../models/ReadinessReport.js';
import * as GithubConnection from '../models/GithubConnection.js';
import { parseResumeBuffer } from '../utils/cvParser.js';
import { scoreGithub } from '../utils/semanticEngine.js';
import { isSemanticEngineConfigured } from '../config/env.js';
import { hasAnyApplication } from '../models/JobApplication.js';

const BUCKET = 'resumes';
const MAX_SIZE_BYTES = 5 * 1024 * 1024; // 5MB (FR 20 — size validation)

/** Flatten getSkills()'s { byCategory, uncategorized } shape into a plain name list. */
function flattenSkillNames(skills) {
  return [...Object.values(skills.byCategory || {}).flat(), ...(skills.uncategorized || [])];
}

/**
 * Runs the semantic_engine job-readiness scoring pipeline in the background
 * (detached from the request — see resumeController's uploadResume). Mining
 * failure must never surface as an unhandled rejection or crash the upload;
 * it just leaves the readiness report in a 'failed' state for the student to
 * see, same as the engine's own "mining failure is not scoring failure"
 * philosophy in engine/pipeline.py.
 */
async function scoreReadinessInBackground(resume, user, githubUsername, skillNames) {
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
    console.error('[resume] readiness scoring failed:', err.message);
    try {
      await ReadinessReport.markFailed(resume.id, err.message);
    } catch (markErr) {
      console.error('[resume] could not record readiness failure:', markErr.message);
    }
  }
}

/** Report the current student's resume + skill-extraction status (FR 28-32). */
export async function resumeStatus(req, res, next) {
  try {
    const resume = await Resume.findByUserId(req.user.id);
    if (!resume) {
      return res.json({
        uploaded: false,
        filename: null,
        sizeBytes: null,
        uploadedAt: null,
        skills: { status: null, byCategory: null, uncategorized: null, extractedAt: null },
        readiness: null,
      });
    }

    const skills = await Resume.getSkills(resume.id);
    const readiness = ReadinessReport.toPublicReadinessReport(
      await ReadinessReport.findByResumeId(resume.id),
    );
    res.json({
      uploaded: true,
      filename: resume.original_name,
      sizeBytes: resume.size_bytes,
      uploadedAt: resume.uploaded_at,
      skills: {
        status: resume.extraction_status,
        byCategory: skills.byCategory,
        uncategorized: skills.uncategorized,
        extractedAt: resume.extracted_at,
      },
      readiness,
    });
  } catch (err) {
    next(err);
  }
}

/**
 * Upload (or replace) the student's resume (FR 19-27). Stored at a fixed
 * per-user path in the private 'resumes' bucket, so re-uploading naturally
 * overwrites the previous file — matching the "replace + re-parse" FRs.
 */
export async function uploadResume(req, res, next) {
  try {
    const file = req.file;
    if (!file) {
      return res.status(400).json({ error: 'No file was uploaded' });
    }
    if (file.mimetype !== 'application/pdf') {
      return res.status(400).json({ error: 'Only PDF resumes are accepted' });
    }
    if (file.size > MAX_SIZE_BYTES) {
      return res.status(400).json({ error: 'Resume must be 5MB or smaller' });
    }

    // A student must select a job role before uploading evidence for it. Fail
    // open (allow) only if the check itself errors — e.g. job_applications
    // hasn't been migrated yet — so an unrelated infra gap doesn't brick
    // uploads; a real "you haven't applied" always blocks.
    try {
      if (!(await hasAnyApplication(req.user.id))) {
        return res.status(400).json({ error: 'Select a job role before uploading a resume' });
      }
    } catch (checkErr) {
      console.error('[resume] could not verify a job application before upload:', checkErr.message);
    }

    const storagePath = `${req.user.id}/resume.pdf`;
    const { error: uploadError } = await supabase.storage
      .from(BUCKET)
      .upload(storagePath, file.buffer, {
        contentType: 'application/pdf',
        upsert: true,
      });
    if (uploadError) {
      return res.status(502).json({ error: 'Could not store the resume. Please try again.' });
    }

    let resume = await Resume.upsert(req.user.id, {
      originalName: file.originalname,
      storagePath,
      sizeBytes: file.size,
    });

    // FR 28-32 — parse immediately after upload. The parser is a fast
    // regex scan (no ML inference), so this stays inline with the upload
    // request rather than needing a background job/polling. A parser
    // failure (service down, bad PDF, etc.) doesn't fail the upload itself
    // — the resume is already safely stored either way.
    try {
      const parsed = await parseResumeBuffer(file.buffer, file.originalname);
      // parse_resume()'s status values ('success' | 'success_no_skills_found'
      // | 'failed') already match the DB check constraint 1:1.
      resume = await Resume.setExtraction(resume.id, {
        status: parsed.status,
        byCategory: parsed.skills || null,
        uncategorized: parsed.uncategorized_terms_found || null,
      });
    } catch {
      resume = await Resume.setExtraction(resume.id, { status: 'failed' });
    }

    const skills = await Resume.getSkills(resume.id);
    const skillNames = flattenSkillNames(skills);

    // Trigger job-readiness scoring (semantic_engine) in the background —
    // never awaited here. Scoring takes tens of seconds and up to ~100
    // GitHub calls (semantic_engine/service/app.py), far past what an
    // upload request should block on; the student polls /resume/status for
    // the result, same as they already do for skill extraction.
    let readiness = null;
    if (isSemanticEngineConfigured && skillNames.length > 0) {
      try {
        const connection = await GithubConnection.findByUserId(req.user.id);
        if (connection) {
          await ReadinessReport.markPending(resume.id);
          readiness = ReadinessReport.toPublicReadinessReport(
            await ReadinessReport.findByResumeId(resume.id),
          );
          scoreReadinessInBackground(resume, req.user, connection.username, skillNames);
        }
      } catch (err) {
        console.error('[resume] could not start readiness scoring:', err.message);
      }
    }

    res.status(201).json({
      uploaded: true,
      filename: resume.original_name,
      sizeBytes: resume.size_bytes,
      uploadedAt: resume.uploaded_at,
      skills: {
        status: resume.extraction_status,
        byCategory: skills.byCategory,
        uncategorized: skills.uncategorized,
        extractedAt: resume.extracted_at,
      },
      readiness,
    });
  } catch (err) {
    next(err);
  }
}
