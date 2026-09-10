import * as ScoringInputs from '../models/ScoringInputs.js';
import * as ScoringResults from '../models/ScoringResults.js';
import { findByResumeId } from '../models/ReadinessReport.js';
import { assignSplit, buildVi, fitWeights, predictTrained, validateWeights } from '../utils/scoring.js';

const DEFAULT_TRAIN_FRACTION = 0.7;

/** A 502 for the Node error handler to surface when the Python service is unreachable or errors. */
function serviceUnavailableError() {
  const err = new Error('scoring_service_unavailable');
  err.status = 502;
  err.expose = true;
  return err;
}

/** Min/max of avg_complexity_overall/total_loc_overall across a set of summaries, for vi_builder normalization. */
function rangeHintFrom(summaries) {
  const complexities = summaries.map((s) => s?.avg_complexity_overall).filter((v) => v != null);
  const locs = summaries.map((s) => s?.total_loc_overall).filter((v) => v != null);
  return {
    complexity_min: complexities.length ? Math.min(...complexities) : 0,
    complexity_max: complexities.length ? Math.max(...complexities) : 0,
    loc_min: locs.length ? Math.min(...locs) : 0,
    loc_max: locs.length ? Math.max(...locs) : 0,
  };
}

/** Admin-only: assigns any not-yet-split scored students into train/test groups. */
export async function runAssignSplit(req, res, next) {
  try {
    const trainFraction = req.body?.trainFraction ?? DEFAULT_TRAIN_FRACTION;
    const seed = req.body?.seed ?? 42;

    const [existing, allUserIds] = await Promise.all([
      ScoringInputs.getSplitAssignments(),
      ScoringInputs.listExpertScoredUserIds(),
    ]);
    if (allUserIds.length === 0) {
      return res.status(400).json({ error: 'No students with expert scores to split' });
    }

    let assignments;
    try {
      assignments = await assignSplit(allUserIds, trainFraction, seed, existing);
    } catch {
      return next(serviceUnavailableError());
    }

    await ScoringInputs.saveSplitAssignments(assignments);
    res.json({ status: 'completed', assignments });
  } catch (err) {
    next(err);
  }
}

/** Admin-only: fits weights on the current training split and freezes them under weightsVersion. */
export async function runFitWeights(req, res, next) {
  try {
    const weightsVersion = req.body?.weightsVersion;
    const categories = req.body?.categories;
    if (!weightsVersion || !Array.isArray(categories) || categories.length === 0) {
      return res.status(400).json({ error: 'weightsVersion and categories are required' });
    }

    const split = await ScoringInputs.getSplitAssignments();
    const trainUserIds = Object.entries(split)
      .filter(([, group]) => group === 'train')
      .map(([userId]) => userId);
    if (trainUserIds.length === 0) {
      return res.status(400).json({ error: 'No training-split students assigned yet' });
    }

    const [skillRowsByUser, summaryByUser, expertScoreByUser] = await Promise.all([
      ScoringInputs.fetchSkillVerificationForUsers(trainUserIds),
      ScoringInputs.fetchCodeAnalysisSummariesForUsers(trainUserIds),
      ScoringInputs.findExpertScoresByUserIds(trainUserIds),
    ]);
    const rangeHint = rangeHintFrom(Object.values(summaryByUser));
    const scoredUserIds = trainUserIds.filter((userId) => expertScoreByUser[userId] != null);
    if (scoredUserIds.length === 0) {
      return res.status(400).json({ error: 'No training-split students have expert scores yet' });
    }

    let trainingRows;
    try {
      trainingRows = await Promise.all(
        scoredUserIds.map(async (userId) => {
          const vi = await buildVi(skillRowsByUser[userId] || [], summaryByUser[userId] || null, rangeHint);
          return {
            vi_by_category: vi.vi_by_category,
            code_quality_vi: vi.code_quality_vi,
            expert_score: expertScoreByUser[userId],
          };
        }),
      );
    } catch {
      return next(serviceUnavailableError());
    }

    let result;
    try {
      result = await fitWeights(trainingRows, categories, weightsVersion);
    } catch {
      return next(serviceUnavailableError());
    }

    await ScoringResults.saveWeights(weightsVersion, result.weights);
    res.json(result);
  } catch (err) {
    next(err);
  }
}

/** Admin-only: validates a frozen weights_version against the test split's expert scores. */
export async function runValidate(req, res, next) {
  try {
    const weightsVersion = req.body?.weightsVersion;
    if (!weightsVersion) {
      return res.status(400).json({ error: 'weightsVersion is required' });
    }

    const [weights, split] = await Promise.all([
      ScoringResults.findWeights(weightsVersion),
      ScoringInputs.getSplitAssignments(),
    ]);
    if (weights.length === 0) {
      return res.status(404).json({ error: 'Unknown weightsVersion' });
    }

    const testUserIds = Object.entries(split)
      .filter(([, group]) => group === 'test')
      .map(([userId]) => userId);
    const [skillRowsByUser, summaryByUser, expertScoreByUser] = await Promise.all([
      ScoringInputs.fetchSkillVerificationForUsers(testUserIds),
      ScoringInputs.fetchCodeAnalysisSummariesForUsers(testUserIds),
      ScoringInputs.findExpertScoresByUserIds(testUserIds),
    ]);
    const rangeHint = rangeHintFrom(Object.values(summaryByUser));
    const scoredUserIds = testUserIds.filter((userId) => expertScoreByUser[userId] != null);
    if (scoredUserIds.length === 0) {
      return res.status(400).json({ error: 'No test-split students have expert scores yet' });
    }

    let testRows;
    let result;
    try {
      testRows = await Promise.all(
        scoredUserIds.map(async (userId) => {
          const vi = await buildVi(skillRowsByUser[userId] || [], summaryByUser[userId] || null, rangeHint);
          return {
            vi_by_category: vi.vi_by_category,
            code_quality_vi: vi.code_quality_vi,
            expert_score: expertScoreByUser[userId],
          };
        }),
      );
      result = await validateWeights(testRows, weights);
    } catch {
      return next(serviceUnavailableError());
    }

    await ScoringResults.saveValidationResults(weightsVersion, [
      { metric_name: 'spearman_rho', metric_value: result.spearman_rho, sample_size: result.sample_size },
      { metric_name: 'mae', metric_value: result.mae, sample_size: result.sample_size },
    ]);
    res.json(result);
  } catch (err) {
    next(err);
  }
}

/**
 * Admin-only: runs the trained models (rf_model.py, DevScore ML Project 3 —
 * Linear Regression + tuned Random Forest, plus their ensemble) against one
 * resume's already-computed semantic_engine readiness report, for
 * comparison against the primary rule-based score. Sourced directly from
 * `readiness_reports` (real, live data) — not the skill_verification/
 * code_analysis_summary tables the rest of this controller uses, which
 * don't exist on master (see rf_model.py's own caveats before citing any of
 * these as a validated result). `predictedScore` (Linear Regression) is the
 * project's chosen production number; `ensembleScore`/`randomForestScore`
 * are reported comparison signals, not the headline.
 */
export async function runPredictTrained(req, res, next) {
  try {
    const resumeId = req.body?.resumeId;
    if (!resumeId) {
      return res.status(400).json({ error: 'resumeId is required' });
    }

    const readinessRow = await findByResumeId(resumeId);
    if (!readinessRow || readinessRow.status !== 'success' || !readinessRow.report) {
      return res.status(404).json({ error: 'No completed readiness report for this resume' });
    }

    let result;
    try {
      result = await predictTrained(readinessRow.report.counts || {});
    } catch {
      return next(serviceUnavailableError());
    }

    res.json({
      resumeId,
      actualScore: readinessRow.score,
      predictedScore: result.predicted_score,
      ensembleScore: result.ensemble_score,
      randomForestScore: result.random_forest_tuned_score,
      features: result.features,
      model: result.model,
    });
  } catch (err) {
    next(err);
  }
}
