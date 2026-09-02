import { env } from '../config/env.js';

// Tarball download + extraction + lizard across up to 15 repos is heavier
// than either cv_parser's single-PDF parse or skill_verification's
// metadata-only fetch — sized accordingly.
const REQUEST_TIMEOUT_MS = 90_000;

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
    throw new Error('invalid_github_token');
  }
  if (!res.ok) {
    throw new Error(`code_analysis analyze-repos responded ${res.status}`);
  }
  return res.json();
}
