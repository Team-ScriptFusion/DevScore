-- DevScore — Data Tier schema (Supabase / Postgres)
-- Member 1 database ownership: users, oauth_sessions.
-- Apply via the Supabase SQL editor or `supabase db push`.

-- ---------------------------------------------------------------------------
-- users  (SDS logical design: User + name fields)
-- ---------------------------------------------------------------------------
create table if not exists public.users (
  id             uuid primary key default gen_random_uuid(),
  email          text not null unique,
  first_name     text not null default '',
  last_name      text not null default '',
  avatar_url     text not null default '',
  role           text not null default 'student'
                   check (role in ('student', 'recruiter', 'admin')),
  -- Identity provider for this account. 'local' = email/password signup;
  -- oauth_id/oauth_provider are both null for local accounts.
  oauth_provider text check (oauth_provider in ('google', 'github')),
  oauth_id       text,
  -- Set only for local (email/password) accounts — bcrypt hash, never plaintext.
  password_hash  text,
  -- Student's linked GitHub identity (FR 9/10) — set once the GitHub OAuth
  -- connect flow succeeds; the access token itself lives in oauth_sessions.
  github_username     text,
  github_connected_at timestamptz,
  -- Student's uploaded resume (FR 19-27). The file itself lives in the
  -- 'resumes' Storage bucket at resume_storage_path; re-uploading overwrites
  -- the same path, so these columns always describe the current resume.
  resume_original_name text,
  resume_storage_path  text,
  resume_size_bytes    integer,
  resume_uploaded_at   timestamptz,
  -- Skills extracted from the resume by the CV parser (FR 28-32). Re-parsed
  -- on every upload; claimed_skills mirrors parse_resume()'s "by_category"
  -- shape: { "language": ["Python", ...], "framework": [...], ... }.
  claimed_skills          jsonb,
  skills_uncategorized    jsonb,
  skills_extraction_status text
    check (skills_extraction_status in ('pending', 'success', 'success_no_skills_found', 'failed')),
  skills_extracted_at     timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  -- One account per provider identity (supports existing-user detection, FR 6).
  -- Postgres treats NULLs as distinct, so multiple local (null, null) rows are fine.
  unique (oauth_provider, oauth_id),
  -- Every account must be reachable through at least one credential.
  constraint users_has_credential check (
    (oauth_provider is not null and oauth_id is not null) or password_hash is not null
  )
);

-- Idempotent upgrade path for databases created before password auth existed.
alter table public.users add column if not exists password_hash text;
alter table public.users alter column oauth_provider drop not null;
alter table public.users alter column oauth_id drop not null;
alter table public.users drop constraint if exists users_has_credential;
alter table public.users add constraint users_has_credential check (
  (oauth_provider is not null and oauth_id is not null) or password_hash is not null
);

-- Idempotent upgrade path for databases created before resume upload existed.
alter table public.users add column if not exists resume_original_name text;
alter table public.users add column if not exists resume_storage_path text;
alter table public.users add column if not exists resume_size_bytes integer;
alter table public.users add column if not exists resume_uploaded_at timestamptz;

-- Idempotent upgrade path for databases created before skill extraction existed.
alter table public.users add column if not exists claimed_skills jsonb;
alter table public.users add column if not exists skills_uncategorized jsonb;
alter table public.users add column if not exists skills_extraction_status text;
alter table public.users add column if not exists skills_extracted_at timestamptz;
alter table public.users drop constraint if exists users_skills_extraction_status_check;
alter table public.users add constraint users_skills_extraction_status_check
  check (skills_extraction_status in ('pending', 'success', 'success_no_skills_found', 'failed'));

-- ---------------------------------------------------------------------------
-- oauth_sessions  (FR 7 — server-side session tokens; SDS §4.7.5 audit trail)
-- ---------------------------------------------------------------------------
create table if not exists public.oauth_sessions (
  id                     uuid primary key default gen_random_uuid(),
  user_id                uuid not null references public.users (id) on delete cascade,
  provider               text not null check (provider in ('google', 'github', 'local')),
  -- Opaque id embedded in the JWT (jti) so a token can be revoked server-side.
  token_id               text not null unique,
  -- Encrypted provider access token (via secureToken util; AES-256 is Member 5).
  encrypted_access_token text,
  user_agent             text not null default '',
  ip                     text not null default '',
  revoked_at             timestamptz,
  expires_at             timestamptz not null,
  created_at             timestamptz not null default now()
);

create index if not exists oauth_sessions_user_id_idx on public.oauth_sessions (user_id);

-- Idempotent upgrade path for the 'local' (email/password) provider value.
alter table public.oauth_sessions drop constraint if exists oauth_sessions_provider_check;
alter table public.oauth_sessions add constraint oauth_sessions_provider_check
  check (provider in ('google', 'github', 'local'));

-- The API accesses these tables only through the service-role key, so RLS is
-- enabled with no public policies (deny-by-default for anon/authenticated).
alter table public.users enable row level security;
alter table public.oauth_sessions enable row level security;
