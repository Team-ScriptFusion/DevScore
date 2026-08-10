import { supabase } from '../config/db.js';
import { setResumeInfo } from '../models/User.js';

const BUCKET = 'resumes';
const MAX_SIZE_BYTES = 5 * 1024 * 1024; // 5MB (FR 20 — size validation)

/**
 * Report the current student's resume status (FR 28-32 "extraction status
 * display", scoped here to upload state — parsing is a later phase).
 */
export async function resumeStatus(req, res) {
  res.json({
    uploaded: Boolean(req.user.resume_storage_path),
    filename: req.user.resume_original_name || null,
    sizeBytes: req.user.resume_size_bytes || null,
    uploadedAt: req.user.resume_uploaded_at || null,
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

    const user = await setResumeInfo(req.user.id, {
      originalName: file.originalname,
      storagePath,
      sizeBytes: file.size,
    });

    res.status(201).json({
      uploaded: true,
      filename: user.resume_original_name,
      sizeBytes: user.resume_size_bytes,
      uploadedAt: user.resume_uploaded_at,
    });
  } catch (err) {
    next(err);
  }
}
