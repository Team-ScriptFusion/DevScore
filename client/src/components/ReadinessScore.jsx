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
 */
export default function ReadinessScore({ readiness, emptyHint }) {
  const status = readiness?.status;
  const label = STATUS_LABEL[status];
  const gap = readiness?.evidenceGap;

  return (
    <div className="card">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <h3 style={{ margin: 0 }}>Job Readiness Score</h3>
        {label && <span className={`badge ${label.badge}`}>{label.text}</span>}
      </div>

      {status === 'success' ? (
        <>
          <p style={{ marginBottom: 4 }}>
            <strong style={{ fontSize: '1.6em' }}>{readiness.score}</strong>
            <span className="muted"> / 100 &mdash; {readiness.band}</span>
          </p>
          {readiness.confidence != null && (
            <p className="muted" style={{ marginTop: 0, marginBottom: 16, fontSize: '0.9em' }}>
              Confidence {Math.round(readiness.confidence * 100)}% &mdash; how much evidence
              this score rests on.
            </p>
          )}

          {readiness.categoryScores && Object.keys(readiness.categoryScores).length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <h4 style={{ margin: '0 0 8px' }}>By Category</h4>
              {Object.entries(readiness.categoryScores).map(([category, score]) => (
                <div
                  key={category}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    maxWidth: 320,
                    marginBottom: 4,
                  }}
                >
                  <span className="muted">{category}</span>
                  <span>{score}</span>
                </div>
              ))}
            </div>
          )}

          {gap && (gap.verified.length + gap.weakly_verified.length + gap.unverified.length > 0) && (
            <div style={{ marginBottom: 16 }}>
              <h4 style={{ margin: '0 0 8px' }}>Evidence Gap</h4>
              {['verified', 'weakly_verified', 'unverified'].map(
                (bucket) =>
                  gap[bucket]?.length > 0 && (
                    <div key={bucket} style={{ marginBottom: 8 }}>
                      <span className="skill-group__label">{GAP_LABEL[bucket]}</span>
                      <div className="skill-chips">
                        {gap[bucket].map((skill) => (
                          <span key={skill} className={`badge ${GAP_BADGE[bucket]}`} style={{ marginRight: 6 }}>
                            {skill}
                          </span>
                        ))}
                      </div>
                    </div>
                  ),
              )}
            </div>
          )}

          {readiness.breakdown && (
            <p className="muted" style={{ fontSize: '0.85em', marginBottom: 16 }}>
              Raw ratio {readiness.breakdown.raw_ratio} shrunk to base score{' '}
              {readiness.breakdown.base_score}
              {readiness.breakdown.integrity_penalty > 0 &&
                `, integrity penalty -${readiness.breakdown.integrity_penalty}`}
              {readiness.breakdown.breadth_bonus > 0 &&
                `, breadth bonus +${readiness.breakdown.breadth_bonus}`}
              .
            </p>
          )}

          {readiness.warnings?.length > 0 && (
            <ul className="muted" style={{ margin: 0, paddingLeft: 18, fontSize: '0.9em' }}>
              {readiness.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </>
      ) : status === 'pending' ? (
        <p className="muted" style={{ margin: 0 }}>
          Verifying claimed skills against GitHub activity &mdash; this can take up to a minute.
        </p>
      ) : status === 'failed' ? (
        <p className="muted" style={{ margin: 0 }}>
          We couldn&rsquo;t score this GitHub evidence
          {readiness?.error ? ` (${readiness.error})` : ''}. Try again in a bit.
        </p>
      ) : (
        <p className="muted" style={{ margin: 0 }}>{emptyHint}</p>
      )}
    </div>
  );
}
