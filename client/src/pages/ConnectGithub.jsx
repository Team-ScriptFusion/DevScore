import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import PageHeader from '../components/PageHeader.jsx';
import { InlineLoader } from '../components/Spinner.jsx';
import { githubApi, jobsApi } from '../lib/api.js';
import { relativeDate, absoluteDate } from '../lib/format.js';
import { GithubMiningIcon } from '../components/FeatureIcons.jsx';
import { LockIcon } from '../components/DashboardIcons.jsx';

const ERROR_MESSAGES = {
  github_permission_denied: 'GitHub connection was cancelled — permission was not granted.',
  github_invalid_callback: 'GitHub did not return the expected authorization code.',
  github_invalid_state: 'That connection request expired or is invalid. Please try again.',
  github_token_exchange_failed: 'GitHub rejected the connection request. Please try again.',
  github_profile_fetch_failed: 'Could not read your GitHub profile. Please try again.',
  github_connection_failed: 'Something went wrong connecting your GitHub account.',
  select_role_first: 'Select a job role before connecting GitHub.',
};

/**
 * Connect GitHub Account screen (FR 9/10, use case "Connect GitHub Account").
 * Kicks off the GitHub OAuth flow and reports the resulting connection state.
 */
export default function ConnectGithub() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [status, setStatus] = useState(null);
  // Optimistic until we know otherwise, so an unrelated fetch failure (e.g.
  // job_applications not migrated yet) never flashes a false "locked" state.
  const [roleApplied, setRoleApplied] = useState(true);
  const [loading, setLoading] = useState(true);
  const [disconnecting, setDisconnecting] = useState(false);

  const callbackError = searchParams.get('error');
  const justConnected = searchParams.get('connected') === '1';

  useEffect(() => {
    (async () => {
      const [s, a] = await Promise.allSettled([githubApi.status(), jobsApi.listApplied()]);
      if (s.status === 'fulfilled') setStatus(s.value);
      if (a.status === 'fulfilled') setRoleApplied(a.value.applications.length > 0);
      setLoading(false);
      if (callbackError || justConnected) {
        searchParams.delete('error');
        searchParams.delete('connected');
        setSearchParams(searchParams, { replace: true });
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, []);

  async function handleDisconnect() {
    setDisconnecting(true);
    try {
      await githubApi.disconnect();
      setStatus(await githubApi.status());
    } finally {
      setDisconnecting(false);
    }
  }

  return (
    <DashboardLayout>
      <PageHeader
        title="Connect GitHub Account"
        subtitle="Link your GitHub profile so recruiters can verify your resume claims against your real coding activity."
      />

      {callbackError && (
        <div className="alert alert--error alert--stack" role="alert">
          {ERROR_MESSAGES[callbackError] || 'Could not connect your GitHub account.'}
        </div>
      )}
      {justConnected && !callbackError && (
        <div className="alert alert--success alert--stack" role="status">
          GitHub account linked successfully.
        </div>
      )}

      <div className="card card--narrow">
        {loading ? (
          <InlineLoader label="Checking connection status…" />
        ) : status?.connected ? (
          <div className="state-panel">
            <span className="state-panel__icon state-panel__icon--done">
              <GithubMiningIcon />
            </span>
            <div className="state-panel__body">
              <span className="badge badge--verified">Connected</span>
              <h3 className="state-panel__title">@{status.username}</h3>
              <p className="muted" title={absoluteDate(status.connectedAt)}>
                {status.connectedAt ? `Linked ${relativeDate(status.connectedAt)}` : ''}
              </p>
              <div className="state-panel__actions">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={handleDisconnect}
                  disabled={disconnecting}
                >
                  {disconnecting ? 'Disconnecting…' : 'Disconnect GitHub'}
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
                Your GitHub evidence is reviewed against the roles you&rsquo;ve
                applied for, so we need to know which ones those are.
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
              <GithubMiningIcon />
            </span>
            <div className="state-panel__body">
              <h3 className="state-panel__title">GitHub not connected</h3>
              <p className="muted">
                We only request read access to your public repositories — we
                never modify or delete your code.
              </p>
              <div className="state-panel__actions">
                <button
                  type="button"
                  className="btn-primary"
                  onClick={githubApi.startConnect}
                >
                  Connect GitHub Account
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}
