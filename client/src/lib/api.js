/**
 * Thin API client for the DevScore backend. The session travels only as an
 * httpOnly cookie (SDS §4.7.2) — never store the session token in JS-readable
 * storage. `credentials: 'include'` is what actually authenticates requests.
 */
async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    credentials: 'include',
  });

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      message = body.error || message;
    } catch {
      /* non-JSON error */
    }
    const err = new Error(message);
    err.status = res.status;
    throw err;
  }

  return res.status === 204 ? null : res.json();
}

export const authApi = {
  /** Full-page redirect that begins the Google OAuth flow (FR 1/2). */
  startGoogleLogin: () => {
    window.location.href = '/api/auth/google';
  },
  /** Full-page redirect that begins "Sign in / up with GitHub". */
  startGithubLogin: () => {
    window.location.href = '/api/auth/github/login';
  },
  /** Email/password registration. Resolves with the created user on success. */
  register: (payload) =>
    request('/auth/register', { method: 'POST', body: JSON.stringify(payload) }),
  /** Email/password login. Resolves with the user on success. */
  login: (payload) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify(payload) }),
  me: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }),
};

export const githubApi = {
  /** Full-page redirect that begins the GitHub OAuth connect flow (FR 9/10). */
  startConnect: () => {
    window.location.href = '/api/auth/github/connect';
  },
  status: () => request('/auth/github/status'),
  disconnect: () => request('/auth/github/disconnect', { method: 'POST' }),
};

export const resumeApi = {
  status: () => request('/resume/status'),
  /**
   * Upload/replace the resume (FR 19-27). Uses a bare fetch — multipart
   * bodies must not get the `Content-Type: application/json` header the
   * shared `request()` helper always sets.
   */
  upload: async (file) => {
    const body = new FormData();
    body.append('resume', file);
    const res = await fetch('/api/resume/upload', {
      method: 'POST',
      body,
      credentials: 'include',
    });
    if (!res.ok) {
      let message = `Upload failed (${res.status})`;
      try {
        message = (await res.json()).error || message;
      } catch {
        /* non-JSON error */
      }
      throw new Error(message);
    }
    return res.json();
  },
};
