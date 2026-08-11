import { supabase } from '../config/db.js';
import { setResumeInfo, setSkillsExtraction } from '../models/User.js';
import { parseResumeBuffer } from '../utils/cvParser.js';

const BUCKET = 'resumes';
const MAX_SIZE_BYTES = 5 * 1024 * 1024; // 5MB (FR 20 — size validation)

/** Report the current student's resume + skill-extraction status (FR 28-32). */
export async function resumeStatus(req, res) {
  res.json({
    uploaded: Boolean(req.user.resume_storage_path),
    filename: req.user.resume_original_name || null,
    sizeBytes: req.user.resume_size_bytes || null,
    uploadedAt: req.user.resume_uploaded_at || null,
    skills: {
      status: req.user.skills_extraction_status || null,
      byCategory: req.user.claimed_skills || null,
      uncategorized: req.user.skills_uncategorized || null,
      extractedAt: req.user.skills_extracted_at || null,
    },
  });
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

    let user = await setResumeInfo(req.user.id, {
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
      user = await setSkillsExtraction(req.user.id, {
        status: parsed.status,
        byCategory: parsed.skills || null,
        uncategorized: parsed.uncategorized_terms_found || null,
      });
    } catch {
      user = await setSkillsExtraction(req.user.id, { status: 'failed' });
    }

    res.status(201).json({
      uploaded: true,
      filename: user.resume_original_name,
      sizeBytes: user.resume_size_bytes,
      uploadedAt: user.resume_uploaded_at,
      skills: {
        status: user.skills_extraction_status || null,
        byCategory: user.claimed_skills || null,
        uncategorized: user.skills_uncategorized || null,
        extractedAt: user.skills_extracted_at || null,
      },
    });
  } catch (err) {
    next(err);
  }
}
