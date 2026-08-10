import { Router } from 'express';
import multer from 'multer';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { resumeStatus, uploadResume } from '../controllers/resumeController.js';

// Buffered in memory (resumes are small, capped well below Node's default
// body limits) and streamed straight to Supabase Storage — no temp files on disk.
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 5 * 1024 * 1024 },
});

const router = Router();

router.get('/status', requireAuth, requireRole('student'), resumeStatus);
router.post(
  '/upload',
  requireAuth,
  requireRole('student'),
  upload.single('resume'),
  uploadResume,
);

export default router;
