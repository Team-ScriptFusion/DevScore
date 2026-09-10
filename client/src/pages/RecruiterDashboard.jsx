import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import PageHeader from '../components/PageHeader.jsx';
import StatCard from '../components/StatCard.jsx';
import EmptyState from '../components/EmptyState.jsx';
import Meter from '../components/Meter.jsx';
import ScoreRing from '../components/ScoreRing.jsx';
import { SkeletonRows, SkeletonCards, LoadingAnnouncement } from '../components/Skeleton.jsx';
import useReveal from '../hooks/useReveal.js';
import useSortableRows from '../hooks/useSortableRows.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useSearch, matches } from '../context/SearchContext.jsx';
import { recruiterApi } from '../lib/api.js';
import { initials, avatarTint } from '../lib/format.js';
import {
  BriefcaseIcon,
  CandidatesIcon,
  CheckBadgeIcon,
  SortIcon,
  PlusIcon,
  InboxIcon,
  SparkIcon,
} from '../components/DashboardIcons.jsx';

function StatusBadge({ verified }) {
  return (
    <span className={`badge ${verified ? 'badge--verified' : 'badge--missing'}`}>
      {verified ? 'Verified' : 'Missing'}
    </span>
  );
}

/**
 * Readiness in a table cell: a small ring plus the figure and band. The ring
 * gives the column a scannable shape, the number and band keep the meaning off
 * colour alone.
 */
function ReadinessCell({ status, score, band }) {
  if (status === 'success') {
    return (
      <div className="data-table__score">
        <ScoreRing value={score} size="sm" showValue={false} label={`${score} out of 100`} />
        <span className="data-table__score-value">
          {score}
          {band && <span className="data-table__score-band">{band}</span>}
        </span>
      </div>
    );
  }
  if (status === 'pending') return <span className="badge badge--pending">Scoring</span>;
  if (status === 'failed') return <span className="badge badge--missing">Failed</span>;
  return <span className="muted">—</span>;
}

const SKILLS_PREVIEW_LIMIT = 4;

function flatSkills(byCategory) {
  return Object.values(byCategory || {}).flat();
}

function SkillsPreview({ status, byCategory }) {
  if (status !== 'success') return <span className="muted">—</span>;
  const flat = flatSkills(byCategory);
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

/** Sortable column header. The button is the whole label, so the hit area matches. */
function SortableTh({ label, colKey, sort, children }) {
  return (
    <th aria-sort={sort.ariaSort(colKey)}>
      <button type="button" className="data-table__sort" onClick={() => sort.toggle(colKey)}>
        {label}
        <SortIcon dir={sort.dirFor(colKey)} />
      </button>
      {children}
    </th>
  );
}

/**
 * Recruiter dashboard (FR 8, 47-48). Stat cards and the candidate table are
 * wired to real student data (resume/GitHub verification state); no "vs last
 * month" trends are shown because no historical data exists to compare against.
 */
export default function RecruiterDashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const firstName = user.firstName || 'there';

  const [candidates, setCandidates] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeJobId, setActiveJobId] = useState('all');

  const query = useSearch('Search candidates by name, email or skill…');

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
  const filtered = useMemo(
    () =>
      candidates
        .filter((c) => activeJobId === 'all' || c.jobId === activeJobId)
        .filter((c) => matches(query, c.name, c.email, c.jobTitle, flatSkills(c.claimedSkills).join(' '))),
    [candidates, activeJobId, query],
  );

  const sort = useSortableRows(filtered, {
    name: (c) => c.name,
    jobTitle: (c) => c.jobTitle,
    // unscored candidates sort last in both directions (see useSortableRows)
    readiness: (c) => (c.readinessStatus === 'success' ? c.readinessScore : null),
  });

  /**
   * Averaged over scored candidates only — including unscored rows as zeroes
   * would drag the figure down and misrepresent the pool.
   */
  const avgReadiness = useMemo(() => {
    const scored = candidates.filter((c) => c.readinessStatus === 'success');
    if (scored.length === 0) return null;
    const total = scored.reduce((sum, c) => sum + (c.readinessScore || 0), 0);
    return { value: Math.round(total / scored.length), count: scored.length };
  }, [candidates]);

  const busiestJob = Math.max(1, ...jobs.map((j) => j.applicantCount || 0));
  const statsRef = useReveal([loading], { enabled: !loading });

  return (
    <DashboardLayout>
      <PageHeader
        title={`Welcome back, ${firstName}!`}
        subtitle="Evaluate candidates with verified skill insights and AI-powered readiness scoring to make confident hiring decisions."
        actions={
          <Link to="/recruiter/jobs" className="btn-primary">
            <PlusIcon />
            Post a Job
          </Link>
        }
      />

      {loading ? (
        <>
          <SkeletonCards n={4} />
          <LoadingAnnouncement label="Loading dashboard" />
        </>
      ) : (
        stats && (
          <div className="stat-grid" ref={statsRef}>
            <StatCard label="Open Roles" value={stats.openJobs} Icon={BriefcaseIcon} />
            <StatCard label="Total Candidates" value={stats.total} Icon={CandidatesIcon} />
            <StatCard
              label="Profiles Ready"
              value={stats.profileComplete}
              Icon={CheckBadgeIcon}
              sublabel="Resume and GitHub both verified"
            />
            <StatCard
              label="Avg Readiness"
              value={avgReadiness ? avgReadiness.value : '—'}
              suffix={avgReadiness ? '/100' : null}
              Icon={SparkIcon}
              sublabel={
                avgReadiness
                  ? `Across ${avgReadiness.count} scored candidate${avgReadiness.count === 1 ? '' : 's'}`
                  : 'No candidates scored yet'
              }
            />
          </div>
        )
      )}

      <div className="card table-card card--stack">
        <div className="table-card__header">
          <h3>Your Job Postings</h3>
          <Link to="/recruiter/jobs" className="btn-primary table-card__cta">
            <PlusIcon />
            Post a Job
          </Link>
        </div>

        {loading ? (
          <SkeletonRows cols={3} rows={3} />
        ) : jobs.length === 0 ? (
          <EmptyState
            Icon={BriefcaseIcon}
            title="No postings yet"
            description="Candidates apply to a specific role, so post one to start receiving applicants."
            action={
              <Link to="/recruiter/jobs" className="btn-primary">
                Post your first role
              </Link>
            }
          />
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
                      <td>
                        {/* scaled against the busiest posting so the column ranks at a glance */}
                        <Meter
                          size="sm"
                          value={j.applicantCount}
                          max={busiestJob}
                          valueLabel={String(j.applicantCount)}
                          label={`${j.title} applicants`}
                        />
                      </td>
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

      <div className="card table-card card--stack">
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
          <SkeletonRows cols={6} rows={5} />
        ) : jobs.length === 0 ? (
          <EmptyState
            Icon={BriefcaseIcon}
            title="No candidates yet"
            description="Post a job role first — candidates reach you by applying to one."
            action={
              <Link to="/recruiter/jobs" className="btn-primary">
                Post a role
              </Link>
            }
          />
        ) : sort.rows.length === 0 ? (
          <EmptyState
            Icon={InboxIcon}
            title={query ? 'No matching candidates' : 'No applications yet'}
            description={
              query
                ? 'Nothing matches your search. Try a different name, email or skill.'
                : activeJobId === 'all'
                  ? 'No one has applied to your roles yet. Applications appear here as they arrive.'
                  : 'No applications for this role yet.'
            }
          />
        ) : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <SortableTh label="Name" colKey="name" sort={sort} />
                    <SortableTh label="Applied For" colKey="jobTitle" sort={sort} />
                    <th>Resume</th>
                    <th>GitHub</th>
                    <th>Skills</th>
                    <SortableTh label="Readiness" colKey="readiness" sort={sort} />
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {/* keyed by application, not candidate — a student who applied
                      to two of these roles legitimately appears twice */}
                  {sort.rows.map((c) => (
                    <tr
                      key={c.applicationId}
                      className="is-clickable"
                      onClick={(e) => {
                        // let the explicit link and any future row control win
                        if (e.target.closest('a, button')) return;
                        navigate(`/recruiter/candidates/${c.id}`);
                      }}
                    >
                      <td>
                        <div className="data-table__person">
                          <span className={`avatar avatar--sm avatar--tint-${avatarTint(c.name)}`}>
                            {initials(c.name)}
                          </span>
                          <span>
                            {c.name}
                            <span className="data-table__sub">{c.email}</span>
                          </span>
                        </div>
                      </td>
                      <td>{c.jobTitle}</td>
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
                        <ReadinessCell
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
              Showing {sort.rows.length} application{sort.rows.length === 1 ? '' : 's'}
              {query && ` matching “${query}”`}
            </p>
          </>
        )}
      </div>
    </DashboardLayout>
  );
}
