import { ROLES } from '../models/User.js';
import { findActiveByUserAndProvider } from '../models/OAuthSession.js';
import { decryptToken } from '../utils/secureToken.js';
import * as GithubConnection from '../models/GithubConnection.js';
import * as Resume from '../models/Resume.js';
import * as GithubEvidence from '../models/GithubEvidence.js';
import * as SkillVerification from '../models/SkillVerification.js';
import { fetchGithubEvidence, matchSkills } from '../utils/skillVerification.js';
import { isCacheFresh, buildNotConnectedResults } from '../utils/skillVerificationHelpers.js';
import { findOwnedCandidate } from '../utils/candidateOwnership.js';

/** Resolves which student a request targets; recruiters must own the candidate. */
async function resolveStudentId(req, studentIdInput) {
  if (req.user.role === ROLES.STUDENT) return req.user.id;
  if (req.user.role === ROLES.RECRUITER) {
    if (!studentIdInput) return null;
    const candidate = await findOwnedCandidate(req.user.id, studentIdInput);
    return candidate ? candidate.id : null;
  }
  return null;
}

/** A 502 for the Node error handler to surface when the Python service is unreachable or errors. */
function serviceUnavailableError() {
  const err = new Error('skill_verification_service_unavailable');
  err.status = 502;
  err.expose = true;
  return err;
}

/** Writes every claimed skill as github_not_connected and responds. */
async function respondNotConnected(res, studentId) {
  const resume = await Resume.findByUserId(studentId);
  const skillRows = resume ? await Resume.getSkillRows(resume.id) : [];
  const persisted = buildNotConnectedResults(skillRows);
  await SkillVerification.replaceForUser(studentId, persisted);

  return res.json({
    status: 'completed',
    skills_verified: 0,
    skills_unverified: persisted.length,
    results: skillRows.map((s) => ({
      claimed_skill: s.name,
      verified: false,
      method: 'unverified',
      confidence: null,
      reason: 'github_not_connected',
    })),
  });
}

/** Runs the fetch (if needed) + match pipeline for one student and persists results. */
export async function runVerification(req, res, next) {
  try {
    const studentId = await resolveStudentId(req, req.body?.studentId);
    if (!studentId) {
      return res.status(404).json({ error: 'Candidate not found' });
    }

    const [connection, session] = await Promise.all([
      GithubConnection.findByUserId(studentId),
      findActiveByUserAndProvider(studentId, 'github'),
    ]);
    if (!connection || !session) {
      return respondNotConnected(res, studentId);
    }

    const force = req.query?.force === '1';
    const latestFetch = await GithubEvidence.latestFetchedAt(studentId);

    let evidenceRows;
    if (!force && isCacheFresh(latestFetch)) {
      evidenceRows = await GithubEvidence.findByUserId(studentId);
    } else {
      const accessToken = decryptToken(session.encrypted_access_token);
      let fetchResult;
      try {
        fetchResult = await fetchGithubEvidence(connection.username, accessToken);
      } catch (err) {
        if (err.message === 'invalid_github_token') {
          return respondNotConnected(res, studentId);
        }
        return next(serviceUnavailableError());
      }
      evidenceRows = await GithubEvidence.replaceForUser(studentId, fetchResult.repos);
    }

    const resume = await Resume.findByUserId(studentId);
    const skillRows = resume ? await Resume.getSkillRows(resume.id) : [];
    if (skillRows.length === 0) {
      await SkillVerification.replaceForUser(studentId, []);
      return res.json({ status: 'completed', skills_verified: 0, skills_unverified: 0, results: [] });
    }

    const evidenceForMatching = evidenceRows.map((row) => ({
      name: row.repo_name,
      is_fork: row.is_fork,
      languages: row.languages,
      readme_text: row.readme_text,
      pushed_at: row.last_pushed_at,
    }));

    let matchResults;
    try {
      matchResults = await matchSkills(skillRows.map((s) => s.name), evidenceForMatching);
    } catch {
      return next(serviceUnavailableError());
    }

    const evidenceRepoIdByName = Object.fromEntries(evidenceRows.map((r) => [r.repo_name, r.id]));
    const skillIdByName = Object.fromEntries(skillRows.map((s) => [s.name, s.skillId]));
    const persisted = matchResults.map((r) => ({
      skillId: skillIdByName[r.skill],
      verified: r.verified,
      method: r.method,
      confidence: r.confidence,
      evidenceRepoId: r.evidence_repo ? evidenceRepoIdByName[r.evidence_repo] : null,
      reason: r.reason,
    }));
    await SkillVerification.replaceForUser(studentId, persisted);

    res.json({
      status: 'completed',
      skills_verified: matchResults.filter((r) => r.verified).length,
      skills_unverified: matchResults.filter((r) => !r.verified).length,
      results: matchResults,
    });
  } catch (err) {
    next(err);
  }
}

/** Reads stored verification results — no recompute. */
export async function getVerification(req, res, next) {
  try {
    let studentId;
    if (req.user.role === ROLES.STUDENT) {
      if (req.params.studentId !== req.user.id) {
        return res.status(404).json({ error: 'Candidate not found' });
      }
      studentId = req.user.id;
    } else if (req.user.role === ROLES.RECRUITER) {
      const candidate = await findOwnedCandidate(req.user.id, req.params.studentId);
      if (!candidate) return res.status(404).json({ error: 'Candidate not found' });
      studentId = candidate.id;
    } else {
      return res.status(403).json({ error: 'You do not have access to this resource' });
    }

    const results = await SkillVerification.findByUserId(studentId);
    res.json({ results });
  } catch (err) {
    next(err);
  }
}
