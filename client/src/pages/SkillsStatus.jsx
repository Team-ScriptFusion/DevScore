import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import PageHeader from '../components/PageHeader.jsx';
import SkillChips from '../components/SkillChips.jsx';
import ReadinessScore from '../components/ReadinessScore.jsx';
import GithubEvidence from '../components/GithubEvidence.jsx';
import EmptyState from '../components/EmptyState.jsx';
import { InlineLoader } from '../components/Spinner.jsx';
import { resumeApi } from '../lib/api.js';
import { absoluteDate, relativeDate } from '../lib/format.js';
import { ResumeIcon } from '../components/FeatureIcons.jsx';

const STATUS_LABEL = {
  pending: { text: 'Extracting…', badge: 'badge--pending' },
  success: { text: 'Extracted', badge: 'badge--verified' },
  success_no_skills_found: { text: 'No skills found', badge: 'badge--pending' },
  failed: { text: 'Extraction failed', badge: 'badge--missing' },
};

// Scoring runs in the background (semantic_engine) and can take tens of
// seconds, so poll while it's in flight rather than making the student
// refresh the page.
const READINESS_POLL_MS = 4000;

/**
 * Skills Status screen (FR 28-32 "Display Extracted Skills Status") — its
 * own page, separate from the upload flow, so a student can check what was
 * parsed from their resume without re-triggering an upload.
 */
export default function SkillsStatus() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setStatus(await resumeApi.status());
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const readinessStatus = status?.readiness?.status;

  // Keep polling only while readiness scoring is actually in flight.
  useEffect(() => {
    if (readinessStatus !== 'pending') return undefined;
    const id = setInterval(async () => {
      try {
        setStatus(await resumeApi.status());
      } catch {
        /* transient poll failure — try again next tick */
      }
    }, READINESS_POLL_MS);
    return () => clearInterval(id);
  }, [readinessStatus]);

  const skillsStatus = status?.skills?.status;
  const label = STATUS_LABEL[skillsStatus];

  return (
    <DashboardLayout>
      <PageHeader
        title="Skills Status"
        subtitle="The skills we extracted from your resume — this is exactly what recruiters see."
        actions={
          status?.uploaded && (
            <Link to="/student/resume" className="btn-secondary">
              Replace resume
            </Link>
          )
        }
      />

      {loading ? (
        <InlineLoader />
      ) : !status?.uploaded ? (
        <div className="card">
          <EmptyState
            Icon={ResumeIcon}
            title="No resume uploaded yet"
            description="There's nothing to extract until you upload a PDF resume. We'll pull out the skills you claim and verify them against your GitHub."
            action={
              <Link to="/student/resume" className="btn-primary">
                Upload Resume
              </Link>
            }
          />
        </div>
      ) : (
        <div className="card">
          <div className="card-head">
            <div>
              <h3>{status.filename}</h3>
              {status.skills?.extractedAt && (
                <p className="muted" title={absoluteDate(status.skills.extractedAt)}>
                  Extracted {relativeDate(status.skills.extractedAt)}
                </p>
              )}
            </div>
            {label && <span className={`badge ${label.badge}`}>{label.text}</span>}
          </div>

          <SkillChips
            status={skillsStatus}
            byCategory={status.skills?.byCategory}
            uncategorized={status.skills?.uncategorized}
          />

          {skillsStatus === 'failed' && (
            <div className="state-panel__actions">
              <Link to="/student/resume" className="btn-secondary">
                Re-upload resume
              </Link>
            </div>
          )}
        </div>
      )}

      {status?.uploaded && (
        <>
          <div className="card--stack">
            <ReadinessScore
              readiness={status.readiness}
              emptyHint="Connect your GitHub account to unlock a readiness score based on your actual code."
            />
          </div>
          <div className="card--stack">
            <GithubEvidence
              readiness={status.readiness}
              emptyHint="Connect your GitHub account to see what evidence we can find in your public repositories."
            />
          </div>
        </>
      )}
    </DashboardLayout>
  );
}
