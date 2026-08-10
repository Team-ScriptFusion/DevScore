import { NavLink } from 'react-router-dom';
import Logo from './Logo.jsx';
import { useAuth } from '../context/AuthContext.jsx';

/**
 * Role-aware navigation shell matching the Figma dashboard sidebar.
 * Screens not yet built (Candidates, Scores, Skills Status, …) appear as
 * inactive placeholders until their modules land.
 */
const NAV_BY_ROLE = {
  student: {
    subtitle: 'Candidate Portal',
    links: [
      { to: '/student', label: 'Dashboard', end: true },
      { to: '/student/resume', label: 'Upload Resume' },
      { to: '/student/github', label: 'Connect GitHub' },
      { to: '/student/skills', label: 'Skills Status', disabled: true },
    ],
  },
  recruiter: {
    subtitle: 'Recruiter Portal',
    links: [
      { to: '/recruiter', label: 'Dashboard', end: true },
      { to: '/recruiter/candidates', label: 'Candidates', disabled: true },
      { to: '/recruiter/scores', label: 'Scores', disabled: true },
    ],
  },
  admin: {
    subtitle: 'Admin Portal',
    links: [
      { to: '/admin', label: 'Dashboard', end: true },
      { to: '/admin/users', label: 'Users', disabled: true },
    ],
  },
};

export default function Sidebar() {
  const { user, logout } = useAuth();
  const config = NAV_BY_ROLE[user?.role] || NAV_BY_ROLE.student;

  return (
    <aside className="sidebar">
      <Logo subtitle={config.subtitle} />

      <nav className="sidebar__nav">
        {config.links.map((link) =>
          link.disabled ? (
            <span
              key={link.to}
              className="sidebar__link"
              style={{ opacity: 0.5, cursor: 'not-allowed' }}
              title="Available in a later implementation phase"
            >
              <span>{link.label}</span>
            </span>
          ) : (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                `sidebar__link${isActive ? ' is-active' : ''}`
              }
            >
              <span>{link.label}</span>
            </NavLink>
          ),
        )}
      </nav>

      <button type="button" className="sidebar__logout" onClick={logout}>
        <span>Logout</span>
      </button>
    </aside>
  );
}
