import { Router } from 'express';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { runVerification, getVerification } from '../controllers/skillVerificationController.js';

const router = Router();

router.post('/run', requireAuth, requireRole('student', 'recruiter'), runVerification);
router.get('/:studentId', requireAuth, requireRole('student', 'recruiter'), getVerification);

export default router;
