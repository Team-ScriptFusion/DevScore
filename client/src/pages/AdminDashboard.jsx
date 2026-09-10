import { useEffect, useMemo, useState } from 'react';
import DashboardLayout from '../components/DashboardLayout.jsx';
import PageHeader from '../components/PageHeader.jsx';
import StatCard from '../components/StatCard.jsx';
import EmptyState from '../components/EmptyState.jsx';
import Modal from '../components/Modal.jsx';
import { StackedMeter } from '../components/Meter.jsx';
import { SkeletonRows, SkeletonCards, LoadingAnnouncement } from '../components/Skeleton.jsx';
import useReveal from '../hooks/useReveal.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useSearch, matches } from '../context/SearchContext.jsx';
import { adminApi } from '../lib/api.js';
import { initials, avatarTint, relativeDate, absoluteDate } from '../lib/format.js';
import {
  UsersIcon,
  BriefcaseIcon,
  ShieldIcon,
  PlusIcon,
  CheckIcon,
  InboxIcon,
} from '../components/DashboardIcons.jsx';

const EMPTY_CREATE_FORM = { firstName: '', lastName: '', email: '' };
const EMPTY_PASSWORD_FORM = { mode: 'generate', password: '' };

/**
 * Admin dashboard (FR 8, 47-50). Admins are the only actor who can create a
 * recruiter login — recruiters cannot self-register (Signup.jsx always
 * creates a student). This screen covers that flow plus recruiter account
 * CRUD, including setting/resetting a recruiter's password.
 */
export default function AdminDashboard() {
  const { user } = useAuth();
  const firstName = user.firstName || 'Admin';

  const [stats, setStats] = useState(null);
  const [recruiters, setRecruiters] = useState([]);
  const [loading, setLoading] = useState(true);

  // modal: null | { type: 'create' } | { type: 'password', recruiter }
  const [modal, setModal] = useState(null);
  const [createForm, setCreateForm] = useState(EMPTY_CREATE_FORM);
  const [passwordForm, setPasswordForm] = useState(EMPTY_PASSWORD_FORM);
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null); // { recruiter, tempPassword }
  const [copied, setCopied] = useState(false);

  const query = useSearch('Search recruiters by name or email…');

  async function refresh() {
    const [s, r] = await Promise.all([adminApi.stats(), adminApi.listRecruiters()]);
    setStats(s);
    setRecruiters(r.recruiters);
  }

  useEffect(() => {
    (async () => {
      try {
        await refresh();
      } finally {
        setLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, []);

  function updateCreateField(field) {
    return (e) => setCreateForm((f) => ({ ...f, [field]: e.target.value }));
  }

  async function handleCreate(e) {
    e.preventDefault();
    setFormError('');
    if (!createForm.firstName.trim() || !createForm.email.trim()) {
      return setFormError('First name and email are required.');
    }

    setSubmitting(true);
    try {
      const res = await adminApi.createRecruiter(createForm);
      setResult({ recruiter: res.recruiter, tempPassword: res.tempPassword, isNew: true });
      setCreateForm(EMPTY_CREATE_FORM);
      await refresh();
    } catch (err) {
      setFormError(err.message || 'Could not create the recruiter account.');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSetPassword(e) {
    e.preventDefault();
    setFormError('');
    if (passwordForm.mode === 'choose' && passwordForm.password.length < 8) {
      return setFormError('Password must be at least 8 characters.');
    }

    setSubmitting(true);
    try {
      const payload = passwordForm.mode === 'choose' ? { password: passwordForm.password } : {};
      const res = await adminApi.setRecruiterPassword(modal.recruiter.id, payload);
      setResult({ recruiter: res.recruiter, tempPassword: res.tempPassword, isNew: false });
    } catch (err) {
      setFormError(err.message || 'Could not update the password.');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id, name) {
    if (!window.confirm(`Remove ${name}'s recruiter account? This cannot be undone.`)) return;
    await adminApi.deleteRecruiter(id);
    await refresh();
  }

  function closeModal() {
    setModal(null);
    setCreateForm(EMPTY_CREATE_FORM);
    setPasswordForm(EMPTY_PASSWORD_FORM);
    setFormError('');
    setResult(null);
    setCopied(false);
  }

  async function copyPassword() {
    try {
      await navigator.clipboard.writeText(result.tempPassword);
      setCopied(true);
    } catch {
      /* clipboard unavailable — the value is still selectable/visible */
    }
  }

  const visible = useMemo(
    () => recruiters.filter((r) => matches(query, r.fullName, r.email)),
    [recruiters, query],
  );

  const statsRef = useReveal([loading], { enabled: !loading });

  const modalTitle = result
    ? result.isNew
      ? 'Recruiter account created'
      : 'Password updated'
    : modal?.type === 'create'
      ? 'Add Recruiter'
      : 'Set Password';

  const modalDescription = result
    ? `Share these one-time credentials with ${result.recruiter.fullName || result.recruiter.email}. The password can’t be shown again after you close this.`
    : modal?.type === 'create'
      ? 'Creates a login for a recruiter. Only admins can do this — recruiters can’t sign themselves up.'
      : modal
        ? `For ${modal.recruiter.fullName || modal.recruiter.email}. This replaces their current password immediately.`
        : '';

  return (
    <DashboardLayout>
      <PageHeader
        title={`Welcome back, ${firstName}!`}
        subtitle="Manage recruiter access and monitor platform activity."
        actions={
          <button
            type="button"
            className="btn-primary"
            onClick={() => setModal({ type: 'create' })}
          >
            <PlusIcon />
            Add Recruiter
          </button>
        }
      />

      {loading ? (
        <>
          <SkeletonCards n={3} />
          <LoadingAnnouncement label="Loading platform stats" />
        </>
      ) : (
        stats && (
          <>
            <div className="stat-grid" ref={statsRef}>
              <StatCard label="Students" value={stats.students} Icon={UsersIcon} />
              <StatCard label="Recruiters" value={stats.recruiters} Icon={BriefcaseIcon} />
              <StatCard label="Admins" value={stats.admins} Icon={ShieldIcon} />
            </div>

            <div className="card card--stack">
              <div className="card-head">
                <div>
                  <h3>Platform Composition</h3>
                  <p className="muted">
                    How the {stats.students + stats.recruiters + stats.admins} accounts on
                    DevScore break down by role.
                  </p>
                </div>
              </div>
              <StackedMeter
                label="Accounts by role"
                segments={[
                  { key: 'students', label: 'Students', value: stats.students, tone: 'primary' },
                  { key: 'recruiters', label: 'Recruiters', value: stats.recruiters, tone: 'accent' },
                  { key: 'admins', label: 'Admins', value: stats.admins, tone: 'neutral' },
                ]}
              />
            </div>
          </>
        )
      )}

      <div className="card table-card card--stack">
        <div className="table-card__header">
          <h3>Recruiter Accounts</h3>
          <button
            type="button"
            className="btn-primary table-card__cta"
            onClick={() => setModal({ type: 'create' })}
          >
            <PlusIcon />
            Add Recruiter
          </button>
        </div>

        {loading ? (
          <SkeletonRows cols={4} rows={4} />
        ) : recruiters.length === 0 ? (
          <EmptyState
            Icon={BriefcaseIcon}
            title="No recruiter accounts yet"
            description="Recruiters can't sign themselves up — create the first account to give someone hiring access."
            action={
              <button
                type="button"
                className="btn-primary"
                onClick={() => setModal({ type: 'create' })}
              >
                Add the first recruiter
              </button>
            }
          />
        ) : visible.length === 0 ? (
          <EmptyState
            Icon={InboxIcon}
            title="No matching recruiters"
            description="Nothing matches your search. Try a different name or email address."
          />
        ) : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Created</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <div className="data-table__person">
                          <span
                            className={`avatar avatar--sm avatar--tint-${avatarTint(r.fullName || r.email)}`}
                          >
                            {initials(r.fullName || r.email)}
                          </span>
                          {r.fullName || '—'}
                        </div>
                      </td>
                      <td>{r.email}</td>
                      <td title={absoluteDate(r.createdAt)}>{relativeDate(r.createdAt)}</td>
                      <td className="data-table__actions">
                        <button
                          type="button"
                          className="btn-link"
                          onClick={() => setModal({ type: 'password', recruiter: r })}
                        >
                          Set Password
                        </button>
                        <button
                          type="button"
                          className="btn-link btn-link--danger"
                          onClick={() => handleDelete(r.id, r.fullName || r.email)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted table-card__footer">
              Showing {visible.length} account{visible.length === 1 ? '' : 's'}
              {query && ` matching “${query}”`}
            </p>
          </>
        )}
      </div>

      {modal && (
        <Modal title={modalTitle} description={modalDescription} onClose={closeModal}>
          {result ? (
            <>
              <div className="credential-box">
                <div className="credential-box__row">
                  <span className="credential-box__label">Email</span>
                  <span className="credential-box__value">{result.recruiter.email}</span>
                </div>
                <div className="credential-box__row">
                  <span className="credential-box__label">
                    {result.isNew ? 'Temporary password' : 'New password'}
                  </span>
                  <span className="credential-box__value credential-box__value--mono">
                    {result.tempPassword}
                  </span>
                </div>
                <button type="button" className="btn-secondary" onClick={copyPassword}>
                  {copied && <CheckIcon size={15} />}
                  {copied ? 'Copied!' : 'Copy password'}
                </button>
                {/* the label change alone is silent to a screen reader */}
                <span className="sr-only" role="status" aria-live="polite">
                  {copied ? 'Password copied to clipboard' : ''}
                </span>
              </div>
              <div className="modal__footer">
                <button type="button" className="btn-primary" onClick={closeModal}>
                  Done
                </button>
              </div>
            </>
          ) : modal.type === 'create' ? (
            <>
              {formError && (
                <div className="auth-error" role="alert">
                  {formError}
                </div>
              )}
              <form className="auth-form" onSubmit={handleCreate}>
                <div className="auth-form__row">
                  <label className="auth-field">
                    <span>First name</span>
                    <input
                      type="text"
                      value={createForm.firstName}
                      onChange={updateCreateField('firstName')}
                      required
                    />
                  </label>
                  <label className="auth-field">
                    <span>Last name</span>
                    <input
                      type="text"
                      value={createForm.lastName}
                      onChange={updateCreateField('lastName')}
                    />
                  </label>
                </div>
                <label className="auth-field">
                  <span>Email</span>
                  <input
                    type="email"
                    value={createForm.email}
                    onChange={updateCreateField('email')}
                    required
                  />
                </label>
                <div className="modal__footer">
                  <button type="button" className="btn-secondary" onClick={closeModal}>
                    Cancel
                  </button>
                  <button type="submit" className="btn-primary" disabled={submitting}>
                    {submitting ? 'Creating…' : 'Create Recruiter'}
                  </button>
                </div>
              </form>
            </>
          ) : (
            <>
              {formError && (
                <div className="auth-error" role="alert">
                  {formError}
                </div>
              )}
              <form className="auth-form" onSubmit={handleSetPassword}>
                <div className="radio-group">
                  <label className="radio-option">
                    <input
                      type="radio"
                      name="password-mode"
                      checked={passwordForm.mode === 'generate'}
                      onChange={() => setPasswordForm((f) => ({ ...f, mode: 'generate' }))}
                    />
                    <span>Generate a random password</span>
                  </label>
                  <label className="radio-option">
                    <input
                      type="radio"
                      name="password-mode"
                      checked={passwordForm.mode === 'choose'}
                      onChange={() => setPasswordForm((f) => ({ ...f, mode: 'choose' }))}
                    />
                    <span>Set a specific password</span>
                  </label>
                </div>
                {passwordForm.mode === 'choose' && (
                  <label className="auth-field">
                    <span>New password</span>
                    <input
                      type="text"
                      value={passwordForm.password}
                      onChange={(e) =>
                        setPasswordForm((f) => ({ ...f, password: e.target.value }))
                      }
                      minLength={8}
                      placeholder="At least 8 characters"
                      autoComplete="new-password"
                      required
                    />
                  </label>
                )}
                <div className="modal__footer">
                  <button type="button" className="btn-secondary" onClick={closeModal}>
                    Cancel
                  </button>
                  <button type="submit" className="btn-primary" disabled={submitting}>
                    {submitting ? 'Saving…' : 'Update Password'}
                  </button>
                </div>
              </form>
            </>
          )}
        </Modal>
      )}
    </DashboardLayout>
  );
}
