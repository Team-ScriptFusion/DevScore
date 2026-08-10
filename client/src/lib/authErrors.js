/** Maps `?error=` query values (set by OAuth failure redirects) to user-facing copy. */
export const AUTH_ERROR_MESSAGES = {
  oauth_failed: 'Google sign-in was cancelled or failed. Please try again.',
  github_failed: 'GitHub sign-in was cancelled or failed. Please try again.',
  github_permission_denied: 'GitHub access was denied. Please try again.',
  github_invalid_callback: 'GitHub sign-in could not be completed. Please try again.',
  github_invalid_state: 'That GitHub sign-in link expired. Please try again.',
  github_email_required:
    'Your GitHub account has no public email. Add one in GitHub settings, or sign up with email/password instead.',
  github_login_failed: 'GitHub sign-in failed. Please try again.',
};

export function authErrorMessage(code) {
  if (!code) return '';
  return AUTH_ERROR_MESSAGES[code] || AUTH_ERROR_MESSAGES.oauth_failed;
}
