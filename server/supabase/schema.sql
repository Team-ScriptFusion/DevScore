-- DevScore — Data Tier schema (Supabase / Postgres)
-- Apply via the Supabase SQL editor or `supabase db push`.
--
-- Table layout (SDS logical design): users (identity/auth only),
-- oauth_sessions (session audit trail), github_connections (1:1 per
-- student), resumes (1:1 per student, current resume), skills (canonical
-- catalog), resume_skills (junction — one row per skill found in a resume),
-- job_roles (recruiter postings), job_applications (student -> job_role).

-- ---------------------------------------------------------------------------
-- users  — identity and authentication ONLY. Resume/GitHub/skills data used
-- to live here as bolted-on columns; they now live in their own tables below.
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

-- ---------------------------------------------------------------------------
-- github_connections  — a student's linked GitHub account (FR 9/10). One row
-- per user; the OAuth access token itself lives in oauth_sessions.
-- ---------------------------------------------------------------------------
create table if not exists public.github_connections (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null unique references public.users (id) on delete cascade,
  username     text not null,
  connected_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- resumes  — a student's current uploaded resume (FR 19-27). One row per
-- user; re-uploading overwrites this row (and the file at storage_path in
-- the 'resumes' Storage bucket), so it always describes the latest resume.
-- ---------------------------------------------------------------------------
create table if not exists public.resumes (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null unique references public.users (id) on delete cascade,
  original_name     text not null,
  storage_path      text not null,
  size_bytes        integer not null,
  uploaded_at       timestamptz not null default now(),
  -- Skill-extraction status (FR 28-32) for THIS resume upload.
  extraction_status text check (extraction_status in ('pending', 'success', 'success_no_skills_found', 'failed')),
  extracted_at      timestamptz
);

-- ---------------------------------------------------------------------------
-- skills  — canonical skill catalog, shared across all resumes. Seeded from
-- cv_parser's dictionary scan; unrecognized terms found in an explicit
-- "Skills" section are added here too (category = null) rather than
-- dropped, so the catalog grows from real resumes over time.
-- ---------------------------------------------------------------------------
create table if not exists public.skills (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  category   text,
  created_at timestamptz not null default now()
);

-- Case-insensitive uniqueness so "Python" and "python" from different
-- resumes collapse into one catalog entry.
create unique index if not exists skills_name_lower_idx on public.skills (lower(name));

-- ---------------------------------------------------------------------------
-- resume_skills  — junction: one row per skill found in a given resume
-- (SDS "Skill" entity, scoped to a resume). from_dictionary_scan /
-- from_skills_section mirror cv_parser's two detection passes — a skill can
-- be found by either or both.
-- ---------------------------------------------------------------------------
create table if not exists public.resume_skills (
  id                   uuid primary key default gen_random_uuid(),
  resume_id            uuid not null references public.resumes (id) on delete cascade,
  skill_id             uuid not null references public.skills (id) on delete cascade,
  from_dictionary_scan boolean not null default false,
  from_skills_section  boolean not null default false,
  created_at           timestamptz not null default now(),
  unique (resume_id, skill_id)
);

create index if not exists resume_skills_resume_id_idx on public.resume_skills (resume_id);
create index if not exists resume_skills_skill_id_idx on public.resume_skills (skill_id);

-- ---------------------------------------------------------------------------
-- job_roles  (recruiter-authored postings a student applies to before we have
-- anything to score them against)
-- ---------------------------------------------------------------------------
create table if not exists public.job_roles (
  id              uuid primary key default gen_random_uuid(),
  recruiter_id    uuid not null references public.users (id) on delete cascade,
  title           text not null,
  description     text not null default '',
  -- Skills the role asks for, as a flat jsonb array of names:
  -- ["React", "PostgreSQL", ...]. Stored as the recruiter typed it, NOT
  -- normalised against the skills catalog above — a future claimed-vs-
  -- required comparison must case-fold both sides rather than match literally.
  required_skills jsonb not null default '[]'::jsonb,
  employment_type text not null default 'full-time'
                    check (employment_type in ('full-time', 'part-time', 'internship', 'contract')),
  location        text not null default '',
  -- A closed posting stops accepting new applications but keeps its applicants.
  status          text not null default 'open'
                    check (status in ('open', 'closed')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists job_roles_recruiter_id_idx on public.job_roles (recruiter_id);
create index if not exists job_roles_status_idx on public.job_roles (status);

-- ---------------------------------------------------------------------------
-- job_applications  (student -> job_role; a student may apply to many roles)
-- ---------------------------------------------------------------------------
-- The resume and the GitHub link stay one-per-student (resumes/github_connections
-- above) and are shared across every application, so an application row
-- carries no artefacts of its own — the (job_id, student_id) pair plus a
-- timestamp is the whole fact.
create table if not exists public.job_applications (
  id         uuid primary key default gen_random_uuid(),
  job_id     uuid not null references public.job_roles (id) on delete cascade,
  student_id uuid not null references public.users (id) on delete cascade,
  applied_at timestamptz not null default now(),
  -- One application per student per role; withdrawing deletes the row.
  unique (job_id, student_id)
);

create index if not exists job_applications_job_id_idx on public.job_applications (job_id);
create index if not exists job_applications_student_id_idx on public.job_applications (student_id);

-- ---------------------------------------------------------------------------
-- github_evidence  — raw per-repo GitHub evidence for a student (Phase 0 of
-- the skill-verification module). Replaced wholesale on each re-fetch
-- (delete + reinsert), same pattern as resume_skills.
-- ---------------------------------------------------------------------------
create table if not exists public.github_evidence (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.users (id) on delete cascade,
  repo_name      text not null,
  is_fork        boolean not null default false,
  languages      jsonb not null default '{}'::jsonb,
  readme_text    text,
  last_pushed_at timestamptz,
  fetched_at     timestamptz not null default now()
);
create index if not exists github_evidence_user_id_idx on public.github_evidence (user_id);

-- ---------------------------------------------------------------------------
-- skill_verification  — per-skill verification result (Phases 1-2), the Vi
-- input to the WVR scoring formula. One row per (user, skill); replaced
-- wholesale on each re-run.
-- ---------------------------------------------------------------------------
create table if not exists public.skill_verification (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references public.users (id) on delete cascade,
  skill_id         uuid not null references public.skills (id) on delete cascade,
  verified         boolean not null,
  method           text not null check (method in ('direct_match', 'semantic_match', 'unverified')),
  confidence       numeric check (confidence >= 0 and confidence <= 1),
  -- on delete set null: github_evidence rows are replaced wholesale on every
  -- re-fetch (delete + reinsert), so prior-run references must not block that
  -- delete — the verification row survives with no linked evidence repo.
  evidence_repo_id uuid references public.github_evidence (id) on delete set null,
  reason           text check (reason in (
                     'github_not_connected', 'no_public_repos',
                     'below_confidence_threshold'
                   )),
  computed_at      timestamptz not null default now(),
  unique (user_id, skill_id)
);
create index if not exists skill_verification_user_id_idx on public.skill_verification (user_id);

-- Idempotent upgrade path for databases created before evidence_repo_id got
-- its on-delete behaviour: without it, GithubEvidence.replaceForUser's delete
-- raises a foreign-key violation on every re-verification after the first.
alter table public.skill_verification drop constraint if exists skill_verification_evidence_repo_id_fkey;
alter table public.skill_verification add constraint skill_verification_evidence_repo_id_fkey
  foreign key (evidence_repo_id) references public.github_evidence (id) on delete set null;

-- The API accesses these tables only through the service-role key, so RLS is
-- enabled with no public policies (deny-by-default for anon/authenticated).
alter table public.users enable row level security;
alter table public.oauth_sessions enable row level security;
alter table public.github_connections enable row level security;
alter table public.resumes enable row level security;
alter table public.skills enable row level security;
alter table public.resume_skills enable row level security;
alter table public.job_roles enable row level security;
alter table public.job_applications enable row level security;
alter table public.github_evidence enable row level security;
alter table public.skill_verification enable row level security;
