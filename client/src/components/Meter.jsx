/**
 * Horizontal progress bar — the `.evidence-bar` treatment from the marketing
 * page, generalised. Used for readiness category scores, confidence, and
 * applicant counts, all of which were plain numbers before.
 *
 * `max` lets a row be scaled against a peer group rather than 100 (the
 * recruiter's job list scales each posting against the busiest one), so
 * `valueLabel` exists separately to show the real figure.
 */
export default function Meter({
  value,
  max = 100,
  label,
  valueLabel,
  tone = 'primary',
  size = 'md',
}) {
  const safeMax = max > 0 ? max : 1;
  const pct = Math.max(0, Math.min(100, (Number(value) || 0) / safeMax * 100));

  return (
    <div className={`meter meter--${size}`}>
      {(label || valueLabel) && (
        <div className="meter__head">
          {label && <span className="meter__label">{label}</span>}
          {valueLabel && <span className="meter__value">{valueLabel}</span>}
        </div>
      )}
      <div
        className="meter__track"
        role="meter"
        aria-valuenow={Number(value) || 0}
        aria-valuemin={0}
        aria-valuemax={safeMax}
        aria-label={label || valueLabel || 'Progress'}
      >
        <span className={`meter__fill meter__fill--${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/**
 * A single stacked bar for composition (e.g. the admin's students / recruiters
 * / admins split). `segments` is [{ key, label, value, tone }].
 */
export function StackedMeter({ segments, label }) {
  const total = segments.reduce((sum, s) => sum + (Number(s.value) || 0), 0);

  return (
    <div className="stacked-meter">
      <div className="stacked-meter__track" role="img" aria-label={label}>
        {total > 0 &&
          segments.map((s) => {
            const pct = ((Number(s.value) || 0) / total) * 100;
            if (pct === 0) return null;
            return (
              <span
                key={s.key}
                className={`stacked-meter__seg stacked-meter__seg--${s.tone}`}
                style={{ width: `${pct}%` }}
                title={`${s.label}: ${s.value}`}
              />
            );
          })}
      </div>
      <ul className="stacked-meter__legend">
        {segments.map((s) => (
          <li key={s.key}>
            <span className={`stacked-meter__dot stacked-meter__dot--${s.tone}`} />
            <span className="stacked-meter__legend-label">{s.label}</span>
            <span className="stacked-meter__legend-value">
              {s.value}
              <span className="stacked-meter__legend-pct">
                {total > 0 ? ` · ${Math.round((s.value / total) * 100)}%` : ''}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
