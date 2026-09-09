import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import SkillChips from '../components/SkillChips.jsx';
import ReadinessScore from '../components/ReadinessScore.jsx';
import GithubEvidence from '../components/GithubEvidence.jsx';
import { recruiterApi } from '../lib/api.js';
import { initials, avatarTint, relativeDate, absoluteDate } from '../lib/format.js';
import { ResumeIcon, GithubMiningIcon } from '../components/FeatureIcons.jsx';
import { InlineLoader } from '../components/Spinner.jsx';

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
      <Link to="/recruiter" className="auth-back auth-back--stack">
        &larr; Back to candidates
      </Link>

      {loading ? (
        <InlineLoader />
      ) : error ? (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      ) : (
        <>
          <div className="profile-header card">
            <span className={`avatar avatar--lg avatar--tint-${avatarTint(candidate.name)}`}>
              {initials(candidate.name)}
            </span>
            <div>
              <h1 className="page-title profile-header__name">{candidate.name}</h1>
              <p className="muted">{candidate.email}</p>
            </div>
          </div>

          {candidate.appliedRoles?.length > 0 && (
            <div className="card card--stack">
              <div className="card-head">
                <div>
                  <h3>Applied For</h3>
                  <p className="muted">Your postings this candidate applied to.</p>
                </div>
              </div>
              <ul className="applied-list applied-list--flush">
                {candidate.appliedRoles.map((r) => (
                  <li className="applied-list__item" key={r.jobId}>
                    <span className="applied-list__title">{r.jobTitle}</span>
                    <span className="applied-list__meta" title={absoluteDate(r.appliedAt)}>
                      Applied {relativeDate(r.appliedAt)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="setup-grid setup-grid--stack">
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
                  <p className="setup-card__meta" title={absoluteDate(candidate.resumeUploadedAt)}>
                    Uploaded {relativeDate(candidate.resumeUploadedAt)}
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
                  <p
                    className="setup-card__meta"
                    title={absoluteDate(candidate.githubConnectedAt)}
                  >
                    Connected {relativeDate(candidate.githubConnectedAt)}
                  </p>
                </>
              ) : (
                <p className="muted">This candidate hasn&rsquo;t connected GitHub yet.</p>
              )}
            </div>
          </div>

          {candidate.resumeVerified && (
            <div className="card card--stack">
              <div className="card-head">
                <div>
                  <h3>Claimed Skills</h3>
                  <p className="muted">
                    Extracted from the candidate&rsquo;s resume — not yet verified
                    against GitHub evidence.
                  </p>
                </div>
              </div>
              <SkillChips
                status={candidate.skillsStatus}
                byCategory={candidate.claimedSkills}
                uncategorized={candidate.skillsUncategorized}
              />
            </div>
          )}

          <div className="card--stack">
            <ReadinessScore
              readiness={candidate.readiness}
              emptyHint={
                candidate.githubVerified
                  ? "Not scored yet — this candidate hasn't uploaded a resume with recognised skills."
                  : "Not scored yet — this candidate hasn't connected GitHub."
              }
            />
          </div>
          <div className="card--stack">
            <GithubEvidence
              readiness={candidate.readiness}
              emptyHint={
                candidate.githubVerified
                  ? 'No GitHub evidence yet.'
                  : "This candidate hasn't connected GitHub."
              }
            />
          </div>
        </>
      )}
    </DashboardLayout>
  );
}
