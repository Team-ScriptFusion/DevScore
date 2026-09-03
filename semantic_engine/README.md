# Semantic Analysis & Scoring Engine

**Implementation 02 — the evidence and scoring core of DevScore.**
Branch `Janidu` · KKJD de Alwis (ICT/2022/049)
Rajarata University of Sri Lanka · Department of Computing · ICT3411 / COM3405

> Research ownership: *"Semantic and static code analysis of GitHub repositories
> to verify resume claims against real coding evidence"* — de Alwis & Madhushan.

Everything here lives under `semantic_engine/`. It reads the repo's existing
[`cv_parser/`](../cv_parser/) for claimed skills and adds the verification half:
GitHub mining, static code analysis, claim↔evidence matching, and the weighted
Job Readiness Score.

```bash
cd semantic_engine
pip install -r requirements.txt
python tests/test_engine.py        # 53 tests
```

Every command below is run from `semantic_engine/`. Put the collected CVs in
`semantic_engine/data/cvs/` — that path is gitignored, and it must stay that
way: those are real students' resumes, consented for the study and not for
publication in a public repository.

---

Implementation 01 ([`Team-ScriptFusion/DevScore`](https://github.com/Team-ScriptFusion/DevScore))
answers *"what does this CV claim?"* — OAuth, resume upload, PDF text extraction,
NLP skill identification, GitHub account linking. FR 1–35, all deployed.

This directory answers the half that was left: **is the claim true, and how good
is the code behind it?**

> The CV says React.
> So find their React repositories, read the React code, measure how complex and
> how well-built it is, and turn that into a number a recruiter can defend.

That is Implementation 02 — the semantic matching engine, the AST/static code
analysis, the weighted scoring algorithm, and the Evidence Gap view.

---

## The pipeline

```
              ┌─ cv_parser/ ────────────┐   ← the team's deployed module,
resume.pdf ──▶│ extract_claimed_skills  │     at the repo root (FR 28-32)
              └────────────┬────────────┘
                           ▼
              resume.parser (adapter) ──▶ ClaimedSkill[]   (the set C)
                    │                         │
                    │ GitHub handle + name    │ used to target the mining
                    ▼                         ▼
              github.miner ──▶ RepoEvidence[] ──▶ analysis.* ──▶ CodeMetrics
                                      │                              │
                                      ▼                              ▼
                             matching.semantic ──▶ SkillVerdict[] ◀───┘
                                      │              (the set E)
                                      ▼
                              scoring.engine ──▶ ReadinessReport (0–100)
```

Every number in the output traces back to a named repository, file and metric.
Given only the JSON, you can answer *"why 61 and not 80?"* down to the individual
file that did or did not prove a claim.

---

## Quick start

```bash
pip install -r requirements.txt
export GITHUB_TOKEN=ghp_...        # or just `gh auth login` — the engine finds it
```

```bash
# 1. The roster: who is in the folder, and who can actually be scored?
python cli.py scan data/cvs
```

```
  #  CANDIDATE (from CV)      GITHUB                 SKILLS  NOTE
  4  THARUSHI BANDARA        TharushiB                 26
  7  KAVI RANASINGHE              Kavi-R30               9  filename says 'uploader account'
  9  Binara Silva          no handle                  15
 13  Ravindu Silva           ravindus7                    1
```

```bash
# 2. Score a selection — by index, range, or name/handle substring
python cli.py score --from data/cvs --select 4
python cli.py score --from data/cvs --select 1,4,7-12
python cli.py score --from data/cvs --select jayasuriya

# 3. Or the whole cohort → scores.csv, verdicts.csv, per-candidate JSON, summary.md
python batch.py data/cvs --out data/out
python batch.py data/cvs --select 1,4,7-12 --scorable-only

# 4. Build the selectable cohort dashboard from those results
python cli.py cohort data/out/reports --out data/out/cohort.html
```

Other entry points:

```bash
python cli.py score resume.pdf --html report.html --json report.json  # one file
python cli.py parse resume.pdf          # resume side only — no API calls, instant
python cli.py score resume.pdf --boolean  # the proposal's original Vᵢ ∈ {0,1}
```

### Picking candidates

`cli.py scan` prints a stable, indexed roster; `--select` consumes those indices.
Expressions mix freely: `"3"`, `"1,4,9"`, `"5-12"`, `"1,4,7-12"`, a name or handle
substring like `"jayasuriya"`, or `"all"`. A selection that matches nothing is an
**error**, not an empty run — "scored 0 candidates" and "scored everything
successfully" are indistinguishable in a log file otherwise.

The roster is built from resume parsing alone, so it costs no API calls and a
mistyped selection fails before a single GitHub request is spent.

### The cohort dashboard

`cli.py cohort` renders every scored candidate into one self-contained page:
sortable and filterable, with checkboxes to pick a shortlist and a **skill matrix**
comparing the selected candidates side by side. The matrix cells carry the
evidence *tier*, not a tick — `declared` and `applied` are both "has React" to a
keyword matcher, and the comparison view is exactly where that distinction earns
its keep.

Candidates with no GitHub handle are **listed, not hidden**, and shown as *not
assessable* rather than scored 0 — a zero in a ranked list reads as "worst
candidate" instead of "outside what this method can see".

Run the tests:

```bash
python tests/test_engine.py          # or: python -m pytest tests -q
```

53 tests, every one anchored to a failure mode that would produce a *plausible
but wrong score* rather than a crash — a crash gets noticed, a candidate quietly
scored 12 points low does not.

---

## Where the claims come from

**Skill extraction is not done in this directory.** It is done by
[`cv_parser/`](../cv_parser/) at the repository root — the module already
deployed as Implementation 01 (FR 28–32), owned by the team and untouched here.

That is deliberate. `cv_parser` is the authority on what a CV claims because it
is what the **live system runs** and what the backend stores in `resume_skills`.
If this engine extracted skills its own way, a recruiter's dashboard and the
score beside it would disagree about the same candidate — and the disagreement
would be invisible, because both numbers would look reasonable.

[`engine/resume/parser.py`](engine/resume/parser.py) is a thin adapter. It calls
`extract_text_from_pdf`, `clean_text` and `extract_claimed_skills` **unchanged**,
then adds the two things Implementation 02 needs and Implementation 01 never had
to answer:

- the candidate's **GitHub handle** — no claim is verifiable without a repository
- the candidate's **name** — read from the CV, never the filename

Both live in [`engine/resume/identity.py`](engine/resume/identity.py).

`engine/resume/parser.py` locates `cv_parser/` by walking up the directory tree,
so it works unchanged whether it sits beside it in this repo or is checked out
standalone. **Extending the skill dictionary is done in `cv_parser/`, not here** —
this engine picks the change up automatically, and
`test_crosswalk_covers_the_deployed_dictionary` fails if a newly added skill has
no verification recipe and no explicit note.

### Two vocabularies, joined by a crosswalk

| | `cv_parser/skills_dictionary.py` | `engine/ontology.py` |
|---|---|---|
| Entries | **121** | **89** |
| Answers | "does this CV claim it?" | "what would it look like in code?" |
| Carries | aliases, category | + evidence channels, difficulty weight |

Neither is a subset of the other, so `ontology.CV_PARSER_CROSSWALK` resolves the
overlap. Of cv_parser's 121 skills:

- **83** map onto a verification recipe and are scored
  (`OpenCV` → Computer Vision, `Android Development` → Android (Native),
  `scikit-learn` → Machine Learning, `Jest`/`PyTest`/`JUnit` → Unit Testing,
  `GitHub` → Git, `MariaDB` → MySQL)
- **14** are recognised but not code-verifiable (Jira, Figma, Agile, Postman…)
- **24** have no recipe here yet (Terraform, Redux, Cypress, WordPress…)

The last two groups are still **reported** — as claims with `verifiable=False`
and weight 0, so they reach the recruiter without distorting the score. Dropping
them would hide a real claim; scoring them down would be measuring our own blind
spot. Mappings that would over-credit (`Nuxt.js` → Vue.js, `Cypress` → Unit
Testing) are deliberately left out.

A test asserts every cv_parser skill either maps, resolves, or is listed in
`CV_PARSER_UNMAPPED_NOTE` — so a skill added upstream can never silently vanish
from scoring.

---

## How a skill gets verified

Each skill in [`engine/ontology.py`](engine/ontology.py) carries six evidence
channels. They are combined into a **tier** — the ordering is the whole point:

| Tier | What it means | E |
|---|---|---|
| `none` | Claimed, nothing found | 0.00 |
| `ambient` | The repo contains the language. Nothing more. | 0.25 |
| `declared` | A manifest lists the dependency, but no code imports it | 0.45 |
| `used` | Actually imported/`using`/`#include`d in code they wrote | 0.70 |
| `applied` | Used **and** idiomatic — `useState`, `@Autowired`, `pd.DataFrame` | 0.90 |
| `mastered` | Applied across ≥ 2 repositories **that contain real code for it**, with real complexity | 1.00 |

`declared` vs `used` is the distinction a keyword matcher cannot make. It is
what separates a candidate who ran `create-react-app` from one who wrote
components.

**Two rules keep this honest:**

1. **Markers are matched against comment- and string-stripped source.**
   A README listing fifteen technologies contributes nothing. `// TODO: use
   React here` is not evidence of React. Evidence must be executable code.
   ([`engine/analysis/textprep.py`](engine/analysis/textprep.py))

2. **Markers are gated by file language.** Before this existed, Ruby's `def`/`end`
   matched Python files, MATLAB's `function ... =` matched JavaScript, and C#'s
   `namespace` matched C++ — handing one real candidate four confident
   "unclaimed strengths" in languages they had never written.

3. **Repository counts distinguish code from ambience.** A TypeScript-heavy
   account gives React an ambient hit in *every* repo. Mastery counts only
   repositories where the skill appears in real code, and so does the
   explanation text — otherwise "verified across 13 repositories" is printed on
   the strength of six files in two of them.

---

## How the code is judged

Python gets a **real AST walk** (`ast`, McCabe cyclomatic complexity, nesting
depth, docstring and type-annotation coverage, exception handling). Every other
language gets a token-level analyser on stripped source, and its results are
**labelled `brace_heuristic`** and discounted — an estimate presented as a
measurement is the research failure; an estimate labelled as one is a reasonable
trade for a project whose NFRs say "open-source, zero licence cost".

Complexity is scored as a **band, not a ramp**:

| Cyclomatic / function | Reading | Score |
|---|---|---|
| < 1.5 | trivial — getters, config, re-exports | 0.15 |
| 1.5 – 3 | simple CRUD | 0.45 |
| **3 – 8** | **real branching logic** | **1.00** |
| 8 – 15 | works, but complexity is a smell | 0.75 |
| > 15 | one god-function | 0.45 |

Because *more complex is not better*. A monotonic ramp would teach the model to
prefer unmaintainable code. Peak reward sits where a competent engineer's code
actually lives — which is also what lets the engine tell a 400-line React file
that is fifteen composed components apart from a 400-line React file that is one
component with a fifteen-branch conditional.

---

## The score

The Project Proposal's formula is kept exactly:

```
I = ( Σ Wᵢ · Vᵢ ) / ( Σ Wᵢ ) × 100
```

**What changed is Vᵢ.** A boolean cannot distinguish someone who once imported
React from someone who has shipped three React apps with tests, so:

```
Vᵢ = 0.40·E + 0.22·C + 0.18·D + 0.12·R + 0.08·Q      capped at E
```

| | Signal | Source |
|---|---|---|
| **E** | Evidence strength | the tier above |
| **C** | Complexity | AST / static analysis |
| **D** | Depth | log-scaled LOC × files × repos |
| **R** | Recency | exponential decay, 14-month half-life |
| **Q** | Craft | tests, CI, error handling, typing, duplication |

Verification dominates (0.40) — this is a verification system before it is a
quality system. Code quality (0.22) ranks **above** code volume (0.18) on
purpose. And Vᵢ is capped at E, so a huge stale codebase can never outrank a
genuinely verified skill on volume alone.

Setting E's coefficient to 1.0 and the rest to 0 reproduces the proposal's
original boolean formula exactly — which is what makes the extension *testable*
rather than merely asserted. See [Validating the model](#validating-the-model).

### The difficulty weights, Wᵢ

The proposal gives two illustrative values (Python = 1.0, HTML = 0.5) with no
derivation, and flags this as open work. Weights that directly determine the
score cannot be assigned by intuition in a research deliverable, so each is the
product of two documented 1–5 axes:

```
Wᵢ = 0.55·depth + 0.45·scarcity     rescaled onto [0.35, 1.00]
```

- **depth** — irreducible engineering understanding required. A property of the
  technology; stable over time. HTML = 1, C++ = 5.
- **scarcity** — competent practitioners relative to demand. This is *market
  data* and is expected to drift.

Both axes are stored per skill, so no weight is ever a magic number: it is
recomputable, auditable, and recalibratable. `tools/calibrate_weights.py`
re-derives `scarcity` from a scraped job-description corpus without touching
`depth` — exactly the split the research design calls for.

### Four bounded adjustments

**Small-sample shrinkage.** A weighted ratio over two claims is a ratio computed
from almost no data, and left alone it *rewards under-claiming*. On the real
cohort a candidate who listed one verifiable skill and proved it scored **75.0**,
ahead of one who listed twelve and proved nine. The ratio is correct; the
conclusion is absurd. So it is smoothed toward a prior, as any small-denominator
rate would be:

```
base = ( Σ WᵢVᵢ + k·W̄·μ ) / ( Σ Wᵢ + k·W̄ )      k = 1.5,  μ = 0.30
```

At a strong ratio of 81 this costs a 1-claim CV ~31 points, a 5-claim CV ~11,
and a 12-claim CV under 6 — decisive where the denominator is meaningless,
nearly invisible where it is not. Both the raw and smoothed values appear in the
report, so the correction is never silent.


**Integrity penalty (≤ 12 pts).** An unverified claim already scores Vᵢ = 0, so a
separate penalty is only justified for what the base score cannot express: the
difference between *no evidence because there was nothing to look at* and *no
evidence despite twenty active repositories*. Only the second is a credibility
signal, so the penalty is scaled by **evidence capacity**:

```
penalty = 12 × unverified_weight_share × capacity
```

A candidate with no GitHub link has capacity ≈ 0 and takes **no penalty at all**.
That is not generosity — it is the difference between measuring the candidate and
measuring our own coverage. Charging someone for our blind spot is precisely the
bias this project exists to remove.

**Breadth bonus (≤ 5 pts).** Verified skills spanning multiple engineering areas.
Capped low: breadth is worth less than depth, and an uncapped bonus rewards
listing everything.

**Confidence — reported, never applied.** A low-confidence 70 and a
high-confidence 70 are the same claim about the candidate and a different claim
about *us*. Folding uncertainty into the number would hide that distinction from
the recruiter, so it is surfaced beside the score instead.

---

## Whose CV is this?

The candidate's name is read from **inside the CV**, never from the filename.

That is not fussiness. Google Drive appends the name of whoever *uploaded* a
file, and in the collected dataset that is frequently not whose CV it is:

| File | Filename claims | CV actually says | Handle |
|---|---|---|---|
| `Anura Perera … - Binara Silva.pdf` | Binara Silva | **Anura Perera** | `anuraperera` |
| `Jayasuriya_Resume… - Menaka Jayasuriya.pdf` | Menaka Jayasuriya | **A.B.C.D. Jayasuriya** | `MenakaJ` |
| `Blue and White Minimalist… - uploader account.pdf` | uploader account | **Kavi Ranasinghe** | `Kavi-R30` |

Trusting the filename attributes one student's verified skills to another
student **by name** — the worst failure available to a system whose entire
output is a judgement about a named person.

The GitHub handle was never affected: it is read from the CV's own link
annotations and body text, so it always belongs to that CV's owner. But both
values are kept (`candidate` and `filename_label` in `scores.csv`) and `cli.py
scan` flags every disagreement, so the provenance is auditable rather than
invisible.

Name extraction handles the layouts that actually occur: letter-spaced Canva
headings (`J A N I D U` → `JANIDU`), names split one word per line, and phone
numbers interleaved onto the heading line by multi-column extraction. It returns
**nothing** rather than guessing — 42 of 47 CVs yield a name; the rest fall back
to the filename and are marked `name from filename` in the roster.

### Supplying a handle the CV left off

Some CVs name **no GitHub account at all** — the candidate wrote "GitHub" as a
skill without a URL, or just forgot the link. The parser is right to return
nothing (a guessed handle scores someone against a stranger's repos), but "no
handle in the CV" is not "no GitHub account", and the team often knows the real
one.

`<cv-folder>/handle_overrides.json` supplies them, keyed by the CV's exact filename:

```json
{
  "Binara Silva - Software Engineer Undergraduate CV (2) - Binara Silva.pdf": {
    "github": "https://github.com/BinaraSilva",
    "note": "CV lists 'GitHub' as a skill but includes no profile URL; supplied by the team"
  }
}
```

A `github` value may be a full URL or a bare handle. An override **always wins**
over a handle found in the CV — it is a deliberate correction — and every score
built on one is recorded as `handle_source = override` in `scores.csv`, flagged
in `cli.py scan`, and badged **handle supplied** on the cohort dashboard, so a
supplied handle is never mistaken for one the candidate put on their own CV.

Real example from this dataset: `Binara Silva`'s CV claims Machine Learning,
Computer Vision, Flutter, Java and Python but includes no GitHub URL. Scored
against his real account (`BinaraSilva`), the public repos back only frontend
web work — **14.3 / 100**, 4 of 15 claims verified, confidence 35%. That is the
system doing exactly its job: the resume asserts a broad ML/mobile/backend
skillset, the evidence shows a portfolio site and a clothing-store front end.

---

## What the engine refuses to do

These are design commitments, not gaps.

**"Unverified" never means "lying."** The label is *no public evidence found*,
and the dashboard says so in words. Private and organisation repositories are out
of scope by design (an ethical constraint, not just a technical one), so a
candidate who works in them is invisible here. A UI that renders that absence as
a red X teaches recruiters to read it as deception — introducing a new bias while
claiming to remove an old one. This is the "verification false negative" risk the
project summary names, addressed in the output format rather than hand-waved.

**Unclaimed strengths are surfaced but never scored.** A candidate with three
strong Django repos who forgot to list Django gets it shown to the recruiter — it
is a hiring signal. It cannot raise the integrity score, because that score
measures claim honesty and rewarding omission would corrupt it.

**Non-code skills are excluded from the denominator, not scored zero.** Agile,
Leadership, Communication, Figma. Scoring someone down for a skill we cannot
check would be measuring our blind spot and calling it their weakness.

**Nothing a candidate merely wrote down counts.** Not in a README, not in a
comment, not in a string literal.

---

## Validating the model

```bash
python batch.py data/cvs --out data/out
python tools/ablation.py data/out/reports --experts data/expert_rankings.csv
```

The ablation recomputes every stored report under five Vᵢ formulations —
`boolean` (the proposal as written), `evidence_only`, `no_complexity`,
`no_recency`, `full` — and ranks each against the industry panel's manual
ordering (Spearman ρ with a permutation test, Pearson r, MAE, top-k overlap).

**`no_complexity` is the row that matters.** It isolates what reading the code
actually contributed. If `full` does not beat `no_complexity` against the expert
baseline, then the static analysis added nothing, and the honest conclusion is to
report that — a negative result about a component you built is still a result.

Expert file format:

```csv
candidate,expert_score
Anura Perera,72
```

---

## Findings from the collected cohort (47 CVs)

A full run over the real dataset — `python batch.py data/cvs --out data/out` —
produced results worth carrying into the write-up, because they bound what the
method can achieve.

**Coverage**

| | |
|---|---|
| CVs processed | 47 |
| Scored against a GitHub profile | **32 (68%)** |
| No discoverable GitHub handle | 15 |
| Resume parsing failures (image-only PDFs) | 2 |

**Scores** — mean 41.0, median 43.9, range 0–66.6, σ 15.9.
1 solid · 14 partial · 11 thin · 6 largely unevidenced.

**Claim verification** — of 368 verifiable claims across the cohort:
**53% verified in code**, 15% weakly evidenced, **32% with no public evidence**.
That last figure is the Verification Gap the project set out to measure, and it
is large enough to be the headline result — provided it is reported honestly as
*unevidenced*, which for the third of candidates with no handle at all is a
limit of the method rather than a property of the candidate.

**Things that only showed up by running it on real data:**

- **32 of 47 CVs (68%) yield a discoverable GitHub handle** (31 from the CV, 1 supplied via `handle_overrides.json`). The other third
  cannot be verified at all — not because the candidates lack repositories, but
  because their CV never says so. This is a ceiling on the method's coverage and
  belongs in the limitations section, not in the candidates' scores.
- **Link annotations matter more than expected.** Several CVs (Canva/Figma
  exports) render GitHub as a clickable icon with *no visible URL text*. Text-only
  extraction finds nothing; reading the PDF's `/Annots` recovers the handle.
- **2 CVs have no text layer at all** — a single flattened page image. Without
  the optional OCR dependency they parse to zero skills. They are reported as
  `no_text_layer_and_ocr_unavailable`, distinct from a genuine parse failure, so
  a missing optional dependency cannot masquerade as a dataset problem.
- **One false-handle class had to be fixed.** `GitHub | 2025`, `GitHub projects`
  and `Github Analysis` were all confidently reported as usernames by a
  permissive regex. A wrong handle is worse than no handle — it scores the
  candidate against a stranger's repositories.
- **Under-claiming beat over-delivering, until it was fixed.** A candidate who
  listed *one* verifiable skill and proved it topped the cohort at **75.0**,
  ahead of one who listed twelve and proved nine. This is what motivated the
  shrinkage term above; that candidate now scores 51.0 and sits among peers with
  comparable evidence.
- **Marker leakage across languages was producing confident nonsense.** Before
  the language gate, one candidate was credited with four "unclaimed strengths"
  — Ruby, MATLAB, C#, SQLite — in languages they had never written a line of.

---

## Layout

```
../cv_parser/            the team's deployed skill extractor (FR 28-32) — not edited here
engine/
  resume/parser.py       thin ADAPTER over cv_parser (see below)
  resume/identity.py     GitHub handle + candidate name — what cv_parser omits
  ontology.py            evidence channels, derived weights, cv_parser crosswalk
  models.py              dataclasses; ReadinessReport is self-explaining
  github/client.py       REST client: disk+ETag cache, rate-limit budget guard
  github/miner.py        targeted sampling — repo ranking, file picking, manifests
  analysis/textprep.py   comment/string stripping  ← load-bearing
  analysis/python_ast.py exact McCabe complexity via the ast module
  analysis/brace.py      token-level analyser for every other language
  analysis/dispatch.py   normalisation: complexity bands, craft, depth, recency
  matching/semantic.py   claim ↔ evidence, tier promotion, unclaimed strengths
  scoring/engine.py      Vᵢ, the weighted ratio, the three adjustments
  report/html.py         standalone Evidence Gap dashboard (no CDN, no build)
  report/cohort.py       selectable cohort dashboard + side-by-side skill matrix
  selection.py           indexed roster, --select resolution, handle overrides
  pipeline.py            orchestration
service/app.py           Flask API — mirrors cv_parser's shape exactly
cli.py                   scan / score / parse / cohort
batch.py                 cohort runner → scores.csv, verdicts.csv, summary.md
tools/ablation.py        boolean vs continuous vs expert baseline
tools/calibrate_weights.py   re-derive scarcity from job-description data
supabase/schema.sql      persistence tables for Implementation 01's database
tests/test_engine.py     53 tests, all on silent-failure paths
```

---

## Integrating with the MERN backend

`service/app.py` deliberately mirrors `cv_parser/app.py` — Flask, `X-Api-Key`
shared secret, degrade-to-open when unconfigured — so Express gains one base URL
and no new patterns.

```
GET  /health          liveness + whether a GitHub token is configured
POST /parse           multipart resume=<pdf>            → claims only, no API calls
POST /score           multipart resume=<pdf>, github=?  → full report (or ?format=html)
POST /score-github    json {github, skills[]}           → ★ use this one in production
GET  /ontology        the skill catalogue with derived weights
```

**Use `/score-github`.** Implementation 01 already stores extracted skills in
`resume_skills`; re-uploading and re-parsing the PDF on every recruiter-triggered
scoring run is wasted work.

Scoring one candidate takes tens of seconds and up to ~100 GitHub calls, which is
past what belongs in a synchronous request. The production shape is a job queue —
POST returns 202, a worker runs the pipeline, the dashboard polls. That is
Implementation 03; this service is the reference implementation the queue calls.
The NFR budget (15–20 s to render a score) is only reachable with a warm cache.

`supabase/schema.sql` adds `job_readiness_scores` and `skill_verdicts` alongside
the existing tables. Note that Implementation 01 settled the SDS's
MongoDB-vs-MySQL inconsistency in favour of **Supabase/Postgres**
(`server/supabase/schema.sql`); the SDS chapters still need updating to match.

---

## Rate limits, honestly

Scoring one candidate properly costs roughly
`1 (user) + 1 (repos) + R×(languages + tree) + F (files)` ≈ **60–100 calls**.
A 100-candidate validation run is ~10,000 — twice the hourly budget.

- **Disk cache.** Every GET is cached and keyed by URL, with the ETag stored;
  refreshes revalidate with `If-None-Match`, and a 304 costs nothing against the
  limit. Re-running the batch while tuning weights is free.
- **Budget guard.** Below a reserve, calls raise `RateLimitExhausted` instead of
  returning partial data — which would silently give a *lower* score to whoever
  happened to be scored last. A missing score is better than a wrong one.
- **Resumable batches.** `batch.py --resume-from data/out/scores.csv` skips
  candidates already scored.

Without a token you get 60 requests/hour — about half of one candidate.

---

## Known limitations

- **Non-Python complexity is heuristic.** Labelled as such, discounted, and
  visible per file in the report. tree-sitter would fix it at the cost of a
  compiled dependency.
- **Sampling, not exhaustive analysis.** Up to ~10 files per repo across the
  top-ranked repositories. Rate limits make full analysis impossible, and past a
  point more code does not improve the verdict.
- **Forks are excluded.** A fork proves a button click, not authorship. Counted
  and reported, never used as evidence.
- **SQL and utility-CSS need raw text.** Their idioms legitimately live inside
  string literals, so `search_raw` waives comment/string stripping for those
  specific skills. This is the one deliberate hole in rule 1 above, granted one
  skill at a time rather than globally.
- **Commit attribution is by GitHub account.** Work committed under a different
  email that GitHub has not linked is invisible.

---

## Ethics

**Every candidate name, GitHub handle and phone number in this directory is
fictional.** The behaviours they illustrate are real and were observed on the
collected cohort, but the identities are stand-ins: this repository is public,
and the Ethical Review Clearance requires personal identifiers to be removed.
Do not substitute real participant names back in when editing these examples.

Public repositories only — private repositories are never accessed. The cohort
itself was collected under that clearance with informed consent, and the CVs
contain personal data — names, phone numbers, addresses. `semantic_engine/data/`
is gitignored and **must stay that way**. Reports are pseudonymised by filename
only; anonymise before any public evaluation view.

Students cannot see their own score — a deliberate design decision in the parent
project to prevent gaming and ranking anxiety. Nothing in this engine should be
exposed on a student-facing route.
