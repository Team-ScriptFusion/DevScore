const STATUS_BADGE = {
  verified: 'badge--verified',
  weakly_verified: 'badge--pending',
  unverified: 'badge--missing',
  unclaimed_strength: 'badge--neutral',
};

const STATUS_LABEL = {
  verified: 'Verified',
  weakly_verified: 'Weakly verified',
  unverified: 'Unverified',
  unclaimed_strength: 'Found in code, not claimed',
};

/**
 * What semantic_engine actually found in the candidate's public
 * repositories — commit authorship and, per skill, which repos and code
 * backed (or failed to back) the claim. Deliberately its own card, separate
 * from the headline score, so "what evidence did we find" reads apart from
 * "what number did it produce".
 */
export default function GithubEvidence({ readiness, emptyHint }) {
  const status = readiness?.status;

  if (status !== 'success') {
    return (
      <div className="card">
        <h3 style={{ marginTop: 0 }}>GitHub Evidence</h3>
        <p className="muted" style={{ margin: 0 }}>
          {status === 'pending'
            ? 'Mining GitHub activity…'
            : status === 'failed'
              ? "We couldn't fetch GitHub evidence this time."
              : emptyHint}
        </p>
      </div>
    );
  }

  const verdicts = (readiness.verdicts || []).filter(
    (v) => (v.repos && v.repos.length > 0) || (v.evidence && v.evidence.length > 0),
  );
  const authorship = readiness.authorship;

  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>GitHub Evidence</h3>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        What was actually found in the public repositories we mined.
      </p>

      {authorship && authorship.total > 0 && (
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ margin: '0 0 8px' }}>Commit Authorship</h4>
          <p className="muted" style={{ margin: 0 }}>
            {authorship.mine} of {authorship.total} mined commits belong to this candidate (
            {Math.round(authorship.ownership_ratio * 100)}% ownership)
            {authorship.disputed > 0 && `, ${authorship.disputed} disputed`}.
          </p>
        </div>
      )}

      {verdicts.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>No repository-level evidence was found.</p>
      ) : (
        verdicts.map((v) => (
          <div
            key={v.skill}
            style={{
              marginBottom: 14,
              paddingBottom: 14,
              borderBottom: '1px solid var(--ds-border)',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 4,
              }}
            >
              <strong>{v.skill}</strong>
              <span className={`badge ${STATUS_BADGE[v.status] || 'badge--neutral'}`}>
                {STATUS_LABEL[v.status] || v.status}
              </span>
            </div>
            {v.repos?.length > 0 && (
              <p className="muted" style={{ margin: '0 0 4px', fontSize: '0.9em' }}>
                Repositories: {v.repos.join(', ')}
              </p>
            )}
            {v.explanation && (
              <p className="muted" style={{ margin: 0, fontSize: '0.9em' }}>{v.explanation}</p>
            )}
          </div>
        ))
      )}
    </div>
  );
}
