import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import Logo from '../components/Logo.jsx';
import { AuthProviderButtons } from '../components/ProviderIcons.jsx';
import { authApi } from '../lib/api.js';
import { authErrorMessage } from '../lib/authErrors.js';
import { useAuth, ROLE_HOME } from '../context/AuthContext.jsx';

const EMPTY_FORM = {
  firstName: '',
  lastName: '',
  email: '',
  password: '',
  confirmPassword: '',
};

/**
 * Sign-up screen. Email/password, or "Sign up with Google" / "Sign up with
 * GitHub" (SRS §1.4.2, FR 1/2). Signing in to an existing account lives on
 * its own page — see Login.jsx.
 */
export default function Signup() {
  const { user, status, loadUser } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const queryError = params.get('error');

  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Already signed in → straight to the role dashboard.
  useEffect(() => {
    if (status === 'authed' && user) {
      navigate(ROLE_HOME[user.role] || '/student', { replace: true });
    }
  }, [status, user, navigate]);

  function updateField(field) {
    return (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setFormError('');

    if (!form.firstName.trim()) {
      return setFormError('First name is required.');
    }
    if (form.password.length < 8) {
      return setFormError('Password must be at least 8 characters.');
    }
    if (form.password !== form.confirmPassword) {
      return setFormError('Passwords do not match.');
    }

    setSubmitting(true);
    try {
      await authApi.register({
        email: form.email,
        password: form.password,
        firstName: form.firstName,
        lastName: form.lastName,
      });
      const me = await loadUser();
      navigate(ROLE_HOME[me?.role] || '/student', { replace: true });
    } catch (err) {
      setFormError(err.message || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  const bannerError = formError || authErrorMessage(queryError);

  return (
    <div className="auth-screen">
      <div className="auth-shell">
        <Link to="/" className="auth-back">
          &larr; Back to home
        </Link>
        <div className="auth-card card">
          <span className="brand">
            <Logo showText subtitle="AI Job Readiness Scoring" />
          </span>

          <h1>Create your DevScore account</h1>
          <p>
            Verify your software engineering skills with evidence from your
            resume and GitHub activity.
          </p>

          {bannerError && <div className="auth-error">{bannerError}</div>}

          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="auth-form__row">
              <label className="auth-field">
                <span>First name</span>
                <input
                  type="text"
                  value={form.firstName}
                  onChange={updateField('firstName')}
                  autoComplete="given-name"
                  required
                />
              </label>
              <label className="auth-field">
                <span>Last name</span>
                <input
                  type="text"
                  value={form.lastName}
                  onChange={updateField('lastName')}
                  autoComplete="family-name"
                />
              </label>
            </div>

            <label className="auth-field">
              <span>Email</span>
              <input
                type="email"
                value={form.email}
                onChange={updateField('email')}
                autoComplete="email"
                required
              />
            </label>

            <label className="auth-field">
              <span>Password</span>
              <input
                type="password"
                value={form.password}
                onChange={updateField('password')}
                autoComplete="new-password"
                minLength={8}
                required
              />
            </label>

            <label className="auth-field">
              <span>Confirm password</span>
              <input
                type="password"
                value={form.confirmPassword}
                onChange={updateField('confirmPassword')}
                autoComplete="new-password"
                required
              />
            </label>

            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? 'Please wait…' : 'Create account'}
            </button>
          </form>

          <div className="auth-divider">
            <span>or continue with</span>
          </div>

          <AuthProviderButtons
            onGoogle={authApi.startGoogleLogin}
            onGithub={authApi.startGithubLogin}
          />

          <p className="auth-switch">
            Already have an account? <Link to="/login">Sign in</Link>
          </p>

          <p className="auth-fineprint">
            By continuing you agree to the Informed Consent and Privacy Policy.
          </p>
        </div>
      </div>
    </div>
  );
}
