import { Router } from 'express';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { runAnalysis, getSummary } from '../controllers/codeAnalysisController.js';

const router = Router();

router.post('/run', requireAuth, requireRole('student', 'recruiter'), runAnalysis);
router.get('/:studentId/summary', requireAuth, requireRole('student', 'recruiter'), getSummary);

export default router;
