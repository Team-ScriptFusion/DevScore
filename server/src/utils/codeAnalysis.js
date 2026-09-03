import { env } from '../config/env.js';

// Sized against the Python service's real worst case, not a guess: it
// processes up to 15 repos strictly sequentially, and each repo's network
// budget alone is a 15s metadata fetch plus a 30s tarball download
// (repo_fetch.py's timeout=15 / timeout=30) — 15 x 45s = 675s before any
// extraction or lizard time is counted. 15 minutes leaves margin for that
// CPU work plus general overhead. Timing out short is expensive here:
// nothing is persisted on that path, so analyzed_at stays stale, the 24h
// cache never goes fresh, and every retry repeats the whole sequence.
const REQUEST_TIMEOUT_MS = 900_000;

function headers() {
  return {
    'Content-Type': 'application/json',
    ...(env.codeAnalysis.apiKey ? { 'X-Api-Key': env.codeAnalysis.apiKey } : {}),
  };
}

/** Calls the code-analysis service's /analyze-repos route. */
export async function analyzeRepos(username, accessToken, repoNames) {
  const res = await fetch(`${env.codeAnalysis.url}/analyze-repos`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({
      github_username: username,
      access_token: accessToken,
      repo_names: repoNames,
    }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (res.status === 401) {
    const body = await res.json().catch(() => ({}));
    if (body.error === 'invalid_token') {
      throw new Error('invalid_github_token');
    }
    throw new Error(`code_analysis analyze-repos responded 401: ${body.error || 'unauthorized'}`);
  }
  if (!res.ok) {
    throw new Error(`code_analysis analyze-repos responded ${res.status}`);
  }
  return res.json();
}
