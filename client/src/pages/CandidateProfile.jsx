import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import SkillChips from '../components/SkillChips.jsx';
import { recruiterApi } from '../lib/api.js';
import { ResumeIcon, GithubMiningIcon } from '../components/FeatureIcons.jsx';
import { InlineLoader } from '../components/Spinner.jsx';

function initials(name) {
  return (name || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0].toUpperCase())
    .join('');
}

/** Read-only candidate profile detail (FR 47/48), including the semantic_engine job readiness score. */
export default function CandidateProfile() {
  const { id } = useParams();
  const [candidate, setCandidate] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { candidate: c } = await recruiterApi.getCandidate(id);
        setCandidate(c);
      } catch (err) {
        setError(err.message || 'Could not load this candidate.');
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  return (
    <DashboardLayout>
      <Link to="/recruiter" className="auth-back" style={{ marginBottom: 16 }}>
        &larr; Back to candidates
      </Link>

      {loading ? (
        <InlineLoader />
      ) : error ? (
        <div className="alert alert--error">{error}</div>
      ) : (
        <>
          <div className="profile-header card">
            <span className="avatar avatar--lg">{initials(candidate.name)}</span>
            <div>
              <h1 className="page-title" style={{ marginBottom: 2 }}>
                {candidate.name}
              </h1>
              <p className="muted">{candidate.email}</p>
            </div>
          </div>

          {candidate.appliedRoles?.length > 0 && (
            <div className="card" style={{ marginTop: 20 }}>
              <h3 style={{ marginTop: 0 }}>Applied For</h3>
              <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
                Your postings this candidate applied to.
              </p>
              <ul className="applied-list" style={{ marginBottom: 0 }}>
                {candidate.appliedRoles.map((r) => (
                  <li className="applied-list__item" key={r.jobId}>
                    <span className="applied-list__title">{r.jobTitle}</span>
                    <span className="applied-list__meta">
                      Applied {new Date(r.appliedAt).toLocaleDateString()}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="setup-grid" style={{ marginTop: 20 }}>
            <div className={`setup-card card ${candidate.resumeVerified ? 'is-done' : ''}`}>
              <div className="setup-card__header">
                <span className="setup-card__icon">
                  <ResumeIcon />
                </span>
                <span className={`badge ${candidate.resumeVerified ? 'badge--verified' : 'badge--missing'}`}>
                  {candidate.resumeVerified ? 'Verified' : 'Missing'}
                </span>
              </div>
              <h3>Resume</h3>
              {candidate.resumeVerified ? (
                <>
                  <p className="muted">{candidate.resumeFilename}</p>
                  <p className="setup-card__meta">
                    Uploaded {new Date(candidate.resumeUploadedAt).toLocaleDateString()}
                  </p>
                </>
              ) : (
                <p className="muted">This candidate hasn&rsquo;t uploaded a resume yet.</p>
              )}
            </div>

            <div className={`setup-card card ${candidate.githubVerified ? 'is-done' : ''}`}>
              <div className="setup-card__header">
                <span className="setup-card__icon">
                  <GithubMiningIcon />
                </span>
                <span className={`badge ${candidate.githubVerified ? 'badge--verified' : 'badge--missing'}`}>
                  {candidate.githubVerified ? 'Verified' : 'Missing'}
                </span>
              </div>
              <h3>GitHub</h3>
              {candidate.githubVerified ? (
                <>
                  <p className="muted">@{candidate.githubUsername}</p>
                  <p className="setup-card__meta">
                    Connected {new Date(candidate.githubConnectedAt).toLocaleDateString()}
                  </p>
                </>
              ) : (
                <p className="muted">This candidate hasn&rsquo;t connected GitHub yet.</p>
              )}
            </div>
          </div>

          {candidate.resumeVerified && (
            <div className="card" style={{ marginTop: 20 }}>
              <h3 style={{ marginTop: 0 }}>Claimed Skills</h3>
              <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
                Extracted from the candidate&rsquo;s resume — not yet
                verified against GitHub evidence.
              </p>
              <SkillChips
                status={candidate.skillsStatus}
                byCategory={candidate.claimedSkills}
                uncategorized={candidate.skillsUncategorized}
              />
            </div>
          )}

          <div className="card" style={{ marginTop: 20 }}>
            <h3 style={{ marginTop: 0 }}>Job Readiness Score</h3>
            {candidate.readinessStatus === 'success' ? (
              <p style={{ marginBottom: 0 }}>
                <strong style={{ fontSize: '1.5em' }}>{candidate.readinessScore}</strong>
                <span className="muted"> / 100 &mdash; {candidate.readinessBand}</span>
              </p>
            ) : candidate.readinessStatus === 'pending' ? (
              <p className="muted" style={{ marginBottom: 0 }}>
                Verifying claimed skills against GitHub evidence&hellip;
              </p>
            ) : candidate.readinessStatus === 'failed' ? (
              <p className="muted" style={{ marginBottom: 0 }}>
                Scoring failed for this candidate&rsquo;s GitHub evidence.
              </p>
            ) : (
              <p className="muted" style={{ marginBottom: 0 }}>
                {candidate.githubVerified
                  ? "Not scored yet — this candidate hasn't uploaded a resume with recognised skills."
                  : "Not scored yet — this candidate hasn't connected GitHub."}
              </p>
            )}
          </div>
        </>
      )}
    </DashboardLayout>
  );
}
