import ScoreRing, { ScoreRingEmpty } from './ScoreRing.jsx';
import Meter from './Meter.jsx';

const STATUS_LABEL = {
  pending: { text: 'Scoring…', badge: 'badge--pending' },
  success: { text: 'Scored', badge: 'badge--verified' },
  failed: { text: 'Scoring failed', badge: 'badge--missing' },
};

const GAP_BADGE = {
  verified: 'badge--verified',
  weakly_verified: 'badge--pending',
  unverified: 'badge--missing',
};

const GAP_LABEL = {
  verified: 'Verified',
  weakly_verified: 'Weakly verified',
  unverified: 'Unverified',
};

/**
 * The full semantic_engine job-readiness result: headline score/band,
 * confidence, per-category scores, the evidence gap (which claimed skills
 * are backed by code vs not), the scoring breakdown, and any warnings.
 * Shared between the student's own view and the recruiter's candidate view
 * so both render the same shape (see server/src/models/ReadinessReport.js).
 *
 * Category scores render as meters rather than a label/number list: the whole
 * point of the section is which areas are strong relative to the others, and a
 * column of digits makes the reader do that comparison themselves.
 */
export default function ReadinessScore({ readiness, emptyHint }) {
  const status = readiness?.status;
  const label = STATUS_LABEL[status];
  const gap = readiness?.evidenceGap;
  const hasGap =
    gap && gap.verified.length + gap.weakly_verified.length + gap.unverified.length > 0;

  return (
    <div className="card">
      <div className="card-head">
        <h3>Job Readiness Score</h3>
        {label && <span className={`badge ${label.badge}`}>{label.text}</span>}
      </div>

      {status === 'success' ? (
        <>
          <div className="readiness__summary">
            <ScoreRing
              value={readiness.score}
              size="md"
              suffix="/100"
              label={`Readiness score ${readiness.score} out of 100`}
            />
            <div>
              <p className="readiness__band">{readiness.band}</p>
              <p className="muted">
                Measured against the claimed skills we could verify in real code.
              </p>
              {readiness.confidence != null && (
                <div className="readiness__confidence">
                  <Meter
                    size="sm"
                    value={Math.round(readiness.confidence * 100)}
                    label="Confidence"
                    valueLabel={`${Math.round(readiness.confidence * 100)}%`}
                  />
                </div>
              )}
            </div>
          </div>

          {readiness.categoryScores && Object.keys(readiness.categoryScores).length > 0 && (
            <div className="readiness__section">
              <h4 className="readiness__section-title">By Category</h4>
              <div className="readiness__categories">
                {Object.entries(readiness.categoryScores).map(([category, score]) => (
                  <Meter
                    key={category}
                    value={score}
                    label={category}
                    valueLabel={String(score)}
                  />
                ))}
              </div>
            </div>
          )}

          {hasGap && (
            <div className="readiness__section">
              <h4 className="readiness__section-title">Evidence Gap</h4>
              {['verified', 'weakly_verified', 'unverified'].map(
                (bucket) =>
                  gap[bucket]?.length > 0 && (
                    <div className="readiness__gap-group" key={bucket}>
                      <span className="skill-group__label">
                        {GAP_LABEL[bucket]} ({gap[bucket].length})
                      </span>
                      <div className="skill-chips">
                        {gap[bucket].map((skill) => (
                          <span key={skill} className={`badge ${GAP_BADGE[bucket]}`}>
                            {skill}
                          </span>
                        ))}
                      </div>
                    </div>
                  ),
              )}
            </div>
          )}

          {readiness.warnings?.length > 0 && (
            <div className="readiness__section">
              <h4 className="readiness__section-title">Warnings</h4>
              <ul className="readiness__warnings">
                {readiness.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Available for anyone who wants to audit the number, but folded away
              so it doesn't compete with the score it explains. */}
          {readiness.breakdown && (
            <details className="readiness__details">
              <summary>How this score was calculated</summary>
              <p className="readiness__breakdown">
                Raw ratio {readiness.breakdown.raw_ratio} shrunk to base score{' '}
                {readiness.breakdown.base_score}
                {readiness.breakdown.integrity_penalty > 0 &&
                  `, integrity penalty -${readiness.breakdown.integrity_penalty}`}
                {readiness.breakdown.breadth_bonus > 0 &&
                  `, breadth bonus +${readiness.breakdown.breadth_bonus}`}
                .
              </p>
            </details>
          )}
        </>
      ) : (
        <div className="readiness__summary readiness__summary--empty">
          <ScoreRingEmpty size="md" hint={status === 'pending' ? '…' : '—'} />
          <p className="muted">
            {status === 'pending'
              ? 'Verifying claimed skills against GitHub activity — this can take up to a minute.'
              : status === 'failed'
                ? `We couldn’t score this GitHub evidence${readiness?.error ? ` (${readiness.error})` : ''}. Try again in a bit.`
                : emptyHint}
          </p>
        </div>
      )}
    </div>
  );
}
