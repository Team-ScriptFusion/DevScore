import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import Logo from '../components/Logo.jsx';
import AuthAside from '../components/AuthAside.jsx';
import { AuthProviderButtons } from '../components/ProviderIcons.jsx';
import { authApi } from '../lib/api.js';
import { authErrorMessage } from '../lib/authErrors.js';
import { useAuth, ROLE_HOME } from '../context/AuthContext.jsx';

const EMPTY_FORM = { email: '', password: '' };

/**
 * Sign-in screen. Email/password, or "Sign in with Google" / "Sign in with
 * GitHub" (SRS §1.4.1, FR 11/12). Registration lives on its own page — see
 * Signup.jsx.
 */
export default function Login() {
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
    setSubmitting(true);
    try {
      await authApi.login({ email: form.email, password: form.password });
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
      <div className="auth-layout">
        <section className="auth-panel">
          <div className="auth-panel__inner">
            <Link to="/" className="auth-back">
              &larr; Back to home
            </Link>
            <span className="brand">
              <Logo height={30} subtitle="AI Job Readiness Scoring" />
            </span>

            <h1>Sign in to DevScore</h1>
            <p className="auth-lead">
              Verify your software engineering skills with evidence from your
              resume and GitHub activity.
            </p>

            {bannerError && <div className="auth-error">{bannerError}</div>}

            <form className="auth-form" onSubmit={handleSubmit}>
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
                  autoComplete="current-password"
                  required
                />
              </label>

              <button type="submit" className="btn-primary btn-block" disabled={submitting}>
                {submitting ? 'Please wait…' : 'Sign in'}
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
              Don&rsquo;t have an account? <Link to="/signup">Sign up</Link>
            </p>

            <p className="auth-fineprint">
              By continuing you agree to the Informed Consent and Privacy Policy.
            </p>
          </div>
        </section>

        <AuthAside variant="login" />
      </div>
    </div>
  );
}
