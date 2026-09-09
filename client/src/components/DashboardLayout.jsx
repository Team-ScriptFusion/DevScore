import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import Sidebar, { labelForPath, navConfigFor } from './Sidebar.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useSearchBox } from '../context/SearchContext.jsx';
import { SearchIcon, CloseIcon, MenuIcon } from './DashboardIcons.jsx';

/** Initials fallback avatar when the OAuth provider gives no photo. */
function initials(user) {
  const a = user.firstName?.[0] || user.email?.[0] || '?';
  const b = user.lastName?.[0] || '';
  return (a + b).toUpperCase();
}

/**
 * The topbar search only appears once a page has claimed it via `useSearch`.
 * Screens with nothing to filter get no control at all, rather than an input
 * that accepts typing and does nothing with it.
 */
function TopbarSearch() {
  const { query, setQuery, placeholder, active } = useSearchBox();
  if (!active) return null;

  return (
    <div className="topbar__search-wrap">
      <span className="topbar__search-icon">
        <SearchIcon />
      </span>
      <input
        className="topbar__search"
        type="search"
        value={query}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(e) => setQuery(e.target.value)}
      />
      {query && (
        <button
          type="button"
          className="topbar__search-clear"
          onClick={() => setQuery('')}
          aria-label="Clear search"
        >
          <CloseIcon size={14} />
        </button>
      )}
    </div>
  );
}

/**
 * Shared authenticated shell (sidebar + topbar + content) used by every role
 * dashboard. Feature screens render into `children` and may claim the topbar
 * search box via `useSearch` — the provider for that lives in App.jsx, above
 * the routes, since a page calls the hook before this layout has mounted.
 */
export default function DashboardLayout({ children }) {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const [navOpen, setNavOpen] = useState(false);

  const portal = navConfigFor(user?.role).subtitle;
  const page = labelForPath(user?.role, pathname);

  // The drawer is a navigation surface — leaving it open over the destination
  // after a link is tapped would hide the thing the user just asked for.
  useEffect(() => setNavOpen(false), [pathname]);

  useEffect(() => {
    if (!navOpen) return undefined;
    const onKey = (e) => e.key === 'Escape' && setNavOpen(false);
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [navOpen]);

  return (
    <div className={`app-shell${navOpen ? ' nav-open' : ''}`}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      {navOpen && (
        <div className="sidebar-backdrop" onClick={() => setNavOpen(false)} aria-hidden="true" />
      )}

      <div className="app-main">
        <header className="topbar">
          <div className="topbar__lead">
            <button
              type="button"
              className="topbar__menu"
              onClick={() => setNavOpen(true)}
              aria-label="Open navigation"
              aria-expanded={navOpen}
              aria-controls="app-sidebar"
            >
              <MenuIcon />
            </button>
            <nav className="breadcrumb" aria-label="Breadcrumb">
              <span className="breadcrumb__root">{portal}</span>
              {page && (
                <>
                  <span className="breadcrumb__sep" aria-hidden="true">
                    /
                  </span>
                  <span className="breadcrumb__current" aria-current="page">
                    {page}
                  </span>
                </>
              )}
            </nav>
          </div>

          <TopbarSearch />

          <div className="topbar__user">
            <div className="topbar__user-meta">
              <div className="topbar__user-name">{user.fullName || user.email}</div>
              <div className="topbar__user-role">{user.role}</div>
            </div>
            {user.avatarUrl ? (
              <img className="avatar" src={user.avatarUrl} alt="" />
            ) : (
              <span className="avatar">{initials(user)}</span>
            )}
          </div>
        </header>

        <main className="app-content" id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
