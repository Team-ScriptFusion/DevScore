import Meter from './Meter.jsx';

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
        <div className="card-head">
          <h3>GitHub Evidence</h3>
        </div>
        <p className="muted">
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
      <div className="card-head">
        <div>
          <h3>GitHub Evidence</h3>
          <p className="muted">
            What was actually found in the public repositories we mined.
          </p>
        </div>
      </div>

      {/* Ownership is the number that decides how much the rest is worth, so it
          gets a bar rather than being buried in a sentence. */}
      {authorship && authorship.total > 0 && (
        <div className="readiness__section">
          <h4 className="readiness__section-title">Commit Authorship</h4>
          <div className="evidence__authorship">
            <Meter
              value={authorship.mine}
              max={authorship.total}
              label="Commits authored by this candidate"
              valueLabel={`${authorship.mine} / ${authorship.total} · ${Math.round(authorship.ownership_ratio * 100)}%`}
            />
            {authorship.disputed > 0 && (
              <p className="muted evidence__disputed">
                {authorship.disputed} commit{authorship.disputed === 1 ? '' : 's'} disputed.
              </p>
            )}
          </div>
        </div>
      )}

      {verdicts.length === 0 ? (
        <p className="muted">No repository-level evidence was found.</p>
      ) : (
        <ul className="evidence-list">
          {verdicts.map((v) => (
            <li className="evidence-item" key={v.skill}>
              <div className="evidence-item__head">
                <strong className="evidence-item__skill">{v.skill}</strong>
                <span className={`badge ${STATUS_BADGE[v.status] || 'badge--neutral'}`}>
                  {STATUS_LABEL[v.status] || v.status}
                </span>
              </div>
              {v.repos?.length > 0 && (
                <p className="evidence-item__repos">
                  {v.repos.map((repo) => (
                    <span className="evidence-item__repo" key={repo}>
                      {repo}
                    </span>
                  ))}
                </p>
              )}
              {v.explanation && (
                <p className="evidence-item__explanation">{v.explanation}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
