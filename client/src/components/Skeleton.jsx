/**
 * Loading placeholders that occupy the same space as the content they stand in
 * for. The dashboards previously dropped an `InlineLoader` into a zero-height
 * container, so every table and stat grid jumped once data landed.
 *
 * The sheen is pure CSS and is disabled under `prefers-reduced-motion` in
 * index.css — the bars still render, they just stop moving.
 */

export function SkeletonBar({ width = '100%' }) {
  return <span className="skeleton skeleton--bar" style={{ width }} />;
}

/** Widths cycle so a block of rows doesn't read as a suspiciously even grid. */
const CELL_WIDTHS = ['72%', '54%', '84%', '46%', '64%'];

export function SkeletonRows({ cols = 4, rows = 4 }) {
  return (
    <div className="skeleton-table" aria-hidden="true">
      {Array.from({ length: rows }, (_, r) => (
        <div className="skeleton-table__row" key={r}>
          {Array.from({ length: cols }, (_, c) => (
            <span
              className="skeleton skeleton--bar"
              key={c}
              style={{ width: CELL_WIDTHS[(r + c) % CELL_WIDTHS.length] }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonCards({ n = 3 }) {
  return (
    <div className="stat-grid" aria-hidden="true">
      {Array.from({ length: n }, (_, i) => (
        <div className="card stat-card stat-card--skeleton" key={i}>
          <div className="stat-card__body">
            <span className="skeleton skeleton--bar skeleton--label" />
            <span className="skeleton skeleton--bar skeleton--value" />
          </div>
          <span className="skeleton skeleton--tile" />
        </div>
      ))}
    </div>
  );
}

/**
 * Screen-reader announcement to pair with any of the above — the visual
 * skeleton is `aria-hidden`, so without this a load is silent.
 */
export function LoadingAnnouncement({ label = 'Loading' }) {
  return (
    <span className="sr-only" role="status" aria-live="polite">
      {label}
    </span>
  );
}
