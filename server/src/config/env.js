import dotenv from 'dotenv';

dotenv.config();

const nodeEnv = process.env.NODE_ENV || 'development';

// Refuse to boot with the insecure default secret in production — falling
// back silently there would sign session JWTs with a value published in
// this source file.
if (nodeEnv === 'production' && !process.env.JWT_SECRET) {
  throw new Error(
    'JWT_SECRET must be set in production (see server/.env.example).',
  );
}

/** Centralised, validated access to environment configuration. */
export const env = {
  port: Number(process.env.PORT) || 5000,
  nodeEnv,
  jwtSecret: process.env.JWT_SECRET || 'dev-insecure-secret',
  jwtExpiresIn: process.env.JWT_EXPIRES_IN || '7d',
  clientUrl: process.env.CLIENT_URL || 'http://localhost:5173',
  supabase: {
    url: process.env.SUPABASE_URL || '',
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY || '',
  },
  google: {
    clientId: process.env.GOOGLE_CLIENT_ID || '',
    clientSecret: process.env.GOOGLE_CLIENT_SECRET || '',
    callbackUrl:
      process.env.GOOGLE_CALLBACK_URL ||
      'http://localhost:5000/api/auth/google/callback',
  },
  github: {
    clientId: process.env.GITHUB_CLIENT_ID || '',
    clientSecret: process.env.GITHUB_CLIENT_SECRET || '',
    callbackUrl:
      process.env.GITHUB_CALLBACK_URL ||
      'http://localhost:5000/api/auth/github/callback',
  },
  cvParser: {
    url: process.env.CV_PARSER_URL || 'http://localhost:5001',
    apiKey: process.env.CV_PARSER_API_KEY || '',
  },
  skillVerification: {
    url: process.env.SKILL_VERIFICATION_URL || 'http://localhost:5002',
    apiKey: process.env.SKILL_VERIFICATION_API_KEY || '',
  },
};

/** True only when the CV parser service URL is configured. */
export const isCvParserConfigured = Boolean(env.cvParser.url);

/** True only when Supabase credentials are present. */
export const isSupabaseConfigured = Boolean(
  env.supabase.url && env.supabase.serviceRoleKey,
);

/** True only when Google OAuth credentials are present. */
export const isGoogleOAuthConfigured = Boolean(
  env.google.clientId && env.google.clientSecret,
);

/** True only when GitHub OAuth credentials are present (FR 9/10). */
export const isGithubOAuthConfigured = Boolean(
  env.github.clientId && env.github.clientSecret,
);
