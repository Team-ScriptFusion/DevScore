const CACHE_TTL_MS = 24 * 60 * 60 * 1000;

/** True if `fetchedAt` is within the 24h cache window. */
export function isCacheFresh(fetchedAt, now = Date.now()) {
  if (!fetchedAt) return false;
  return now - new Date(fetchedAt).getTime() < CACHE_TTL_MS;
}

/**
 * Builds a github_not_connected verification result for every claimed
 * skill — used when a student has no active GitHub connection at all
 * (the "unverifiable, not unverified" case).
 */
export function buildNotConnectedResults(skillRows) {
  return skillRows.map((row) => ({
    skillId: row.skillId,
    verified: false,
    method: 'unverified',
    confidence: null,
    evidenceRepoId: null,
    reason: 'github_not_connected',
  }));
}
