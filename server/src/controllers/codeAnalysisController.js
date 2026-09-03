import { ROLES } from '../models/User.js';
import { findActiveByUserAndProvider } from '../models/OAuthSession.js';
import { decryptToken } from '../utils/secureToken.js';
import * as GithubConnection from '../models/GithubConnection.js';
import * as CodeAnalysis from '../models/CodeAnalysis.js';
import { analyzeRepos } from '../utils/codeAnalysis.js';
import { isCacheFresh } from '../utils/codeAnalysisHelpers.js';
import { findOwnedCandidate } from '../utils/candidateOwnership.js';

const MAX_REPOS = 15;
const GITHUB_API = 'https://api.github.com';
const EMPTY_SUMMARY = { avg_complexity_overall: null, total_loc_overall: 0, qualifying_repo_count: 0 };

/** A 502 for the Node error handler to surface when the Python service is unreachable or errors. */
function serviceUnavailableError() {
  const err = new Error('code_analysis_service_unavailable');
  err.status = 502;
  err.expose = true;
  return err;
}

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

/** Fetches up to MAX_REPOS public, non-fork repo names for a GitHub user. */
async function listPublicNonForkRepoNames(username, accessToken) {
  const res = await fetch(
    `${GITHUB_API}/users/${username}/repos?per_page=100&sort=pushed&direction=desc`,
    {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'DevScore-CodeAnalysis',
      },
      signal: AbortSignal.timeout(15_000),
    },
  );
  if (res.status === 401) throw new Error('invalid_github_token');
  if (!res.ok) throw new Error(`github repo list responded ${res.status}`);
  const repos = await res.json();
  return repos
    .filter((r) => !r.private && !r.fork)
    .slice(0, MAX_REPOS)
    .map((r) => r.name);
}

/** Clears any prior results and responds with the empty-analysis shape. */
async function respondEmpty(res, studentId) {
  await CodeAnalysis.replaceForUser(studentId, []);
  await CodeAnalysis.upsertSummary(studentId, EMPTY_SUMMARY);
  return res.json({
    status: 'completed',
    repos_analyzed: 0,
    repos_excluded: 0,
    summary: EMPTY_SUMMARY,
  });
}

/** Runs the fetch + analyze pipeline for one student and persists results. */
export async function runAnalysis(req, res, next) {
  try {
    const studentId = await resolveStudentId(req, req.body?.studentId);
    if (!studentId) {
      return res.status(404).json({ error: 'Candidate not found' });
    }

    const [connection, session] = await Promise.all([
      GithubConnection.findByUserId(studentId),
      findActiveByUserAndProvider(studentId, 'github'),
    ]);
    if (!connection || !session?.encrypted_access_token) {
      return respondEmpty(res, studentId);
    }

    const force = req.user.role === ROLES.STUDENT && req.query?.force === '1';
    const latest = await CodeAnalysis.latestAnalyzedAt(studentId);
    if (!force && isCacheFresh(latest)) {
      const summary = await CodeAnalysis.findSummaryByUserId(studentId);
      return res.json({
        status: 'completed',
        repos_analyzed: null,
        repos_excluded: null,
        summary: summary || EMPTY_SUMMARY,
      });
    }

    const accessToken = decryptToken(session.encrypted_access_token);

    let repoNames;
    try {
      repoNames = await listPublicNonForkRepoNames(connection.username, accessToken);
    } catch (err) {
      if (err.message === 'invalid_github_token') {
        return respondEmpty(res, studentId);
      }
      return next(serviceUnavailableError());
    }

    let result;
    try {
      result = await analyzeRepos(connection.username, accessToken, repoNames);
    } catch (err) {
      if (err.message === 'invalid_github_token') {
        return respondEmpty(res, studentId);
      }
      return next(serviceUnavailableError());
    }

    if (
      repoNames.length > 0 &&
      result.repos.every((r) => r.excluded_reason === 'fetch_failed')
    ) {
      // Every repo failed to fetch/analyze (outage, network loss, or
      // rate-limiting affecting the whole batch) rather than just one bad
      // repo. This must not overwrite previously-good stored results with
      // an all-excluded, null-summary result, nor mark the cache fresh on
      // that empty result — treat it the same as a service failure.
      return next(serviceUnavailableError());
    }

    await CodeAnalysis.replaceForUser(studentId, result.repos);
    await CodeAnalysis.upsertSummary(studentId, result.summary);

    res.json({
      status: 'completed',
      repos_analyzed: result.repos.filter((r) => r.included).length,
      repos_excluded: result.repos.filter((r) => !r.included).length,
      summary: result.summary,
    });
  } catch (err) {
    next(err);
  }
}

/** Reads the stored summary — no recompute. */
export async function getSummary(req, res, next) {
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

    const summary = await CodeAnalysis.findSummaryByUserId(studentId);
    res.json({ summary: summary || null });
  } catch (err) {
    next(err);
  }
}
