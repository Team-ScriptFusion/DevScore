import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import PageHeader from '../components/PageHeader.jsx';
import EmptyState from '../components/EmptyState.jsx';
import useReveal from '../hooks/useReveal.js';
import { InlineLoader } from '../components/Spinner.jsx';
import { useSearch, matches } from '../context/SearchContext.jsx';
import { jobsApi } from '../lib/api.js';
import { BriefcaseIcon, InboxIcon } from '../components/DashboardIcons.jsx';

const EMPLOYMENT_LABELS = {
  'full-time': 'Full-time',
  'part-time': 'Part-time',
  internship: 'Internship',
  contract: 'Contract',
};

// Server-side redirect landings — the client already hides the resume/GitHub
// actions until a role is picked, but the server enforces it too (e.g. a
// direct hit on the connect URL), and redirects back here with this code.
const ERROR_MESSAGES = {
  select_role_first: 'Select a job role before uploading a resume or connecting GitHub.',
};

/**
 * Job roles browser — step 1 of the student setup checklist. A student picks
 * the roles they're applying for before uploading a resume or connecting
 * GitHub; the resume and GitHub link are shared across every application.
 */
export default function BrowseJobs() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState('');
  const [error, setError] = useState(() => {
    const code = searchParams.get('error');
    return code ? ERROR_MESSAGES[code] || '' : '';
  });

  const query = useSearch('Search roles by title, location or skill…');

  useEffect(() => {
    if (!searchParams.get('error')) return;
    searchParams.delete('error');
    setSearchParams(searchParams, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refresh() {
    const { jobs: rows } = await jobsApi.listOpen();
    setJobs(rows);
  }

  useEffect(() => {
    (async () => {
      try {
        await refresh();
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function handleApply(job) {
    setError('');
    setBusyId(job.id);
    try {
      await jobsApi.apply(job.id);
      await refresh();
    } catch (err) {
      setError(err.message || 'Could not apply to this role. Please try again.');
    } finally {
      setBusyId('');
    }
  }

  async function handleWithdraw(job) {
    if (!window.confirm(`Withdraw your application for "${job.title}"?`)) return;
    setError('');
    setBusyId(job.id);
    try {
      await jobsApi.withdraw(job.id);
      await refresh();
    } catch (err) {
      setError(err.message || 'Could not withdraw. Please try again.');
    } finally {
      setBusyId('');
    }
  }

  const appliedCount = jobs.filter((j) => j.applied).length;

  const visible = useMemo(
    () =>
      jobs.filter((j) =>
        matches(query, j.title, j.location, j.description, (j.requiredSkills || []).join(' ')),
      ),
    [jobs, query],
  );

  const gridRef = useReveal([loading, visible.length], { enabled: !loading });

  return (
    <DashboardLayout>
      <PageHeader
        title="Job Roles"
        subtitle="Pick the roles you're applying for. Your resume and GitHub connection are shared across every application, so you only set them up once."
      />

      {error && (
        <div className="alert alert--error alert--stack" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <InlineLoader />
      ) : jobs.length === 0 ? (
        <div className="card">
          <EmptyState
            Icon={BriefcaseIcon}
            title="No open roles yet"
            description="No recruiter has published a role so far. Check back soon — new postings appear here as they go live."
          />
        </div>
      ) : visible.length === 0 ? (
        <div className="card">
          <EmptyState
            Icon={InboxIcon}
            title="No matching roles"
            description="Nothing matches your search. Try a different title, location or skill."
          />
        </div>
      ) : (
        <>
          <div className="job-grid" ref={gridRef}>
            {visible.map((job) => {
              const closed = job.status === 'closed';
              const busy = busyId === job.id;
              return (
                <article
                  className={`job-card card ${job.applied ? 'is-applied' : ''}`}
                  key={job.id}
                >
                  <div className="job-card__header">
                    <h3 className="job-card__title">{job.title}</h3>
                    {job.applied && <span className="badge badge--verified">Applied</span>}
                  </div>

                  <div className="job-card__meta">
                    <span className="job-tag">
                      {EMPLOYMENT_LABELS[job.employmentType] || job.employmentType}
                    </span>
                    {job.location && <span className="job-tag">{job.location}</span>}
                    {closed && <span className="badge badge--neutral">Closed</span>}
                  </div>

                  <p className="job-card__desc">
                    {job.description || 'No description provided.'}
                  </p>

                  {job.requiredSkills.length > 0 && (
                    <div className="skill-chips skill-chips--inline job-card__skills">
                      {job.requiredSkills.map((skill) => (
                        <span className="skill-chip" key={skill}>{skill}</span>
                      ))}
                    </div>
                  )}

                  <div className="job-card__footer">
                    {job.applied ? (
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => handleWithdraw(job)}
                        disabled={busy}
                      >
                        {busy ? 'Working…' : 'Withdraw'}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => handleApply(job)}
                        disabled={busy || closed}
                      >
                        {busy ? 'Applying…' : 'Apply for this role'}
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>

          {appliedCount > 0 && (
            <div className="card card--stack">
              <div className="card-head">
                <div>
                  <h3>Next step</h3>
                  <p className="muted">
                    You&rsquo;ve applied to {appliedCount} role
                    {appliedCount === 1 ? '' : 's'}. Upload your resume and connect
                    GitHub so recruiters have evidence to review.
                  </p>
                </div>
                <Link to="/student/resume" className="btn-primary">
                  Upload Resume
                </Link>
              </div>
            </div>
          )}
        </>
      )}
    </DashboardLayout>
  );
}
