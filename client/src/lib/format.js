/**
 * Presentation helpers shared by the dashboards. `initials` was duplicated in
 * three files with three slightly different rules before it landed here.
 */

/** Up to two initials from a display name, falling back to '?'. */
export function initials(name) {
  const parts = String(name || '')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0].toUpperCase());
  return parts.join('') || '?';
}

const TINT_COUNT = 6;

/**
 * Picks one of six avatar tints from the name, so a given person keeps the same
 * colour across sessions and across screens. Purely decorative — the initials
 * carry the identity, the colour only helps the eye track a row.
 */
export function avatarTint(name) {
  const s = String(name || '');
  let hash = 0;
  for (let i = 0; i < s.length; i += 1) {
    hash = (hash * 31 + s.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % TINT_COUNT;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * "3 days ago" style dates. Anything past a month falls back to a real date —
 * "14 months ago" is harder to read than the date itself.
 */
export function relativeDate(input) {
  if (!input) return '—';
  const then = new Date(input);
  if (Number.isNaN(then.getTime())) return '—';

  const diff = Date.now() - then.getTime();
  if (diff < MINUTE) return 'just now';
  if (diff < HOUR) {
    const m = Math.floor(diff / MINUTE);
    return `${m} minute${m === 1 ? '' : 's'} ago`;
  }
  if (diff < DAY) {
    const h = Math.floor(diff / HOUR);
    return `${h} hour${h === 1 ? '' : 's'} ago`;
  }
  if (diff < 30 * DAY) {
    const d = Math.floor(diff / DAY);
    return d === 1 ? 'yesterday' : `${d} days ago`;
  }
  return then.toLocaleDateString();
}

/** Full timestamp for the `title` attribute beside a relative date. */
export function absoluteDate(input) {
  if (!input) return '';
  const d = new Date(input);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString();
}
