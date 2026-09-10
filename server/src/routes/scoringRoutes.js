import { Router } from 'express';
import { requireAuth, requireRole } from '../middleware/auth.js';
import {
  runAssignSplit,
  runFitWeights,
  runPredictTrained,
  runValidate,
} from '../controllers/scoringController.js';

const router = Router();

// Admin-only in this pass — no student/recruiter endpoint yet (design spec §2).
router.post('/assign-split', requireAuth, requireRole('admin'), runAssignSplit);
router.post('/fit-weights', requireAuth, requireRole('admin'), runFitWeights);
router.post('/validate', requireAuth, requireRole('admin'), runValidate);
// Trained RandomForestRegressor, sourced from real semantic_engine readiness_reports.
router.post('/predict-trained', requireAuth, requireRole('admin'), runPredictTrained);

export default router;
