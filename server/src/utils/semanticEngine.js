import { env } from '../config/env.js';

// Scoring mines up to ~100 GitHub calls per candidate (semantic_engine's own
// docs), so this runs well past cvParser's 45s budget — but it's always
// called from a detached background task (never inline in a request), so a
// longer wait here costs nothing user-facing. Give this comfortably more
// headroom than the engine service's own gunicorn --timeout (see
// deploy/aws/systemd/semantic-engine.service / Render start command) so
// Node never gives up before the engine would have legitimately finished.
const REQUEST_TIMEOUT_MS = 150_000;

/**
 * Calls the semantic_engine microservice's POST /score-github — scores an
 * already-extracted skill list against a GitHub profile, so we never need to
 * re-upload/re-parse the PDF (Node already has the skills from cvParser).
 */
export async function scoreGithub({ github, skills, name, resumeName }) {
  const res = await fetch(`${env.engine.url}/score-github`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(env.engine.apiKey ? { 'X-Api-Key': env.engine.apiKey } : {}),
    },
    body: JSON.stringify({ github, skills, name, resume_name: resumeName }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });

  if (!res.ok) {
    throw new Error(`semantic_engine responded ${res.status}`);
  }
  return res.json();
}
