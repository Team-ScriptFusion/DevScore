import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import StatCard from '../components/StatCard.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { recruiterApi } from '../lib/api.js';
import { CandidatesIcon, CheckBadgeIcon, ClockIcon } from '../components/DashboardIcons.jsx';

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
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { candidates: rows, stats: s } = await recruiterApi.listCandidates();
        setCandidates(rows);
        setStats(s);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <DashboardLayout>
      <h1 className="page-title">Welcome back, {firstName}!</h1>
      <p className="page-subtitle">
        Evaluate candidates with verified skill insights and AI-powered
        readiness scoring to make confident hiring decisions.
      </p>

      {!loading && stats && (
        <div className="stat-grid">
          <StatCard label="Total Candidates" value={stats.total} Icon={CandidatesIcon} />
          <StatCard label="Profiles Ready" value={stats.profileComplete} Icon={CheckBadgeIcon} />
          <StatCard label="Awaiting Setup" value={stats.total - stats.profileComplete} Icon={ClockIcon} />
        </div>
      )}

      <div className="card table-card">
        <div className="table-card__header">
          <h3>Candidates</h3>
        </div>

        {loading ? (
          <p className="muted table-card__empty">Loading…</p>
        ) : candidates.length === 0 ? (
          <p className="muted table-card__empty">
            No candidates have signed up yet.
          </p>
        ) : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Resume</th>
                    <th>GitHub</th>
                    <th>Skills</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <div className="data-table__person">
                          <span className="avatar avatar--sm">{initials(c.name)}</span>
                          {c.name}
                        </div>
                      </td>
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
              Showing {candidates.length} candidate{candidates.length === 1 ? '' : 's'}
            </p>
          </>
        )}
      </div>
    </DashboardLayout>
  );
}
