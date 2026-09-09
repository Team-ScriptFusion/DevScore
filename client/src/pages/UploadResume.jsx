import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import PageHeader from '../components/PageHeader.jsx';
import { InlineLoader } from '../components/Spinner.jsx';
import { jobsApi, resumeApi } from '../lib/api.js';
import { relativeDate, absoluteDate } from '../lib/format.js';
import { ResumeIcon } from '../components/FeatureIcons.jsx';
import { LockIcon } from '../components/DashboardIcons.jsx';

function formatSize(bytes) {
  if (!bytes) return '';
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Upload Resume screen (FR 19-27). Accepts a PDF, stores it, and triggers
 * skill extraction (re-uploading replaces + re-parses). The extracted
 * skills themselves are shown on their own Skills Status page, not here.
 */
export default function UploadResume() {
  const [status, setStatus] = useState(null);
  // Optimistic until we know otherwise, so an unrelated fetch failure (e.g.
  // job_applications not migrated yet) never flashes a false "locked" state.
  const [roleApplied, setRoleApplied] = useState(true);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    (async () => {
      const [s, a] = await Promise.allSettled([resumeApi.status(), jobsApi.listApplied()]);
      if (s.status === 'fulfilled') setStatus(s.value);
      if (a.status === 'fulfilled') setRoleApplied(a.value.applications.length > 0);
      setLoading(false);
    })();
  }, []);

  async function handleFileChosen(e) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;

    setError('');
    if (file.type !== 'application/pdf') {
      return setError('Only PDF resumes are accepted.');
    }
    if (file.size > 5 * 1024 * 1024) {
      return setError('Resume must be 5MB or smaller.');
    }

    setUploading(true);
    try {
      const result = await resumeApi.upload(file);
      setStatus(result);
    } catch (err) {
      setError(err.message || 'Upload failed. Please try again.');
    } finally {
      setUploading(false);
    }
  }

  return (
    <DashboardLayout>
      <PageHeader
        title="Upload Resume"
        subtitle="Upload a PDF resume so we can extract the skills you claim and match them against your GitHub evidence."
      />

      {error && (
        <div className="alert alert--error alert--stack" role="alert">
          {error}
        </div>
      )}

      <div className="card card--narrow">
        {loading ? (
          <InlineLoader label="Checking resume status…" />
        ) : status?.uploaded ? (
          <div className="state-panel">
            <span className="state-panel__icon state-panel__icon--done">
              <ResumeIcon />
            </span>
            <div className="state-panel__body">
              <span className="badge badge--verified">Uploaded</span>
              <h3 className="state-panel__title">{status.filename}</h3>
              <p className="muted" title={absoluteDate(status.uploadedAt)}>
                {formatSize(status.sizeBytes)}
                {status.uploadedAt ? ` · ${relativeDate(status.uploadedAt)}` : ''}
              </p>
              <div className="state-panel__actions">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => inputRef.current?.click()}
                  disabled={uploading}
                >
                  {uploading ? 'Uploading…' : 'Replace resume'}
                </button>
              </div>
            </div>
          </div>
        ) : !roleApplied ? (
          <div className="state-panel">
            <span className="state-panel__icon state-panel__icon--locked">
              <LockIcon />
            </span>
            <div className="state-panel__body">
              <h3 className="state-panel__title">Select a job role first</h3>
              <p className="muted">
                Your resume is reviewed against the roles you&rsquo;ve applied for,
                so we need to know which ones those are.
              </p>
              <div className="state-panel__actions">
                <Link to="/student/jobs" className="btn-primary">
                  Browse Job Roles
                </Link>
              </div>
            </div>
          </div>
        ) : (
          <div className="state-panel">
            <span className="state-panel__icon">
              <ResumeIcon />
            </span>
            <div className="state-panel__body">
              <h3 className="state-panel__title">No resume uploaded yet</h3>
              <p className="muted">PDF only, up to 5MB.</p>
              <div className="state-panel__actions">
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => inputRef.current?.click()}
                  disabled={uploading}
                >
                  {uploading ? 'Uploading…' : 'Upload Resume'}
                </button>
              </div>
            </div>
          </div>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          onChange={handleFileChosen}
          hidden
        />
      </div>

      {status?.uploaded && (
        <p className="muted card--stack">
          We extract skills from your resume automatically — check{' '}
          <Link to="/student/skills" className="text-link">
            Skills Status
          </Link>{' '}
          to see what was found.
        </p>
      )}
    </DashboardLayout>
  );
}
