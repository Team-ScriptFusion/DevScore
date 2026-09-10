import { useEffect, useMemo, useState } from 'react';
import DashboardLayout from '../components/DashboardLayout.jsx';
import PageHeader from '../components/PageHeader.jsx';
import StatCard from '../components/StatCard.jsx';
import EmptyState from '../components/EmptyState.jsx';
import Modal from '../components/Modal.jsx';
import { SkeletonRows, SkeletonCards } from '../components/Skeleton.jsx';
import useReveal from '../hooks/useReveal.js';
import { useSearch, matches } from '../context/SearchContext.jsx';
import { jobsApi } from '../lib/api.js';
import {
  BriefcaseIcon,
  CheckBadgeIcon,
  CandidatesIcon,
  PlusIcon,
  InboxIcon,
} from '../components/DashboardIcons.jsx';

const EMPTY_JOB_FORM = {
  title: '',
  description: '',
  requiredSkills: '',
  employmentType: 'full-time',
  location: '',
};

const EMPLOYMENT_OPTIONS = [
  { value: 'full-time', label: 'Full-time' },
  { value: 'part-time', label: 'Part-time' },
  { value: 'internship', label: 'Internship' },
  { value: 'contract', label: 'Contract' },
];

const EMPLOYMENT_LABELS = Object.fromEntries(
  EMPLOYMENT_OPTIONS.map((o) => [o.value, o.label]),
);

/** The form edits skills as one comma-separated line; the API takes an array. */
function parseSkills(value) {
  return value.split(',').map((s) => s.trim()).filter(Boolean);
}

/**
 * Recruiter job postings manager. Candidates apply to a specific role, so this
 * is where a recruiter's candidate list comes from — with no postings, their
 * dashboard has nothing to show.
 */
export default function RecruiterJobs() {
  const [jobs, setJobs] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  // modal: null | { type: 'create' } | { type: 'edit', job }
  const [modal, setModal] = useState(null);
  const [jobForm, setJobForm] = useState(EMPTY_JOB_FORM);
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const query = useSearch('Search postings by title, location or skill…');

  const visible = useMemo(
    () =>
      jobs.filter((j) =>
        matches(query, j.title, j.location, j.description, (j.requiredSkills || []).join(' ')),
      ),
    [jobs, query],
  );

  const statsRef = useReveal([loading], { enabled: !loading });

  async function refresh() {
    const { jobs: rows, stats: s } = await jobsApi.listMine();
    setJobs(rows);
    setStats(s);
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

  function updateJobField(field) {
    return (e) => setJobForm((f) => ({ ...f, [field]: e.target.value }));
  }

  function openCreate() {
    setJobForm(EMPTY_JOB_FORM);
    setModal({ type: 'create' });
  }

  function openEdit(job) {
    setJobForm({
      title: job.title,
      description: job.description,
      requiredSkills: job.requiredSkills.join(', '),
      employmentType: job.employmentType,
      location: job.location,
    });
    setModal({ type: 'edit', job });
  }

  function closeModal() {
    setModal(null);
    setJobForm(EMPTY_JOB_FORM);
    setFormError('');
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setFormError('');

    if (!jobForm.title.trim()) {
      return setFormError('A job title is required.');
    }

    setSubmitting(true);
    try {
      const payload = { ...jobForm, requiredSkills: parseSkills(jobForm.requiredSkills) };
      if (modal.type === 'edit') {
        await jobsApi.update(modal.job.id, payload);
      } else {
        await jobsApi.create(payload);
      }
      closeModal();
      await refresh();
    } catch (err) {
      setFormError(err.message || 'Could not save the job posting.');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleToggleStatus(job) {
    await jobsApi.setStatus(job.id, job.status === 'open' ? 'closed' : 'open');
    await refresh();
  }

  async function handleDelete(job) {
    const applicants = job.applicantCount
      ? ` ${job.applicantCount} application${job.applicantCount === 1 ? '' : 's'} will be removed too.`
      : '';
    if (!window.confirm(`Delete "${job.title}"?${applicants} This cannot be undone.`)) return;
    await jobsApi.remove(job.id);
    await refresh();
  }

  return (
    <DashboardLayout>
      <PageHeader
        title="Job Postings"
        subtitle="Post the roles you're hiring for. Students apply to a specific role, and your dashboard shows you who applied to which."
        actions={
          <button type="button" className="btn-primary" onClick={openCreate}>
            <PlusIcon />
            Post a Job
          </button>
        }
      />

      {loading ? (
        <SkeletonCards n={3} />
      ) : (
        stats && (
          <div className="stat-grid" ref={statsRef}>
            <StatCard label="Total Postings" value={stats.total} Icon={BriefcaseIcon} />
            <StatCard label="Open Roles" value={stats.open} Icon={CheckBadgeIcon} />
            <StatCard label="Applicants" value={stats.applicants} Icon={CandidatesIcon} />
          </div>
        )
      )}

      <div className="card table-card">
        <div className="table-card__header">
          <h3>Your Postings</h3>
          <button type="button" className="btn-primary table-card__cta" onClick={openCreate}>
            <PlusIcon />
            Post a Job
          </button>
        </div>

        {loading ? (
          <SkeletonRows cols={6} rows={4} />
        ) : jobs.length === 0 ? (
          <EmptyState
            Icon={BriefcaseIcon}
            title="No postings yet"
            description="Candidates apply to a specific role, so post one to start receiving applicants."
            action={
              <button type="button" className="btn-primary" onClick={openCreate}>
                Post your first role
              </button>
            }
          />
        ) : visible.length === 0 ? (
          <EmptyState
            Icon={InboxIcon}
            title="No matching postings"
            description="Nothing matches your search. Try a different title, location or skill."
          />
        ) : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Role</th>
                    <th>Type</th>
                    <th>Location</th>
                    <th>Required Skills</th>
                    <th>Status</th>
                    <th>Applicants</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((job) => (
                    <tr key={job.id}>
                      <td>{job.title}</td>
                      <td>{EMPLOYMENT_LABELS[job.employmentType] || job.employmentType}</td>
                      <td>{job.location || '—'}</td>
                      <td>
                        {job.requiredSkills.length === 0 ? (
                          <span className="muted">—</span>
                        ) : (
                          <div className="skill-chips skill-chips--inline">
                            {job.requiredSkills.slice(0, 4).map((skill) => (
                              <span className="skill-chip" key={skill}>{skill}</span>
                            ))}
                            {job.requiredSkills.length > 4 && (
                              <span className="skill-chip skill-chip--more">
                                +{job.requiredSkills.length - 4}
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                      <td>
                        <span
                          className={`badge ${job.status === 'open' ? 'badge--verified' : 'badge--neutral'}`}
                        >
                          {job.status === 'open' ? 'Open' : 'Closed'}
                        </span>
                      </td>
                      <td>{job.applicantCount}</td>
                      <td className="data-table__actions">
                        <button type="button" className="btn-link" onClick={() => openEdit(job)}>
                          Edit
                        </button>
                        <button
                          type="button"
                          className="btn-link"
                          onClick={() => handleToggleStatus(job)}
                        >
                          {job.status === 'open' ? 'Close' : 'Reopen'}
                        </button>
                        <button
                          type="button"
                          className="btn-link btn-link--danger"
                          onClick={() => handleDelete(job)}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted table-card__footer">
              Showing {visible.length} posting{visible.length === 1 ? '' : 's'}
              {query && ` matching “${query}”`}
            </p>
          </>
        )}
      </div>

      {modal && (
        <Modal
          title={modal.type === 'edit' ? 'Edit Posting' : 'Post a Job'}
          description={
            modal.type === 'edit'
              ? 'Changes are visible to students immediately.'
              : 'Students will see this role and can apply to it right away.'
          }
          onClose={closeModal}
        >
          {formError && (
            <div className="auth-error" role="alert">
              {formError}
            </div>
          )}

          <form className="auth-form" onSubmit={handleSubmit}>
              <label className="auth-field">
                <span>Job title</span>
                <input
                  type="text"
                  value={jobForm.title}
                  onChange={updateJobField('title')}
                  placeholder="Backend Engineer"
                  required
                />
              </label>

              <div className="auth-form__row">
                <label className="auth-field">
                  <span>Employment type</span>
                  <select
                    value={jobForm.employmentType}
                    onChange={updateJobField('employmentType')}
                  >
                    {EMPLOYMENT_OPTIONS.map((o) => (
                      <option value={o.value} key={o.value}>{o.label}</option>
                    ))}
                  </select>
                </label>
                <label className="auth-field">
                  <span>Location</span>
                  <input
                    type="text"
                    value={jobForm.location}
                    onChange={updateJobField('location')}
                    placeholder="Colombo / Remote"
                  />
                </label>
              </div>

              <label className="auth-field">
                <span>Description</span>
                <textarea
                  rows={5}
                  value={jobForm.description}
                  onChange={updateJobField('description')}
                  placeholder="What the role involves, and what you're looking for."
                />
              </label>

              <label className="auth-field">
                <span>Required skills</span>
                <input
                  type="text"
                  value={jobForm.requiredSkills}
                  onChange={updateJobField('requiredSkills')}
                  placeholder="React, Node.js, PostgreSQL"
                />
                <span className="auth-field__hint">
                  Comma-separated. These are what a candidate&rsquo;s evidence gets scored against.
                </span>
              </label>

              <div className="modal__footer">
                <button type="button" className="btn-secondary" onClick={closeModal}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? 'Saving…' : modal.type === 'edit' ? 'Save Changes' : 'Post Job'}
                </button>
              </div>
          </form>
        </Modal>
      )}
    </DashboardLayout>
  );
}
