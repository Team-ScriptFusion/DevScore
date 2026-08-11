import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import SkillChips from '../components/SkillChips.jsx';
import { recruiterApi } from '../lib/api.js';
import { ResumeIcon, GithubMiningIcon } from '../components/FeatureIcons.jsx';

function initials(name) {
  return (name || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0].toUpperCase())
    .join('');
}

/**
 * Read-only candidate profile detail (FR 47/48). Shows verification state
 * only — no readiness score, since the scoring engine isn't built yet
 * (Implementation 02 work).
 */
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
        <p className="muted">Loading…</p>
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

          <div className="placeholder" style={{ marginTop: 20 }}>
            Job Readiness Score &amp; Evidence Gap — coming once the scoring
            engine ships.
          </div>
        </>
      )}
    </DashboardLayout>
  );
}
