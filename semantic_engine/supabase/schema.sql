-- DevScore Engine — persistence for Implementation 02 scoring results.
--
-- Additive to server/supabase/schema.sql in Team-ScriptFusion/DevScore. Apply
-- AFTER it: every table here references users / resumes / skills from that file.
--
-- Note on the SDS inconsistency the project summary flags (MongoDB in §2.6 and
-- §5.2 vs MySQL in Chapter 4): Implementation 01 settled it in practice by
-- shipping Supabase/Postgres. This schema follows that decision. The SDS
-- chapters still need to be reconciled to match what was built.
--
-- Design note: verdicts are stored one row per (score, skill) rather than as a
-- jsonb blob. The Evidence Gap dashboard filters and sorts by skill, tier and
-- verification, and per-skill precision/recall for the validation study is a
-- GROUP BY over this table. A blob would make both of those application code.

-- ---------------------------------------------------------------------------
-- job_readiness_scores — one row per scoring run (FR 41-46)
--
-- History is kept rather than overwritten: a candidate who pushes new work
-- should score higher next month, and the research needs to see that movement.
-- The dashboard reads the latest row per user via job_readiness_scores_latest.
-- ---------------------------------------------------------------------------
create table if not exists public.job_readiness_scores (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null references public.users (id) on delete cascade,
  resume_id             uuid references public.resumes (id) on delete set null,
  -- Recruiter who triggered this run (scoring is recruiter-initiated, FR 41).
  requested_by          uuid references public.users (id) on delete set null,

  github_username       text not null default '',
  score                 numeric(5,2) not null check (score >= 0 and score <= 100),
  band                  text not null,
  -- How much public code this score rests on, 0-1. Displayed BESIDE the score,
  -- never folded into it: a low-confidence 70 and a high-confidence 70 are the
  -- same claim about the candidate and a different claim about our coverage.
  confidence            numeric(4,3) not null default 0 check (confidence between 0 and 1),

  base_score            numeric(5,2) not null default 0,
  integrity_penalty     numeric(5,2) not null default 0,
  breadth_bonus         numeric(5,2) not null default 0,

  claimed_count         integer not null default 0,
  verifiable_claims     integer not null default 0,
  verified_count        integer not null default 0,
  weakly_verified_count integer not null default 0,
  unverified_count      integer not null default 0,

  -- Per-area sub-scores: {"Frontend": 78.2, "Backend": 24.7, ...}
  category_scores       jsonb not null default '{}'::jsonb,
  -- Warnings shown to the recruiter (no GitHub found, rate limit hit, OCR used).
  warnings              jsonb not null default '[]'::jsonb,

  engine_version        text not null default '',
  -- Reproducibility: the same CV and the same repositories must be re-scorable
  -- to the same number, and that is only true if the coefficients that produced
  -- it are recorded alongside it. Without this, a weight change silently
  -- invalidates every historical score in the validation study.
  signal_weights        jsonb not null default '{}'::jsonb,

  github_api_calls      integer not null default 0,
  scored_at             timestamptz not null default now()
);

create index if not exists jrs_user_id_idx    on public.job_readiness_scores (user_id);
create index if not exists jrs_scored_at_idx  on public.job_readiness_scores (scored_at desc);
create index if not exists jrs_score_idx      on public.job_readiness_scores (score desc);

-- ---------------------------------------------------------------------------
-- skill_verdicts — the Evidence Gap, one row per claim examined (FR 48)
-- ---------------------------------------------------------------------------
create table if not exists public.skill_verdicts (
  id                uuid primary key default gen_random_uuid(),
  score_id          uuid not null references public.job_readiness_scores (id) on delete cascade,
  -- Nullable: a verdict can exist for a skill not yet in the catalog (an
  -- unclaimed strength found only in code), and skill_name is authoritative.
  skill_id          uuid references public.skills (id) on delete set null,
  skill_name        text not null,
  category          text not null default '',

  claimed           boolean not null default false,
  verifiable        boolean not null default true,
  status            text not null
                      check (status in ('verified', 'weakly_verified', 'unverified',
                                        'not_verifiable', 'unclaimed_strength')),
  tier              text not null default 'none'
                      check (tier in ('none', 'ambient', 'declared', 'used',
                                      'applied', 'mastered')),

  weight            numeric(4,2) not null default 0,   -- W_i
  verification      numeric(5,4) not null default 0,   -- V_i

  -- The five signals composing V_i, stored separately so the dashboard can
  -- explain why a verified skill still scored low (real, but stale).
  evidence_strength numeric(5,4) not null default 0,
  complexity        numeric(5,4) not null default 0,
  depth             numeric(5,4) not null default 0,
  recency           numeric(5,4) not null default 0,
  craft             numeric(5,4) not null default 0,

  repos             jsonb not null default '[]'::jsonb,
  files_analyzed    integer not null default 0,
  loc_analyzed      integer not null default 0,
  last_activity     timestamptz,
  -- Concrete evidence hits: [{channel, repo, detail, count}, ...]. Capped by the
  -- engine before insert; this is the audit trail behind a single verdict.
  evidence          jsonb not null default '[]'::jsonb,
  explanation       text not null default '',

  unique (score_id, skill_name)
);

create index if not exists sv_score_id_idx on public.skill_verdicts (score_id);
create index if not exists sv_skill_idx    on public.skill_verdicts (skill_name);
create index if not exists sv_status_idx   on public.skill_verdicts (status);

-- ---------------------------------------------------------------------------
-- expert_evaluations — the manual baseline the automated score is validated
-- against (research objective 5).
--
-- Kept in the database rather than a spreadsheet so inter-rater agreement can
-- be MEASURED rather than assumed — the project summary lists exactly that as a
-- risk ("the validation is only as strong as the manual rankings"). Multiple
-- experts per candidate is the normal case, which is why the key is
-- (candidate, expert) and not candidate alone.
-- ---------------------------------------------------------------------------
create table if not exists public.expert_evaluations (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users (id) on delete cascade,
  expert_name   text not null,
  expert_org    text not null default '',
  expert_score  numeric(5,2) check (expert_score >= 0 and expert_score <= 100),
  expert_rank   integer,
  notes         text not null default '',
  evaluated_at  timestamptz not null default now(),
  unique (user_id, expert_name),
  -- An evaluation with neither a score nor a rank carries no information.
  constraint expert_has_judgement check (expert_score is not null or expert_rank is not null)
);

create index if not exists ee_user_id_idx on public.expert_evaluations (user_id);

-- ---------------------------------------------------------------------------
-- Latest score per candidate — what the recruiter dashboard lists (FR 47)
-- ---------------------------------------------------------------------------
create or replace view public.job_readiness_scores_latest as
select distinct on (s.user_id)
  s.*,
  u.first_name,
  u.last_name,
  u.email
from public.job_readiness_scores s
join public.users u on u.id = s.user_id
order by s.user_id, s.scored_at desc;

-- ---------------------------------------------------------------------------
-- Row-level security
--
-- The parent project's scope boundary is explicit: "Students cannot see their
-- own score." That is a deliberate anti-gaming and anti-anxiety decision, and
-- it has to be enforced in the DATABASE, not only by hiding a route in React.
-- A student hitting the REST API directly must get nothing back.
-- ---------------------------------------------------------------------------
alter table public.job_readiness_scores enable row level security;
alter table public.skill_verdicts       enable row level security;
alter table public.expert_evaluations   enable row level security;

drop policy if exists jrs_recruiters_and_admins_read on public.job_readiness_scores;
create policy jrs_recruiters_and_admins_read
  on public.job_readiness_scores for select
  using (
    exists (
      select 1 from public.users u
      where u.id = auth.uid() and u.role in ('recruiter', 'admin')
    )
  );

drop policy if exists sv_recruiters_and_admins_read on public.skill_verdicts;
create policy sv_recruiters_and_admins_read
  on public.skill_verdicts for select
  using (
    exists (
      select 1 from public.users u
      where u.id = auth.uid() and u.role in ('recruiter', 'admin')
    )
  );

drop policy if exists ee_admins_only on public.expert_evaluations;
create policy ee_admins_only
  on public.expert_evaluations for all
  using (
    exists (select 1 from public.users u where u.id = auth.uid() and u.role = 'admin')
  );

-- Writes come from the scoring worker using the service role, which bypasses
-- RLS. No insert/update policy is defined for any of these tables on purpose:
-- nothing that authenticates as a normal user should ever be able to write a
-- readiness score.
