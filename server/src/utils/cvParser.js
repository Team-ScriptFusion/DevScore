import { env } from '../config/env.js';

/**
 * Calls the cv_parser microservice (FR 28-32) with a resume buffer and
 * returns its categorized-skills result. Node's global fetch/FormData/Blob
 * (18+) are used directly — no extra HTTP client dependency needed.
 */
export async function parseResumeBuffer(buffer, filename) {
  const body = new FormData();
  body.append('resume', new Blob([buffer], { type: 'application/pdf' }), filename);

  const res = await fetch(`${env.cvParser.url}/parse`, {
    method: 'POST',
    headers: env.cvParser.apiKey ? { 'X-Api-Key': env.cvParser.apiKey } : {},
    body,
  });

  if (!res.ok) {
    throw new Error(`cv_parser responded ${res.status}`);
  }
  return res.json();
}
