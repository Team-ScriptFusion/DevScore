# Design: GitHub-Backed Skill Verification (Implementation 02, Module 1)

Status: approved for planning
Date: 2026-09-02

## 1. Problem and origin

DevScore scores a student's job-readiness (the Weighted Verification Ratio,
`WVR = Σ(Wi·Vi) / ΣWi × 100`) by cross-checking resume claims against real
evidence. `Vi`, the per-skill verification value, does not exist yet. This
module produces it: given a student's claimed skills (already extracted by
`cv_parser` into the `skills` / `resume_skills` tables) and their connected
GitHub account, decide per skill whether there is real evidence for it, how
confident that decision is, and how it was reached.

Consumers of this module's output:
- The recruiter dashboard's "verified" badges (currently a "coming soon"
  placeholder — wiring the UI to read this data is a separate, later task,
  not part of this module).
- The scoring module, which reads `skill_verification` as its `Vi` input.

This document does not cover: code/AST analysis (separate module), the WVR
formula or skill-importance weights (separate module), or any recruiter
dashboard UI changes.

## 2. Why this deviates from the original module brief

An initial brief for this module assumed a schema and integration pattern
different from what the codebase actually does. Concretely:

- The GitHub OAuth access token lives in `oauth_sessions.encrypted_access_token`
  (one row per session, provider = `'github'`), retrieved via
  `OAuthSession.findActiveByUserAndProvider(userId, 'github')` and decrypted
  with `secureToken.decryptToken`. It is **not** stored on `github_connections`
  — that table holds only `user_id` + `username`.
- Every table in `server/supabase/schema.sql` has RLS **enabled with zero
  policies** — deny-by-default for `anon`/`authenticated`, service-role-key
  only, with all authorization done in Express (`requireAuth`/`requireRole`
  plus per-route ownership checks). There are no granular per-role Postgres
  policies anywhere in this schema.
- The one existing Python microservice, `cv_parser`, is a **stateless**
  Flask app: it never touches Supabase. Node (`server/src/utils/cvParser.js`)
  POSTs a file to it over HTTP with a shared `X-Api-Key` secret, gets JSON
  back, and does 100% of the persistence itself (`Resume.setExtraction`).

This design follows those existing patterns rather than the brief's
assumptions, for consistency with the rest of the codebase.

## 3. Architecture

```
Student's browser
      │  (existing) GitHub OAuth connect → github_connections + oauth_sessions
      │  (existing) resume upload → cv_parser → skills / resume_skills
      ▼
Node/Express  (server/src)
  routes/skillVerificationRoutes.js
  controllers/skillVerificationController.js
      │  1. decrypt GitHub token (existing OAuthSession + secureToken utils)
      │  2. check github_evidence.fetched_at for cache freshness
      │  3. call Python service over HTTP (shared secret header)
      │  4. persist results via models/GithubEvidence.js, models/SkillVerification.js
      ▼
Python service (new)  services/skill_verification/
  app.py            — Flask, two internal routes, stateless
  github_fetch.py   — Phase 0: GitHub REST API calls, rate-limit aware
  direct_matcher.py — Phase 1: synonym + language-tag matching
  semantic_matcher.py — Phase 2: sentence-transformers cosine similarity
  main.py           — orchestrates fetch → direct → semantic per request
```

The Python service is stateless and never touches Supabase — it mirrors
`cv_parser` exactly. Node owns all persistence, caching decisions, and
authorization.

## 4. Python service — API contract (internal only, not public-facing)

Both routes require header `X-Api-Key: <SKILL_VERIFICATION_API_KEY>` (same
pattern as `cv_parser`'s `PARSER_API_KEY`; absent key = open access, matching
how the rest of this app degrades in local dev).

### `POST /fetch-evidence`
Request:
```json
{ "github_username": "octocat", "access_token": "gho_..." }
```
Fetches the student's public repos via the GitHub REST API using the given
token (`GET /user/repos`, filtered to `private: false`), sorted by
`pushed_at` descending, **capped at the 30 most recently pushed non-fork
repos** (bounds API-call count and request duration for prolific
committers — a hard NFR given no background-job infrastructure exists in
this codebase; the whole call must complete within one HTTP request/response
cycle). For each: `GET .../languages` (bytes per language) and
`GET .../readme` (base64-decoded, truncated to ~4000 chars). Last-activity
date is the repo list response's `pushed_at` field, used as-is; exact commit
count is dropped from this module's evidence (would need an extra
`GET .../commits` call per repo, doubling the request budget, and nothing
in Phase 1/2 matching actually needs a count — only presence/recency and
language/README content do).

Rate-limit handling: after each GitHub API call, check
`X-RateLimit-Remaining`. If it drops below 10, stop fetching further repos
early and return what was gathered so far with `"rate_limited": true` —
never fail the whole request because of it.

Response:
```json
{
  "repos": [
    {
      "name": "my-ml-project",
      "is_fork": false,
      "languages": { "Python": 8000, "Jupyter Notebook": 1200 },
      "readme_text": "...",
      "pushed_at": "2026-08-01T12:00:00Z"
    }
  ],
  "rate_limited": false
}
```
If the token is invalid/revoked (GitHub returns 401), respond
`{ "error": "invalid_token" }` with HTTP 401 so Node can surface
`github_not_connected`-style handling without crashing.

### `POST /match-skills`
Request:
```json
{
  "claimed_skills": ["Python", "Machine Learning", "Kubernetes"],
  "repos": [ /* same shape as fetch-evidence's "repos" */ ]
}
```
Phase 1 (direct match): normalize claimed skill + each repo's language keys
through a synonym table (`"JS"→"JavaScript"`, `"Golang"→"Go"`, etc., grown
as real data is seen); a claimed skill matching a language with a non-trivial
byte count (avoid a single stray config file) is `verified: true,
method: "direct_match", confidence: 1.0`.

Phase 2 (semantic match), for skills that didn't direct-match: embed the
claimed skill string with `sentence-transformers` (`all-MiniLM-L6-v2`,
loaded once at process startup, not per-request). Build one evidence chunk
per repo (`description` — not available from this API shape, so: repo name
+ README text, truncated), embed each, take the max cosine similarity
across chunks. Threshold 0.65 (unvalidated starting point, per the original
brief — do not tune this against the project's expert-ranking dataset,
which is reserved for the scoring module). `verified = score >= 0.65,
method: "semantic_match", confidence: score` (confidence stored even when
below threshold).

If `repos` is empty, every unresolved skill short-circuits to
`verified: false, method: "unverified", confidence: null,
reason: "no_public_repos"` without running the embedding model at all —
there is a repo name in every non-empty `repos` entry, so once at least one
repo exists there is always *some* text to embed, which means a semantic
score always gets computed. So the only other unresolved outcome is: score
computed, below 0.65 → `verified: false, method: "semantic_match",
confidence: score, reason: "below_confidence_threshold"`.

Response: array of
`{ skill, verified, method, confidence, evidence_repo, reason }`
(`evidence_repo` = the matched repo's name, or `null`).

## 5. Node integration

`server/src/utils/skillVerification.js` — two thin functions,
`fetchGithubEvidence(username, accessToken)` and
`matchSkills(claimedSkills, repos)`, calling the two routes above (same
`fetch` + `AbortSignal.timeout` pattern as `cvParser.js`; timeout 60s given
the fetch route can make ~90 GitHub API calls).

`server/src/models/GithubEvidence.js` and
`server/src/models/SkillVerification.js` — plain Supabase CRUD, following
the existing model style (`findByUserId`, `upsert`, etc., no PostgREST
embedding beyond the same single-level `skills(name, category)` join
`Resume.js` already does).

`server/src/controllers/skillVerificationController.js`:

- `runVerification(req, res)` — resolves the target student id: self if
  `req.user.role === 'student'`, or `req.body.studentId` if recruiter (with
  the same "did this student apply to one of my postings, else 404" check
  `recruiterController.getCandidate` already implements — factor that
  ownership check out to a shared helper both controllers import, rather
  than duplicating it).
  1. Look up the student's GitHub connection + active session token. No
     connection or no active session → skip the fetch, write every claimed
     skill as `unverified` / `github_not_connected`, return early (this is
     the module's explicit "unverifiable, not unverified" case from the
     brief's risk list — surfaced via a distinct `reason` value the client
     can label differently later).
  2. Check the newest `github_evidence.fetched_at` for this student. If
     younger than 24h and `req.query.force` is not set, reuse stored rows
     instead of calling `/fetch-evidence` again.
  3. Otherwise call `/fetch-evidence`, replace this student's
     `github_evidence` rows (delete + reinsert, same pattern as
     `Resume.setExtraction`'s delete-then-insert for `resume_skills`).
  4. Load the student's claimed skills (via `Resume.getSkills`'s underlying
     query, by skill so we keep `skill_id`), call `/match-skills`, and
     upsert one `skill_verification` row per skill (delete + reinsert per
     student, keyed by `skill_id`).
  5. Respond with the same `{ status, skills_verified, skills_unverified,
     results }` shape the brief specified.

- `getVerification(req, res)` — same ownership rule, reads
  `skill_verification` joined to `skills(name, category)`, no recompute.

Routes, mounted in `app.js` as `app.use('/api/skill-verification',
skillVerificationRoutes)`:
```
POST /api/skill-verification/run          (requireAuth)
GET  /api/skill-verification/:studentId   (requireAuth)
```

## 6. Data schema

```sql
create table if not exists public.github_evidence (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users (id) on delete cascade,
  repo_name     text not null,
  is_fork       boolean not null default false,
  languages     jsonb not null default '{}'::jsonb,
  readme_text   text,
  last_pushed_at timestamptz,
  fetched_at    timestamptz not null default now()
);
create index if not exists github_evidence_user_id_idx on public.github_evidence (user_id);

create table if not exists public.skill_verification (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references public.users (id) on delete cascade,
  skill_id         uuid not null references public.skills (id) on delete cascade,
  verified         boolean not null,
  method           text not null check (method in ('direct_match', 'semantic_match', 'unverified')),
  confidence       numeric check (confidence >= 0 and confidence <= 1),
  evidence_repo_id uuid references public.github_evidence (id),
  reason           text check (reason in (
                     'github_not_connected', 'no_public_repos',
                     'below_confidence_threshold'
                   )),
  computed_at      timestamptz not null default now(),
  unique (user_id, skill_id)
);
create index if not exists skill_verification_user_id_idx on public.skill_verification (user_id);

alter table public.github_evidence enable row level security;
alter table public.skill_verification enable row level security;
-- No policies added — deny-by-default for anon/authenticated, service-role
-- key only, matching every other table in this schema.
```

`user_id` (not `student_id`) to match every other table's naming
(`resumes.user_id`, `github_connections.user_id`, etc.) — `users.role`
already constrains who that can be.

## 7. Error handling

- GitHub token invalid/revoked → `github_not_connected`-style result, not a
  500; the student's connection status is left alone (disconnect is a
  separate, explicit user action per the existing `githubDisconnect` flow).
- Python service unreachable/times out → the run endpoint responds 502
  (`"error": "skill_verification_service_unavailable"`); no partial writes
  (delete-then-reinsert only happens after a successful response, same
  as-is-safe pattern as `Resume.setExtraction`... except that one does
  delete before insert; here, fetch the new results into memory *first*,
  then delete+insert in one pass, so a mid-call failure leaves the
  previous results intact rather than wiping them).
- A claimed skill with no possible evidence at all (empty `repos`) short
  circuits to `no_public_repos` without calling the embedding model.

## 8. Testing

Python (`services/skill_verification/tests/`, `pytest`):
- Synonym normalization table (`"JS"` → `"JavaScript"`, etc.)
- Direct matcher: known match / non-match / trivial-byte-count-excluded cases
- Semantic matcher: hand-picked obvious-match (e.g. "Machine Learning" vs a
  TensorFlow README) and obvious-non-match pairs, using the real loaded
  model (no mocking the embeddings — the model is small and local)
- Rate-limit backoff: mock `requests` responses with a low
  `X-RateLimit-Remaining` header, assert early stop + `rate_limited: true`
- Integration: run the full `main.py` orchestration against 2-3 real public
  GitHub profiles (team members' own accounts) with a hand-picked claimed-skill
  list, sanity-check output manually — do not assert exact thresholds

Node (`server/src` — no test runner currently installed; use Node's
built-in `node:test` + `assert`, no new dependency):
- Ownership-check helper (recruiter-owns-candidate logic factored out of
  `recruiterController`)
- Cache-freshness decision (24h boundary)
- `github_not_connected` short-circuit path

## 9. Milestones

1. `services/skill_verification/` scaffolded, `/fetch-evidence` working
   end-to-end against one real GitHub account, no persistence yet.
2. Direct matcher (`/match-skills` Phase 1 only) working, `pytest` passing.
3. Semantic matcher (`sentence-transformers`) integrated into
   `/match-skills`.
4. `github_evidence` / `skill_verification` tables + Node models +
   `runVerification`/`getVerification` controller wired end-to-end.
5. Full pipeline tested against 2-3 real profiles; results sanity-checked.
6. `node:test` suite for the Node-side logic; rate-limit path verified.
