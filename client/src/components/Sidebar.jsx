import { NavLink } from 'react-router-dom';
import Logo from './Logo.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import {
  ResumeIcon,
  GithubMiningIcon,
  ScoreIcon,
  EvidenceGapIcon,
} from './FeatureIcons.jsx';
import { BriefcaseIcon, CheckBadgeIcon, ClockIcon, CloseIcon } from './DashboardIcons.jsx';

function LogoutIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M15 17v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10 12h11M18 9l3 3-3 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * Role-aware navigation. Links are grouped into labelled sections so a student
 * can tell "where am I" from "what do I still have to do" — the flat list read
 * as five equally-weighted destinations.
 *
 * Screens not yet built stay visible as explicitly-disabled entries with a
 * "Soon" pill, rather than dimmed links that look broken.
 */
export const NAV_BY_ROLE = {
  student: {
    subtitle: 'Candidate Portal',
    sections: [
      {
        links: [{ to: '/student', label: 'Dashboard', end: true, Icon: EvidenceGapIcon }],
      },
      {
        label: 'Your profile',
        links: [
          { to: '/student/jobs', label: 'Job Roles', Icon: BriefcaseIcon },
          { to: '/student/resume', label: 'Upload Resume', Icon: ResumeIcon },
          { to: '/student/github', label: 'Connect GitHub', Icon: GithubMiningIcon },
          { to: '/student/skills', label: 'Skills Status', Icon: CheckBadgeIcon },
        ],
      },
    ],
  },
  recruiter: {
    subtitle: 'Recruiter Portal',
    sections: [
      {
        links: [{ to: '/recruiter', label: 'Dashboard', end: true, Icon: EvidenceGapIcon }],
      },
      {
        label: 'Hiring',
        links: [
          { to: '/recruiter/jobs', label: 'Job Postings', Icon: BriefcaseIcon },
          { to: '/recruiter/scores', label: 'Scores', disabled: true, Icon: ScoreIcon },
        ],
      },
    ],
  },
  admin: {
    subtitle: 'Admin Portal',
    sections: [
      {
        links: [
          { to: '/admin', label: 'Dashboard', end: true, Icon: EvidenceGapIcon },
          { to: '/admin/audit-log', label: 'Audit Log', disabled: true, Icon: ClockIcon },
        ],
      },
    ],
  },
};

export function navConfigFor(role) {
  return NAV_BY_ROLE[role] || NAV_BY_ROLE.student;
}

/** Flat link list — used by the topbar breadcrumb to name the current screen. */
export function labelForPath(role, pathname) {
  const links = navConfigFor(role).sections.flatMap((s) => s.links);
  const exact = links.find((l) => l.to === pathname);
  if (exact) return exact.label;
  // Detail routes (/recruiter/candidates/:id) have no nav entry of their own.
  const prefix = links
    .filter((l) => l.to !== '/' && pathname.startsWith(`${l.to}/`))
    .sort((a, b) => b.to.length - a.to.length)[0];
  return prefix?.label || null;
}

export default function Sidebar({ open = false, onClose }) {
  const { user, logout } = useAuth();
  const config = navConfigFor(user?.role);

  return (
    <aside className={`sidebar${open ? ' is-open' : ''}`} id="app-sidebar">
      <div className="sidebar__top">
        <Logo subtitle={config.subtitle} />
        {/* only rendered as a control on mobile, where the sidebar is a drawer */}
        <button
          type="button"
          className="sidebar__dismiss"
          onClick={onClose}
          aria-label="Close navigation"
        >
          <CloseIcon />
        </button>
      </div>

      <nav className="sidebar__nav" aria-label="Main">
        {config.sections.map((section, i) => (
          <div className="sidebar__section" key={section.label || i}>
            {section.label && (
              <span className="sidebar__section-label">{section.label}</span>
            )}
            {section.links.map((link) =>
              link.disabled ? (
                <span
                  key={link.to}
                  className="sidebar__link sidebar__link--disabled"
                  title="Available in a later implementation phase"
                >
                  <link.Icon />
                  <span className="sidebar__link-label">{link.label}</span>
                  <span className="sidebar__soon">Soon</span>
                </span>
              ) : (
                <NavLink
                  key={link.to}
                  to={link.to}
                  end={link.end}
                  title={link.label}
                  onClick={onClose}
                  className={({ isActive }) => `sidebar__link${isActive ? ' is-active' : ''}`}
                >
                  <link.Icon />
                  <span className="sidebar__link-label">{link.label}</span>
                </NavLink>
              ),
            )}
          </div>
        ))}
      </nav>

      <button
        type="button"
        className="sidebar__logout"
        onClick={logout}
        title="Logout"
        aria-label="Logout"
      >
        <LogoutIcon />
        <span className="sidebar__link-label">Logout</span>
      </button>
    </aside>
  );
}
