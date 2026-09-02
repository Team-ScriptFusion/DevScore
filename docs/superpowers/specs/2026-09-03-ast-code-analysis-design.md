# Design: AST-Based Code Analysis Engine (Implementation 02, Module 2)

Status: approved for planning
Date: 2026-09-03

## 1. Problem and origin

DevScore scores a student's job-readiness (the Weighted Verification Ratio,
`WVR = Σ(Wi·Vi) / ΣWi × 100`) using real evidence, not resume claims alone.
Module 1 (already built, `services/skill_verification/`) produces most of
`Vi` by checking whether a claimed skill shows up in GitHub evidence at
all. This module supplements that signal with **code-quality/complexity
evidence** — not "did they touch this language" but "how substantial and
well-structured is their actual code" — feeding a second, independent
signal into `Vi` alongside Module 1's output.

Out of scope for this module: deciding whether a claimed skill is
"verified" (Module 1), deciding skill-importance weights (Module 3), and
any recruiter dashboard UI (this is a backend signal, not a user-facing
badge, per the module brief's own framing).

## 2. Deviations from the original module brief

Same class of corrections as Module 1's spec, now grounded in this
codebase's real, already-built patterns (including Module 1 itself,
which the brief could only describe hypothetically):

- The brief's schema sketch uses `student_id`; every table in
  `server/supabase/schema.sql` — including Module 1's `github_evidence`
  and `skill_verification` — uses `user_id`. This spec follows suit.
- The brief suggests granular per-role RLS policies. Every table in this
  schema has RLS enabled with **zero policies** (service-role key only,
  authorization done in Express). This spec follows that pattern, not the
  brief's.
- The brief's Section 8 sample code implies `lizard.analyze_file(...)`
  captures nesting depth out of the box. **Verified directly, and this is
  false**: `lizard.analyze_file` is a pre-built `FileAnalyzer` with zero
  extensions loaded (`lizard.py:1136`,
  `analyze_file = FileAnalyzer(get_extensions([]))`), so
  `max_nesting_depth` silently stays `0` for every function regardless of
  actual nesting — confirmed by running a 5-level-deep test function
  through it. Nesting depth is a separate, real extension
  (`lizard_ext/lizardnd.py`) that must be explicitly loaded via
  `lizard.FileAnalyzer(lizard.get_extensions(['nd']))`. Verified this
  produces correct values (`max_nesting_depth: 5` for the same test
  function). This spec uses the correct invocation; see Section 5.
- The brief frames the "should Node call `git clone`" question loosely.
  This spec fetches via GitHub's tarball endpoint instead (Section 4) —
  no new system-level dependency (git binary) for a codebase whose
  existing Python services (`cv_parser`, `skill_verification`) are all
  pure-Python-plus-`requests`.

## 3. Architecture

```
Node/Express (server/src)
  routes/codeAnalysisRoutes.js
  controllers/codeAnalysisController.js
      │  1. decrypt GitHub token (existing OAuthSession + secureToken utils,
      │     same as Module 1)
      │  2. check code_analysis cache freshness (24h, same policy as Module 1)
      │  3. call Python service over HTTP (shared secret header)
      │  4. persist results via models/CodeAnalysis.js
      ▼
Python service (new)  services/code_analysis/
  app.py             — Flask, one internal route, stateless
  repo_fetch.py       — Phase 1: tarball download + extraction, file filtering
  static_analysis.py  — Phase 2: lizard invocation (with the 'nd' extension)
  aggregation.py       — Phase 2: per-repo -> per-student rollup
  exclusion_rules.py   — Phase 3: fork/empty/too-large/tutorial-heuristic filtering
  main.py              — orchestrates fetch -> filter -> analyze -> aggregate
```

Stateless, mirrors `cv_parser`/`skill_verification` exactly — no Supabase
access anywhere in `services/code_analysis/`. Node owns all persistence,
caching, and authorization, exactly as with Module 1.

## 4. Python service — API contract (internal only, not public-facing)

`POST /analyze-repos`, header `X-Api-Key: <CODE_ANALYSIS_API_KEY>` (same
open-if-unset local-dev degradation as the other two services).

Request:
```json
{
  "github_username": "octocat",
  "access_token": "gho_...",
  "repo_names": ["my-ml-project", "todo-app"]
}
```
`repo_names` is supplied by Node (which already knows the student's repo
list — see Section 7's coordination note); this service does not call
`GET /user/repos` itself, unlike Module 1's `github_fetch.py`.

For each repo, in order, capped at the **15** most-recently-relevant
entries in `repo_names` (Node is expected to pass at most 15; this service
also enforces the cap defensively):

1. `GET /repos/{owner}/{repo}` — check `fork` flag; if true, exclude with
   `reason: "fork"`, skip the rest of the steps for this repo.
2. `GET /repos/{owner}/{repo}/tarball` (`stream=True`, `Authorization:
   Bearer <token>`). If the response's `Content-Length` exceeds **25MB**,
   abort the download and exclude with `reason: "too_large"`.
3. Extract into a fresh `tempfile.mkdtemp()` directory using Python's
   stdlib `tarfile` module (`tarfile.open(fileobj=BytesIO(...)).extractall(...)`)
   — no shelling out to `git` or any other binary.
4. Filter the extracted tree before analysis (Section 5) — this happens
   whether or not the repo will end up excluded, since "empty after
   filtering" is itself one of the exclusion reasons.
5. If, after filtering, total line count is under **20**, exclude with
   `reason: "empty"`.
6. Check whether the repo name matches the tutorial-heuristic pattern
   (Section 6). Unlike `fork`/`too_large` (which skip analysis entirely
   and short-circuit to the next repo), a `tutorial_clone_heuristic` match
   does NOT skip step 7 — record `included: false,
   excluded_reason: "tutorial_clone_heuristic"` on the result, but still
   run analysis and populate its metrics fields. Excluded repos are
   informative, not discarded; `included: false` is what keeps them out
   of the *summary* aggregation later (Section 8), not out of the
   `code_analysis` table itself.
7. Run `static_analysis.py` (Section 5) on the filtered file set,
   populating `avg_cyclomatic_complexity`/`total_functions`/
   `total_lines`/`max_nesting_depth`/`language` regardless of the
   `included` flag set in step 6 (a fork or too-large repo, by contrast,
   reaches this point never having had step 7 run at all, per step 1/2's
   short-circuit — their metrics fields stay `null`, as shown in Section
   4's example response).
8. **Always** `shutil.rmtree()` the temp directory before moving to the
   next repo, in a `finally` block — source code is never persisted or
   left on disk after analysis, per the project's ethical/data-minimization
   commitment (Section 0 of the brief).

Response: array of per-repo results —
```json
[
  {
    "repo_name": "my-ml-project",
    "included": true,
    "excluded_reason": null,
    "language": "Python",
    "avg_cyclomatic_complexity": 4.2,
    "total_functions": 38,
    "total_lines": 1204,
    "max_nesting_depth": 5
  },
  {
    "repo_name": "todo-app",
    "included": false,
    "excluded_reason": "fork",
    "language": null,
    "avg_cyclomatic_complexity": null,
    "total_functions": null,
    "total_lines": null,
    "max_nesting_depth": null
  }
]
```
`language` is `lizard`'s detected language of the file with the most NLOC
in that repo (a repo can span several languages; this reports the
dominant one for the `language` column, while the numeric metrics
aggregate across all files `lizard` could parse — cross-language, per
Section 6 of the brief).

If GitHub returns 401 on any call, respond `{"error": "invalid_token"}`
with HTTP 401 (same contract as Module 1, so Node's existing
`invalid_github_token` handling pattern extends naturally). Any other
unexpected exception is caught by a route-level handler and returned as
structured JSON with a 500 status — never a raw Flask HTML error page
(this is a lesson carried over from Module 1's final review, which found
exactly this gap in `cv_parser`-style services).

## 5. Static analysis — file filtering and `lizard` invocation

**File filtering**, applied before any file reaches `lizard`:
- Skip directories: `node_modules`, `vendor`, `dist`, `build`, `.git`,
  `__pycache__`, `.venv`, `venv`.
- Skip files over **500KB**.
- Cap total files walked per repo at **300** (stop walking further once
  hit — repos are processed newest-pushed-first per Section 4, so this
  bounds worst-case time on a monorepo without silently degrading typical
  student repos, per the brief's own risk note in Section 14).
- Only hand `lizard`-supported source extensions to `lizard` (it has its
  own internal extension whitelist; this filtering step's job is to keep
  minified/generated files and non-code assets out, not to duplicate
  lizard's language detection).

**`lizard` invocation** — the corrected form, not the brief's naive
`analyze_file` sample:
```python
import lizard

_analyzer = lizard.FileAnalyzer(lizard.get_extensions(['nd']))

def analyze_repo(file_paths: list) -> list:
    """Returns lizard's per-function results for every analyzable file."""
    results = []
    for path in file_paths:
        try:
            results.append(_analyzer(path))
        except Exception:
            continue  # a single unparseable file must not fail the whole repo
    return results
```
Per-function metrics used: `cyclomatic_complexity`, `nloc`,
`max_nesting_depth` (now genuinely populated). `FileInformation.language`
(exposed by `lizard`'s `FileInfoBuilder`/reader) identifies the dominant
language per Section 4's response shape.

## 6. Exclusion rules (Section 4's reasons, precise definitions)

- `fork` — GitHub API's own `fork: true` on the repo object.
- `too_large` — tarball `Content-Length` header exceeds 25MB (checked
  before download completes, so an oversized repo doesn't fully download
  just to be thrown away).
- `empty` — total line count across all filtered, analyzable files is
  under 20.
- `tutorial_clone_heuristic` — repo name (case-insensitive) contains any
  of: `tutorial`, `clone`, `practice`, `bootcamp`, `learning`, `-starter`,
  `hello-world`. Documented, per the brief's own instruction, as a **soft,
  unreliable heuristic** — not presented as solved. A repo excluded this
  way still has its metrics computed and stored (`included: false`), so
  the exclusion is fully auditable and reversible by a later, better
  heuristic without re-fetching anything.

## 7. Node integration

`server/src/utils/codeAnalysis.js` — one function,
`analyzeRepos(username, accessToken, repoNames)`, calling the route above
(same `fetch` + `AbortSignal.timeout` pattern as Module 1's
`skillVerification.js`; timeout 90s, since tarball download + extraction +
`lizard` across up to 15 repos is heavier than Module 1's metadata-only
fetch).

`server/src/models/CodeAnalysis.js` — plain Supabase CRUD:
`findByUserId`, `findSummaryByUserId`, `latestAnalyzedAt`,
`replaceForUser(userId, repoResults)` (delete-then-insert into
`code_analysis`, same safe-ordering rule as Module 1: only after the
Python call has already succeeded), and
`upsertSummary(userId, summary)` (one row per user, computed from the
just-replaced `code_analysis` rows).

`server/src/controllers/codeAnalysisController.js`:

- `runAnalysis(req, res)` — same ownership resolution as Module 1's
  `runVerification` (self for students; `findOwnedCandidate` from
  `server/src/utils/candidateOwnership.js` for recruiters — **reused
  as-is, no new ownership logic**). Steps:
  1. No GitHub connection/session/token → respond with an empty analysis
     (`qualifying_repo_count: 0`, no `code_analysis` rows) rather than an
     error — this is the "unverifiable, not a failure" case, same
     philosophy as Module 1's `github_not_connected` handling, though
     there is no dedicated `reason` column on this module's tables for
     it (Section 8's schema has no not-connected case to encode — the
     absence of any `code_analysis` rows for a `user_id` already is that
     signal for a summary consumer).
  2. Cache check: if the newest `code_analysis.analyzed_at` for this user
     is under 24h old and `?force=1` isn't set, skip the Python call and
     recompute the summary from existing rows.
  3. `force` gated to `req.user.role === 'student'` only (mirrors Module
     1's fix for the same recruiter-forces-a-student's-quota problem).
  4. Otherwise fetch the student's repo list (`GET /user/repos` via a
     small inline call — **not** reusing Module 1's `github_fetch.py`
     for v1; see the coordination note below), pass up to 15 non-fork
     public repo names to `analyzeRepos`, then `replaceForUser` with the
     result.
  5. Recompute and `upsertSummary`.
  6. On a Python-service failure (non-401 error), respond 502
     `{"error": "code_analysis_service_unavailable"}` — same pattern as
     Module 1's `serviceUnavailableError()` (factor this into a small
     shared helper if convenient during implementation, rather than
     duplicating the error-shaping logic — controller's call at plan
     time).

- `getSummary(req, res)` — same ownership rule, reads
  `code_analysis_summary` only, no recompute.

Routes:
```
POST /api/code-analysis/run                (requireAuth)
GET  /api/code-analysis/:studentId/summary (requireAuth)
```

**Coordination note (not a v1 dependency):** Module 1's Node controller
already fetches and caches a student's repo list in `github_evidence`.
This module currently fetches its own repo list independently (one extra
`GET /user/repos` call per run) rather than reading Module 1's cache — a
real, available optimization now that both modules exist in the same
codebase, but deliberately deferred: coupling this module's cache-read to
Module 1's cache-freshness would create a dependency the brief explicitly
says not to take on for v1 ("you do NOT depend on the semantic
skill-matching module... to build or test this"). Worth revisiting once
both modules are stable.

## 8. Data schema

```sql
create table if not exists public.code_analysis (
  id                        uuid primary key default gen_random_uuid(),
  user_id                   uuid not null references public.users (id) on delete cascade,
  repo_name                 text not null,
  language                  text,
  avg_cyclomatic_complexity numeric,
  total_functions           int,
  total_lines               int,
  max_nesting_depth         int,
  included                  boolean not null default true,
  excluded_reason           text check (excluded_reason in (
                              'fork', 'empty', 'too_large', 'tutorial_clone_heuristic'
                            )),
  analyzed_at               timestamptz not null default now()
);
create index if not exists code_analysis_user_id_idx on public.code_analysis (user_id);

create table if not exists public.code_analysis_summary (
  user_id                uuid primary key references public.users (id) on delete cascade,
  avg_complexity_overall numeric,
  total_loc_overall      int,
  qualifying_repo_count  int not null default 0,
  computed_at            timestamptz not null default now()
);

alter table public.code_analysis enable row level security;
alter table public.code_analysis_summary enable row level security;
-- No policies added — deny-by-default for anon/authenticated, service-role
-- key only, matching every other table in this schema (including Module
-- 1's github_evidence/skill_verification).
```

`avg_complexity_overall` / `total_loc_overall` are computed only across
rows with `included = true` (Section 6's exclusions are real exclusions
from the *summary*, even though their raw metrics are kept in
`code_analysis` for auditability, per the brief's explicit "record the
reason, don't silently drop" requirement).

## 9. Error handling

- GitHub token invalid/revoked → same `invalid_token`/401 contract as
  Module 1; Node treats it as "nothing to analyze," not an error.
- Python service unreachable/times out → Node responds 502 with a
  structured error, not a generic 500 (Module 1's final review caught
  this exact class of bug — a service failure silently becoming a 500,
  or worse, appearing to succeed with wrong data — so this module's
  controller is built with that lesson applied from the start rather
  than needing a fix-round to catch it later).
- A single unparseable file inside a repo must not fail that repo's
  analysis (Section 5's `try/except continue`), and a single failed repo
  (e.g. a 500 from GitHub on one tarball fetch) must not fail the whole
  student's run — collect what succeeds, record what didn't with a
  reason, keep going.
- No partial writes: `code_analysis` rows are only replaced after the
  full set of per-repo results is in hand from the Python service (all
  gathered into memory first, then one delete-then-insert), and
  `code_analysis_summary` is only upserted after that succeeds.

## 10. Testing

Python (`services/code_analysis/tests/`, `pytest`):
- Exclusion rules (`exclusion_rules.py`) against hand-crafted fake repo
  metadata: fork flag, line count under/over 20, tarball size over/under
  25MB, tutorial-name-pattern match/non-match.
- **`max_nesting_depth` regression test**: run `static_analysis.py`
  against a fixture file with genuinely deep nesting and assert the
  returned value is nonzero and matches the expected depth — this is the
  exact gotcha found during design (Section 2), and it must never
  silently regress back to the naive, zero-only invocation.
- Aggregation math (`aggregation.py`): per-repo → per-student rollup on
  synthetic `lizard`-shaped input, confirming excluded repos are excluded
  from the summary's averages but still appear in the raw `code_analysis`
  rows.
- File filtering (`repo_fetch.py`): confirm `node_modules`/`dist`/etc. are
  excluded, and the 500KB/300-file caps are enforced, using a small
  synthetic directory tree — no real GitHub calls in this test.
- Integration test: run the full pipeline against 2-3 real public GitHub
  profiles (team members' own accounts, per the brief's own suggestion)
  and manually sanity-check the numbers look reasonable for the languages
  actually used.

Node (`server/src` — `node:test`, no new dependency, same as Module 1):
- Any pure logic extracted for cache-freshness / not-connected handling
  (reuse Module 1's `skillVerificationHelpers.js` pattern — likely a
  near-identical `isCacheFresh` this module can share rather than
  duplicate, if the plan finds a clean way to do so without creating an
  awkward cross-module import; a small amount of duplication is
  acceptable here over a forced shared abstraction between two otherwise
  independent modules).

## 11. Milestones

1. `services/code_analysis/` scaffolded; tarball fetch + extraction
   working end-to-end for one real GitHub account, no `lizard` yet.
2. `static_analysis.py` integrated with the verified `nd`-extension
   invocation; per-function metrics captured for a test repo, including a
   passing nesting-depth regression test.
3. `aggregation.py` (per-repo → per-student rollup) and
   `exclusion_rules.py` implemented and tested.
4. `app.py` wired up; full Python test suite passing.
5. `code_analysis` / `code_analysis_summary` tables + Node models +
   `runAnalysis`/`getSummary` controller wired end-to-end, reusing
   `candidateOwnership.js` from Module 1.
6. Full pipeline tested against 2-3 real profiles; results sanity-checked
   manually.
