import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import StatCard from '../components/StatCard.jsx';
import { InlineLoader } from '../components/Spinner.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { recruiterApi } from '../lib/api.js';
import {
  BriefcaseIcon,
  CandidatesIcon,
  CheckBadgeIcon,
} from '../components/DashboardIcons.jsx';

function initials(name) {
  return (name || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0].toUpperCase())
    .join('');
}

function StatusBadge({ verified }) {
  return (
    <span className={`badge ${verified ? 'badge--verified' : 'badge--missing'}`}>
      {verified ? 'Verified' : 'Missing'}
    </span>
  );
}

const READINESS_BADGE = {
  pending: 'badge--pending',
  success: 'badge--verified',
  failed: 'badge--missing',
};

function ReadinessBadge({ status, score, band }) {
  if (status === 'success') {
    return (
      <span className={`badge ${READINESS_BADGE.success}`} title={band}>
        {score} / 100
      </span>
    );
  }
  if (status === 'pending') {
    return <span className={`badge ${READINESS_BADGE.pending}`}>Scoring…</span>;
  }
  if (status === 'failed') {
    return <span className={`badge ${READINESS_BADGE.failed}`}>Failed</span>;
  }
  return <span className="muted">—</span>;
}

const SKILLS_PREVIEW_LIMIT = 4;

function SkillsPreview({ status, byCategory }) {
  if (status !== 'success') return <span className="muted">—</span>;
  const flat = Object.values(byCategory || {}).flat();
  if (flat.length === 0) return <span className="muted">—</span>;

  const shown = flat.slice(0, SKILLS_PREVIEW_LIMIT);
  const remaining = flat.length - shown.length;
  return (
    <div className="skill-chips skill-chips--inline">
      {shown.map((skill) => (
        <span className="skill-chip" key={skill}>
          {skill}
        </span>
      ))}
      {remaining > 0 && <span className="skill-chip skill-chip--more">+{remaining}</span>}
    </div>
  );
}

/**
 * Recruiter dashboard (FR 8, 47-48) — adapted from the Figma "Recruiter
 * Dashboard" frame. Stat cards and the candidate table are wired to real
 * student data (resume/GitHub verification state); the Figma mock's
 * fabricated "vs last month" trends and "Scores Generated" count were
 * dropped since no historical or scoring data exists yet.
 */
export default function RecruiterDashboard() {
  const { user } = useAuth();
  const firstName = user.firstName || 'there';

  const [candidates, setCandidates] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeJobId, setActiveJobId] = useState('all');

  useEffect(() => {
    (async () => {
      try {
        const { candidates: rows, jobs: jobRows, stats: s } =
          await recruiterApi.listCandidates();
        setCandidates(rows);
        setJobs(jobRows);
        setStats(s);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Rows are per-application, so filtering by job is a plain client-side pass.
  const visible =
    activeJobId === 'all' ? candidates : candidates.filter((c) => c.jobId === activeJobId);

  return (
    <DashboardLayout>
      <h1 className="page-title">Welcome back, {firstName}!</h1>
      <p className="page-subtitle">
        Evaluate candidates with verified skill insights and AI-powered
        readiness scoring to make confident hiring decisions.
      </p>

      {!loading && stats && (
        <div className="stat-grid">
          <StatCard label="Open Roles" value={stats.openJobs} Icon={BriefcaseIcon} />
          <StatCard label="Total Candidates" value={stats.total} Icon={CandidatesIcon} />
          <StatCard label="Profiles Ready" value={stats.profileComplete} Icon={CheckBadgeIcon} />
        </div>
      )}

      <div className="card table-card" style={{ marginBottom: 20 }}>
        <div className="table-card__header">
          <h3>Your Job Postings</h3>
          <Link to="/recruiter/jobs" className="btn-primary table-card__cta">
            + Post a Job
          </Link>
        </div>

        {loading ? (
          <InlineLoader className="table-card__empty" />
        ) : jobs.length === 0 ? (
          <p className="muted table-card__empty">
            You haven&rsquo;t posted any roles yet. Candidates apply to a specific role, so
            post one to start receiving applicants.
          </p>
        ) : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Applicants</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.slice(0, 5).map((j) => (
                    <tr key={j.id}>
                      <td>{j.title}</td>
                      <td>
                        <span
                          className={`badge ${j.status === 'open' ? 'badge--verified' : 'badge--neutral'}`}
                        >
                          {j.status === 'open' ? 'Open' : 'Closed'}
                        </span>
                      </td>
                      <td>{j.applicantCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted table-card__footer">
              <Link to="/recruiter/jobs">Manage all postings</Link>
            </p>
          </>
        )}
      </div>

      <div className="card table-card">
        <div className="table-card__header">
          <div>
            <h3>Candidates</h3>
            {jobs.length > 0 && (
              <div className="job-filter">
                <button
                  type="button"
                  className={`job-filter__chip ${activeJobId === 'all' ? 'is-active' : ''}`}
                  onClick={() => setActiveJobId('all')}
                >
                  All ({candidates.length})
                </button>
                {jobs.map((j) => (
                  <button
                    type="button"
                    key={j.id}
                    className={`job-filter__chip ${activeJobId === j.id ? 'is-active' : ''}`}
                    onClick={() => setActiveJobId(j.id)}
                  >
                    {j.title} ({j.applicantCount})
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {loading ? (
          <InlineLoader className="table-card__empty" />
        ) : jobs.length === 0 ? (
          <p className="muted table-card__empty">
            Post a job role first — candidates reach you by applying to one.
          </p>
        ) : visible.length === 0 ? (
          <p className="muted table-card__empty">
            {activeJobId === 'all'
              ? 'No one has applied to your roles yet.'
              : 'No applications for this role yet.'}
          </p>
        ) : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Applied For</th>
                    <th>Email</th>
                    <th>Resume</th>
                    <th>GitHub</th>
                    <th>Skills</th>
                    <th>Readiness</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {/* keyed by application, not candidate — a student who applied
                      to two of these roles legitimately appears twice */}
                  {visible.map((c) => (
                    <tr key={c.applicationId}>
                      <td>
                        <div className="data-table__person">
                          <span className="avatar avatar--sm">{initials(c.name)}</span>
                          {c.name}
                        </div>
                      </td>
                      <td>{c.jobTitle}</td>
                      <td>{c.email}</td>
                      <td>
                        <StatusBadge verified={c.resumeVerified} />
                      </td>
                      <td>
                        <StatusBadge verified={c.githubVerified} />
                      </td>
                      <td>
                        <SkillsPreview status={c.skillsStatus} byCategory={c.claimedSkills} />
                      </td>
                      <td>
                        <ReadinessBadge
                          status={c.readinessStatus}
                          score={c.readinessScore}
                          band={c.readinessBand}
                        />
                      </td>
                      <td className="data-table__actions">
                        <Link to={`/recruiter/candidates/${c.id}`} className="btn-secondary">
                          View Profile
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted table-card__footer">
              Showing {visible.length} application{visible.length === 1 ? '' : 's'}
            </p>
          </>
        )}
      </div>
    </DashboardLayout>
  );
}
