import { env, isSemanticEngineConfigured } from "../config/env.js";
import {
  signGithubConnectState,
  signGithubLoginState,
  verifyGithubState,
  signSessionToken,
  sessionExpiryDate,
  newTokenId,
} from "../utils/jwt.js";
import { encryptToken } from "../utils/secureToken.js";
import {
  createSession,
  findActiveByUserAndProvider,
  revokeAllForUserProvider,
  revokeSession,
} from "../models/OAuthSession.js";
import { findByProviderId, findByEmail, findById, createUser, ROLES } from "../models/User.js";
import * as GithubConnection from "../models/GithubConnection.js";
import * as Resume from "../models/Resume.js";
import * as ReadinessReport from "../models/ReadinessReport.js";
import { hasAnyApplication } from "../models/JobApplication.js";
import { flattenSkillNames, scoreReadinessInBackground } from "../utils/readinessScoring.js";

const SESSION_COOKIE = "devscore_session";

const GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize";
const GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token";
const GITHUB_USER_API = "https://api.github.com/user";

// GitHub OAuth app tokens don't expire on their own; we still record an
// expiry so oauth_sessions' NOT NULL/audit semantics (SDS §4.7.5) hold, and
// so a stale connection eventually falls out of "active" if never renewed.
const GITHUB_TOKEN_TTL_DAYS = 365;

/**
 * Begin the GitHub OAuth connect flow (FR 9). Only students who are already
 * logged in via the DevScore session may reach this route (requireAuth +
 * requireRole('student') in the route definition). We can't rely on a
 * server-side session for the redirect round-trip, so the current user id is
 * carried in a short-lived signed `state` param instead (verified in the
 * callback, and doubling as CSRF protection).
 *
 * A student must select a job role before linking GitHub evidence for it —
 * enforced here (not just hidden in the UI) so hitting this URL directly
 * can't skip the step. Fails open only if the check itself errors (e.g.
 * job_applications hasn't been migrated yet), not on a genuine "no role yet".
 */
export async function githubConnect(req, res) {
  try {
    if (!(await hasAnyApplication(req.user.id))) {
      return res.redirect(
        `${env.clientUrl}/student/jobs?error=select_role_first`,
      );
    }
  } catch (err) {
    console.error(
      "[github] could not verify a job application before connect:",
      err.message,
    );
  }

  const state = signGithubConnectState(req.user.id);

  const params = new URLSearchParams({
    client_id: env.github.clientId,
    redirect_uri: env.github.callbackUrl,
    // Read-only, public-data scopes only (SDS §4.7.4 — minimum viable permissions).
    scope: "read:user public_repo",
    state,
    allow_signup: "false",
  });

  res.redirect(`${GITHUB_AUTHORIZE_URL}?${params.toString()}`);
}

/**
 * Begin "Sign in / up with GitHub" (identity, not the student evidence-link
 * flow above). Reuses the same GitHub OAuth App/callback URL as connect —
 * the callback tells the two apart via the signed `state`'s purpose.
 */
export function githubLoginStart(req, res) {
  const state = signGithubLoginState();

  const params = new URLSearchParams({
    client_id: env.github.clientId,
    redirect_uri: env.github.callbackUrl,
    scope: "read:user user:email",
    state,
    allow_signup: "true",
  });

  res.redirect(`${GITHUB_AUTHORIZE_URL}?${params.toString()}`);
}

/** Exchange an OAuth `code` for a GitHub access token + profile. Shared by connect and login. */
async function exchangeGithubCode(code) {
  const tokenRes = await fetch(GITHUB_TOKEN_URL, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      client_id: env.github.clientId,
      client_secret: env.github.clientSecret,
      code,
      redirect_uri: env.github.callbackUrl,
    }),
  });
  const tokenBody = await tokenRes.json();
  if (!tokenRes.ok || !tokenBody.access_token) {
    throw new Error("github_token_exchange_failed");
  }
  const accessToken = tokenBody.access_token;

  const profileRes = await fetch(GITHUB_USER_API, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "DevScore-App",
    },
  });
  if (!profileRes.ok) {
    throw new Error("github_profile_fetch_failed");
  }
  const profile = await profileRes.json();

  // Public profile email can be null — fall back to the (possibly private) primary email.
  if (!profile.email) {
    const emailsRes = await fetch(`${GITHUB_USER_API}/emails`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "DevScore-App",
      },
    });
    if (emailsRes.ok) {
      const emails = await emailsRes.json();
      profile.email =
        emails.find((e) => e.primary)?.email || emails[0]?.email || null;
    }
  }

  return { accessToken, profile };
}

/**
 * Starts job-readiness scoring for a student who connects GitHub *after*
 * already having an extracted resume — the more common order isn't
 * "connect GitHub, then upload," it's "upload, then realize you should
 * connect GitHub." resumeController's own upload flow only triggers
 * scoring when a GitHub connection already exists at upload time, so
 * without this, connecting GitHub afterward would silently never score
 * anything (no error shown anywhere — just a permanent "—" on Skills
 * Status). Mirrors resumeController.uploadResume's trigger exactly, just
 * from the other direction. Always (re)triggers on a successful connect,
 * same as every resume upload always (re)triggers scoring regardless of
 * whether a prior report exists — see readiness_reports' "current state
 * only" semantics in server/supabase/schema.sql.
 */
async function maybeStartReadinessScoringAfterConnect(userId, githubUsername) {
  if (!isSemanticEngineConfigured) return;

  try {
    const resume = await Resume.findByUserId(userId);
    if (!resume || !resume.extraction_status?.startsWith("success")) return;

    const skills = await Resume.getSkills(resume.id);
    const skillNames = flattenSkillNames(skills);
    if (skillNames.length === 0) return;

    const user = await findById(userId);
    if (!user) return;

    await ReadinessReport.markPending(resume.id);
    scoreReadinessInBackground(resume, user, githubUsername, skillNames);
  } catch (err) {
    console.error("[github] could not start readiness scoring after connect:", err.message);
  }
}

/** Continue the "connect GitHub for evidence" flow (existing student, FR 9/10). */
async function completeGithubConnect(req, res, userId, code) {
  const redirectBack = (query) =>
    res.redirect(
      `${env.clientUrl}/student/github?${new URLSearchParams(query)}`,
    );

  try {
    const { accessToken, profile } = await exchangeGithubCode(code);

    // One active GitHub connection per student — revoke any prior one before storing the new session.
    await revokeAllForUserProvider(userId, "github");

    const expiresAt = new Date(
      Date.now() + GITHUB_TOKEN_TTL_DAYS * 24 * 60 * 60 * 1000,
    );

    await createSession({
      userId,
      provider: "github",
      tokenId: newTokenId(),
      encryptedAccessToken: encryptToken(accessToken),
      userAgent: req.headers["user-agent"] || "",
      ip: req.ip,
      expiresAt,
    });

    await GithubConnection.upsert(userId, profile.login);

    // Never awaited — same "detached background job" pattern as
    // resumeController's upload-time trigger; the student polls
    // /resume/status for the result.
    maybeStartReadinessScoringAfterConnect(userId, profile.login);

    return redirectBack({ connected: "1" });
  } catch {
    return redirectBack({ error: "github_connection_failed" });
  }
}

/** Continue "Sign in / up with GitHub" — find-or-create the account, then issue a session. */
async function completeGithubLogin(req, res, code) {
  const redirectBack = (query) =>
    res.redirect(`${env.clientUrl}/login?${new URLSearchParams(query)}`);

  try {
    const { profile } = await exchangeGithubCode(code);
    const oauthId = String(profile.id);

    let user = await findByProviderId("github", oauthId);
    if (!user) {
      // A prior Google/local account with the same email gets linked by
      // email rather than duplicated (mirrors Google's existing-user check, FR 4/6).
      user = profile.email ? await findByEmail(profile.email) : null;
      if (!user) {
        if (!profile.email) {
          return redirectBack({ error: "github_email_required" });
        }
        const [firstName, ...rest] = (
          profile.name ||
          profile.login ||
          ""
        ).split(" ");
        user = await createUser({
          email: profile.email,
          firstName: firstName || profile.login || "GitHub",
          lastName: rest.join(" "),
          avatarUrl: profile.avatar_url || "",
          role: ROLES.STUDENT,
          oauthProvider: "github",
          oauthId,
        });
      }
    }

    const tokenId = newTokenId();
    const expiresAt = sessionExpiryDate();
    await createSession({
      userId: user.id,
      provider: "github",
      tokenId,
      userAgent: req.headers["user-agent"] || "",
      ip: req.ip,
      expiresAt,
    });
    const token = signSessionToken({
      userId: user.id,
      role: user.role,
      tokenId,
    });

    res.cookie(SESSION_COOKIE, token, {
      httpOnly: true,
      secure: env.nodeEnv === "production",
      sameSite: "lax",
      expires: expiresAt,
    });

    return res.redirect(`${env.clientUrl}/auth/callback`);
  } catch {
    return redirectBack({ error: "github_login_failed" });
  }
}

/**
 * Shared GitHub OAuth callback — dispatches to the "connect for evidence"
 * flow (FR 9/10) or the "sign in / up with GitHub" flow based on the signed
 * state's purpose, since both reuse the same registered callback URL.
 */
export async function githubCallback(req, res) {
  const { code, state, error: githubError } = req.query;

  if (githubError) {
    return res.redirect(
      `${env.clientUrl}/login?error=github_permission_denied`,
    );
  }
  if (!code || !state) {
    return res.redirect(`${env.clientUrl}/login?error=github_invalid_callback`);
  }

  let payload;
  try {
    payload = verifyGithubState(state);
  } catch {
    return res.redirect(`${env.clientUrl}/login?error=github_invalid_state`);
  }

  if (payload.purpose === "github_connect") {
    return completeGithubConnect(req, res, payload.sub, code);
  }
  return completeGithubLogin(req, res, code);
}

/** Report whether the current student has an active GitHub connection. */
export async function githubStatus(req, res, next) {
  try {
    const [session, connection] = await Promise.all([
      findActiveByUserAndProvider(req.user.id, "github"),
      GithubConnection.findByUserId(req.user.id),
    ]);
    res.json({
      connected: Boolean(session),
      username: connection?.username || null,
      connectedAt: connection?.connected_at || null,
    });
  } catch (err) {
    next(err);
  }
}

/** Disconnect the student's linked GitHub account. */
export async function githubDisconnect(req, res, next) {
  try {
    const session = await findActiveByUserAndProvider(req.user.id, "github");
    if (session) {
      await revokeSession(session.token_id);
    }
    await GithubConnection.remove(req.user.id);
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
}
