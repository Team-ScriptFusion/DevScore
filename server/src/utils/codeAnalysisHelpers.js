const CACHE_TTL_MS = 24 * 60 * 60 * 1000;

/** True if `analyzedAt` is within the 24h cache window. */
export function isCacheFresh(analyzedAt, now = Date.now()) {
  if (!analyzedAt) return false;
  return now - new Date(analyzedAt).getTime() < CACHE_TTL_MS;
}
