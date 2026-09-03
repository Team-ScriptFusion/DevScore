import { env } from '../config/env.js';

// The fetch-evidence route can make up to ~60 GitHub API calls (30 repos x
// languages + readme); match cv_parser's timeout pattern but sized for that.
const REQUEST_TIMEOUT_MS = 60_000;

function headers() {
  return {
    'Content-Type': 'application/json',
    ...(env.skillVerification.apiKey ? { 'X-Api-Key': env.skillVerification.apiKey } : {}),
  };
}

/** Calls the skill-verification service's /fetch-evidence route. */
export async function fetchGithubEvidence(username, accessToken) {
  const res = await fetch(`${env.skillVerification.url}/fetch-evidence`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ github_username: username, access_token: accessToken }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (res.status === 401) {
    // The service answers 401 for two unrelated reasons: {"error":"invalid_token"}
    // when GitHub rejected the student's token, and {"error":"unauthorized"} when
    // our own X-Api-Key doesn't match theirs. Only the first is a real GitHub
    // problem; conflating them would let a shared-secret misconfiguration reach
    // respondNotConnected and overwrite every stored verification with
    // verified: false. Anything else must fall through to the 502 path.
    const body = await res.json().catch(() => ({}));
    if (body.error === 'invalid_token') {
      throw new Error('invalid_github_token');
    }
    throw new Error(`skill_verification fetch-evidence responded 401: ${body.error || 'unauthorized'}`);
  }
  if (!res.ok) {
    throw new Error(`skill_verification fetch-evidence responded ${res.status}`);
  }
  return res.json();
}

/** Calls the skill-verification service's /match-skills route. */
export async function matchSkills(claimedSkills, repos) {
  const res = await fetch(`${env.skillVerification.url}/match-skills`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ claimed_skills: claimedSkills, repos }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!res.ok) {
    throw new Error(`skill_verification match-skills responded ${res.status}`);
  }
  return res.json();
}
