# GitHub-Backed Skill Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given a student's claimed skills and connected GitHub account, produce a per-skill verification result (verified/unverified, method, confidence, reason) stored in Supabase and exposed over a Node API — the `Vi` input to DevScore's WVR formula.

**Architecture:** A new stateless Python/Flask microservice (`services/skill_verification/`) fetches public GitHub repo evidence and runs direct + semantic skill matching, called over HTTP from a new Node controller (`server/src`) that owns all persistence, caching, and authorization — mirroring the existing `cv_parser` integration pattern exactly.

**Tech Stack:** Python 3 / Flask / `requests` / `sentence-transformers` (new service); Node/Express / `@supabase/supabase-js` (existing server, extended); `pytest` (Python tests); Node's built-in `node:test` (Node tests, no new dependency).

**Spec:** `docs/superpowers/specs/2026-09-02-github-skill-verification-design.md`

## Global Constraints

- The Python service is stateless — it never touches Supabase, exactly like `cv_parser`.
- Only public, non-fork repos may be fetched — never request or use private-repo data.
- Cap evidence fetching at the 30 most-recently-pushed non-fork public repos per student.
- Rate-limit floor: stop fetching further repos once `X-RateLimit-Remaining` drops below 10, and return what was gathered so far rather than failing.
- Semantic match threshold is 0.65 — an unvalidated starting point. Do not tune it against the project's expert-ranking dataset (reserved for the scoring module).
- New tables (`github_evidence`, `skill_verification`) get RLS enabled with **zero policies** — service-role key only, identical to every existing table in `schema.sql`.
- Node ↔ Python auth uses a shared-secret `X-Api-Key` header; an unset key means open access (matches `cv_parser`'s local-dev degradation).
- Reuse cached `github_evidence` if the newest `fetched_at` is under 24h old, unless the caller forces a re-run.
- No new Node test-runner dependency — use the built-in `node:test` module.
- One small, deliberate deviation from the spec: `recruiterController.getCandidate`'s ownership check is **not** refactored to share code with the new `candidateOwnership.js` helper. Its response shape needs the full `jobs`/`applications` lists (for `titleById`/`appliedRoles`), not just a yes/no, so consolidating them would reshape an unrelated, already-working controller for marginal benefit. `candidateOwnership.js` is written fresh, independently, for the new controller's simpler yes/no need.

---

## Part A — Python skill-verification service

### Task 1: Scaffold the service + synonym normalization

**Files:**
- Create: `services/skill_verification/synonyms.py`
- Create: `services/skill_verification/requirements.txt`
- Create: `services/skill_verification/requirements-dev.txt`
- Create: `services/skill_verification/tests/__init__.py` (empty)
- Create: `services/skill_verification/tests/conftest.py`
- Test: `services/skill_verification/tests/test_synonyms.py`

**Interfaces:**
- Produces: `synonyms.normalize(term: str) -> str` — used by Task 2's direct matcher.

- [ ] **Step 1: Create the service directory and dependency files**

`services/skill_verification/requirements.txt`:
```
flask==3.1.3
gunicorn==26.0.0
requests==2.32.3
sentence-transformers==3.3.1
```

`services/skill_verification/requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.4
```

- [ ] **Step 2: Add `tests/conftest.py` so tests can import service modules regardless of cwd**

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

Also create an empty `services/skill_verification/tests/__init__.py`.

- [ ] **Step 3: Write the failing test**

`services/skill_verification/tests/test_synonyms.py`:
```python
from synonyms import normalize


def test_normalize_passes_through_unknown_terms():
    assert normalize("Python") == "python"


def test_normalize_resolves_known_synonym():
    assert normalize("JS") == "javascript"


def test_normalize_strips_and_lowercases():
    assert normalize("  Golang ") == "go"


def test_normalize_empty_string():
    assert normalize("") == ""
```

- [ ] **Step 4: Install dependencies and run the test to verify it fails**

```bash
cd services/skill_verification
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_synonyms.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'synonyms'`

- [ ] **Step 5: Write the minimal implementation**

`services/skill_verification/synonyms.py`:
```python
"""
Skill/language-name synonym table for direct matching (Phase 1). Grow this
as real student data surfaces new aliases — this is a living list, not a
one-time task (per the module's known risk: normalization needs ongoing
tuning).
"""

SYNONYMS = {
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "py": "python",
    "csharp": "c#",
    "c sharp": "c#",
    "cpp": "c++",
    "c plus plus": "c++",
    "node": "node.js",
    "nodejs": "node.js",
    "reactjs": "react",
    "react.js": "react",
    "vuejs": "vue",
    "vue.js": "vue",
    "postgres": "postgresql",
    "html5": "html",
    "css3": "css",
    "k8s": "kubernetes",
}


def normalize(term: str) -> str:
    """Lowercase, strip, and resolve through the synonym table."""
    key = term.strip().lower()
    return SYNONYMS.get(key, key)
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd services/skill_verification
python -m pytest tests/test_synonyms.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add services/skill_verification/synonyms.py services/skill_verification/requirements.txt services/skill_verification/requirements-dev.txt services/skill_verification/tests/
git commit -m "Add skill-verification service scaffold and synonym normalization"
```

---

### Task 2: Direct matcher (Phase 1)

**Files:**
- Create: `services/skill_verification/direct_matcher.py`
- Test: `services/skill_verification/tests/test_direct_matcher.py`

**Interfaces:**
- Consumes: `synonyms.normalize(term: str) -> str` (Task 1)
- Produces: `direct_matcher.direct_match(claimed_skill: str, repos: list[dict]) -> dict | None`. Each `repos` item has at least `{"name": str, "languages": {lang_name: byte_count}}`. Returns `None` when no match, or `{"skill": str, "verified": True, "method": "direct_match", "confidence": 1.0, "evidence_repo": str, "reason": None}`. Used by Task 5's orchestration.

- [ ] **Step 1: Write the failing test**

`services/skill_verification/tests/test_direct_matcher.py`:
```python
from direct_matcher import direct_match


def test_direct_match_exact_language():
    repos = [{"name": "my-app", "languages": {"Python": 8000}}]
    result = direct_match("Python", repos)
    assert result == {
        "skill": "Python",
        "verified": True,
        "method": "direct_match",
        "confidence": 1.0,
        "evidence_repo": "my-app",
        "reason": None,
    }


def test_direct_match_resolves_synonym():
    repos = [{"name": "frontend", "languages": {"JavaScript": 5000}}]
    result = direct_match("JS", repos)
    assert result["verified"] is True
    assert result["evidence_repo"] == "frontend"


def test_direct_match_no_matching_language():
    repos = [{"name": "my-app", "languages": {"Python": 8000}}]
    assert direct_match("Kubernetes", repos) is None


def test_direct_match_ignores_trivial_byte_count():
    repos = [{"name": "my-app", "languages": {"Python": 50}}]
    assert direct_match("Python", repos) is None


def test_direct_match_picks_repo_with_most_bytes():
    repos = [
        {"name": "small", "languages": {"Python": 300}},
        {"name": "big", "languages": {"Python": 9000}},
    ]
    result = direct_match("Python", repos)
    assert result["evidence_repo"] == "big"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/skill_verification
python -m pytest tests/test_direct_matcher.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'direct_matcher'`

- [ ] **Step 3: Write the minimal implementation**

`services/skill_verification/direct_matcher.py`:
```python
"""Phase 1 — deterministic language-tag matching (module spec §6)."""

from synonyms import normalize

# A single auto-generated config file (e.g. a stray .gitignore-tracked
# lockfile) can register a few bytes of a language GitHub didn't mean to
# highlight as real usage — this floor filters that noise out.
MIN_LANGUAGE_BYTES = 200


def direct_match(claimed_skill: str, repos: list) -> dict | None:
    """
    Returns a verified match if `claimed_skill` (or a synonym) appears as a
    GitHub language tag with a non-trivial byte count in any of `repos`,
    else None (caller falls through to semantic matching).
    """
    target = normalize(claimed_skill)
    best_repo = None
    best_bytes = 0

    for repo in repos:
        for lang, byte_count in repo.get("languages", {}).items():
            if normalize(lang) == target and byte_count > best_bytes:
                best_bytes = byte_count
                best_repo = repo["name"]

    if best_repo is not None and best_bytes >= MIN_LANGUAGE_BYTES:
        return {
            "skill": claimed_skill,
            "verified": True,
            "method": "direct_match",
            "confidence": 1.0,
            "evidence_repo": best_repo,
            "reason": None,
        }
    return None
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/skill_verification
python -m pytest tests/test_direct_matcher.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add services/skill_verification/direct_matcher.py services/skill_verification/tests/test_direct_matcher.py
git commit -m "Add Phase 1 direct skill matcher"
```

---

### Task 3: GitHub evidence fetcher (Phase 0)

**Files:**
- Create: `services/skill_verification/github_fetch.py`
- Test: `services/skill_verification/tests/test_github_fetch.py`

**Interfaces:**
- Produces:
  - `github_fetch.InvalidTokenError` (exception class)
  - `github_fetch.fetch_repos(github_username: str, access_token: str) -> dict` returning `{"repos": [{"name": str, "is_fork": bool, "languages": dict, "readme_text": str, "pushed_at": str}], "rate_limited": bool}`. Raises `InvalidTokenError` on a 401 from GitHub. Used by Task 6's `/fetch-evidence` route.
  - `github_fetch.MAX_REPOS` (int, 30) and `github_fetch.RATE_LIMIT_FLOOR` (int, 10) — module-level constants, referenced directly by tests.

- [ ] **Step 1: Write the failing test**

`services/skill_verification/tests/test_github_fetch.py`:
```python
import base64
from unittest.mock import patch

import github_fetch
from github_fetch import InvalidTokenError, fetch_repos


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {"X-RateLimit-Remaining": "100"}
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._json

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


def _repo(name, fork=False, private=False, pushed_at="2026-08-01T00:00:00Z"):
    return {
        "name": name,
        "full_name": f"octocat/{name}",
        "fork": fork,
        "private": private,
        "pushed_at": pushed_at,
    }


def test_fetch_repos_happy_path():
    repo_list = [_repo("proj-a")]
    readme_b64 = base64.b64encode(b"# Proj A\nA machine learning project.").decode()

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/user/repos"):
            return FakeResponse(200, repo_list)
        if url.endswith("/languages"):
            return FakeResponse(200, {"Python": 5000})
        if url.endswith("/readme"):
            return FakeResponse(200, {"content": readme_b64})
        raise AssertionError(f"unexpected URL {url}")

    with patch("github_fetch.requests.get", side_effect=fake_get):
        result = fetch_repos("octocat", "token123")

    assert result["rate_limited"] is False
    assert len(result["repos"]) == 1
    repo = result["repos"][0]
    assert repo["name"] == "proj-a"
    assert repo["is_fork"] is False
    assert repo["languages"] == {"Python": 5000}
    assert "machine learning" in repo["readme_text"].lower()
    assert repo["pushed_at"] == "2026-08-01T00:00:00Z"


def test_fetch_repos_filters_private_and_forks():
    repo_list = [
        _repo("public-own"),
        _repo("private-own", private=True),
        _repo("forked", fork=True),
    ]

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/user/repos"):
            return FakeResponse(200, repo_list)
        if url.endswith("/languages"):
            return FakeResponse(200, {})
        if url.endswith("/readme"):
            return FakeResponse(200, {"content": ""})
        raise AssertionError(f"unexpected URL {url}")

    with patch("github_fetch.requests.get", side_effect=fake_get):
        result = fetch_repos("octocat", "token123")

    names = [r["name"] for r in result["repos"]]
    assert names == ["public-own"]


def test_fetch_repos_caps_at_max_repos(monkeypatch):
    monkeypatch.setattr(github_fetch, "MAX_REPOS", 2)
    repo_list = [_repo(f"repo-{i}") for i in range(5)]

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/user/repos"):
            return FakeResponse(200, repo_list)
        if url.endswith("/languages"):
            return FakeResponse(200, {})
        if url.endswith("/readme"):
            return FakeResponse(200, {"content": ""})
        raise AssertionError(f"unexpected URL {url}")

    with patch("github_fetch.requests.get", side_effect=fake_get):
        result = fetch_repos("octocat", "token123")

    assert len(result["repos"]) == 2


def test_fetch_repos_raises_on_invalid_token():
    def fake_get(url, headers=None, params=None, timeout=None):
        return FakeResponse(401, {"message": "Bad credentials"})

    with patch("github_fetch.requests.get", side_effect=fake_get):
        try:
            fetch_repos("octocat", "bad-token")
            assert False, "expected InvalidTokenError"
        except InvalidTokenError:
            pass


def test_fetch_repos_stops_early_when_rate_limited():
    repo_list = [_repo("repo-a"), _repo("repo-b"), _repo("repo-c")]
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/user/repos"):
            return FakeResponse(200, repo_list)
        if url.endswith("/languages"):
            return FakeResponse(200, {"Python": 1000}, headers={"X-RateLimit-Remaining": "5"})
        if url.endswith("/readme"):
            return FakeResponse(200, {"content": ""})
        raise AssertionError(f"unexpected URL {url}")

    with patch("github_fetch.requests.get", side_effect=fake_get):
        result = fetch_repos("octocat", "token123")

    assert result["rate_limited"] is True
    assert len(result["repos"]) == 1
    # repo list + repo-a's languages call only — readme skipped once rate
    # limited, and repo-b/repo-c never reached.
    assert len(calls) == 2
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/skill_verification
python -m pytest tests/test_github_fetch.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'github_fetch'`

- [ ] **Step 3: Write the minimal implementation**

`services/skill_verification/github_fetch.py`:
```python
"""Phase 0 — raw GitHub evidence fetching (module spec §5)."""

import base64

import requests

GITHUB_API = "https://api.github.com"

# Bounds total API-call count and request duration for prolific committers —
# a hard requirement given this whole call must finish inside one HTTP
# request/response cycle (no background-job infrastructure exists here).
MAX_REPOS = 30

# Stop fetching further repos once remaining calls drop below this, and
# return what was gathered so far rather than failing the whole request.
RATE_LIMIT_FLOOR = 10

README_MAX_CHARS = 4000


class InvalidTokenError(Exception):
    """Raised when GitHub reports the access token as invalid/revoked (401)."""


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "DevScore-SkillVerification",
    }


def _is_rate_limited(response) -> bool:
    remaining = response.headers.get("X-RateLimit-Remaining")
    return remaining is not None and int(remaining) < RATE_LIMIT_FLOOR


def _decode_readme(readme_response) -> str:
    if not readme_response.ok:
        return ""
    content = readme_response.json().get("content", "")
    try:
        return base64.b64decode(content).decode("utf-8", errors="ignore")[:README_MAX_CHARS]
    except (ValueError, TypeError):
        return ""


def fetch_repos(github_username: str, access_token: str) -> dict:
    """
    Fetches the student's public, non-fork repos (languages + README),
    newest-pushed first, capped at MAX_REPOS. Returns
    {"repos": [...], "rate_limited": bool}. Raises InvalidTokenError if
    GitHub reports the token as invalid (401).
    """
    list_resp = requests.get(
        f"{GITHUB_API}/user/repos",
        headers=_headers(access_token),
        params={
            "per_page": 100,
            "sort": "pushed",
            "direction": "desc",
            "affiliation": "owner",
        },
        timeout=15,
    )
    if list_resp.status_code == 401:
        raise InvalidTokenError()
    list_resp.raise_for_status()

    candidates = [
        repo for repo in list_resp.json()
        if not repo.get("private") and not repo.get("fork")
    ][:MAX_REPOS]

    repos = []
    rate_limited = False

    for repo in candidates:
        if rate_limited:
            break

        full_name = repo["full_name"]
        lang_resp = requests.get(
            f"{GITHUB_API}/repos/{full_name}/languages",
            headers=_headers(access_token),
            timeout=15,
        )
        if lang_resp.status_code == 401:
            raise InvalidTokenError()
        languages = lang_resp.json() if lang_resp.ok else {}
        if _is_rate_limited(lang_resp):
            rate_limited = True

        readme_text = ""
        if not rate_limited:
            readme_resp = requests.get(
                f"{GITHUB_API}/repos/{full_name}/readme",
                headers=_headers(access_token),
                timeout=15,
            )
            readme_text = _decode_readme(readme_resp)
            if _is_rate_limited(readme_resp):
                rate_limited = True

        repos.append({
            "name": repo["name"],
            "is_fork": repo.get("fork", False),
            "languages": languages,
            "readme_text": readme_text,
            "pushed_at": repo.get("pushed_at"),
        })

    return {"repos": repos, "rate_limited": rate_limited}
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/skill_verification
python -m pytest tests/test_github_fetch.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add services/skill_verification/github_fetch.py services/skill_verification/tests/test_github_fetch.py
git commit -m "Add Phase 0 GitHub evidence fetcher with rate-limit backoff"
```

---

### Task 4: Semantic matcher (Phase 2)

**Files:**
- Create: `services/skill_verification/semantic_matcher.py`
- Test: `services/skill_verification/tests/test_semantic_matcher.py`

**Interfaces:**
- Produces:
  - `semantic_matcher.THRESHOLD` (float, 0.65)
  - `semantic_matcher.build_evidence_chunks(repos: list[dict]) -> list[dict]` returning `[{"repo": str, "text": str}]`
  - `semantic_matcher.semantic_match(claimed_skill: str, repos: list[dict]) -> dict` returning `{"skill": str, "verified": bool, "method": "semantic_match", "confidence": float, "evidence_repo": str, "reason": None | "below_confidence_threshold"}`. **Caller must guard the empty-`repos` case before calling this** (Task 5 does). Used by Task 5's orchestration.

Note: this test downloads the `all-MiniLM-L6-v2` model (~90MB) from Hugging Face on first run and caches it locally — it needs network access the first time it executes, and will take noticeably longer than the other test files.

- [ ] **Step 1: Write the failing test**

`services/skill_verification/tests/test_semantic_matcher.py`:
```python
from semantic_matcher import THRESHOLD, semantic_match


def test_semantic_match_obvious_match_clears_threshold():
    repos = [{
        "name": "deep-learning-toolkit",
        "readme_text": (
            "A PyTorch and TensorFlow based deep learning library for "
            "training neural networks on image classification datasets."
        ),
    }]
    result = semantic_match("Machine Learning", repos)
    assert result["method"] == "semantic_match"
    assert result["confidence"] >= THRESHOLD
    assert result["verified"] is True
    assert result["reason"] is None
    assert result["evidence_repo"] == "deep-learning-toolkit"


def test_semantic_match_obvious_non_match_stays_below_threshold():
    repos = [{
        "name": "todo-list-app",
        "readme_text": "A simple to-do list app built with vanilla HTML, CSS and JS checkboxes.",
    }]
    result = semantic_match("Kubernetes", repos)
    assert result["confidence"] < THRESHOLD
    assert result["verified"] is False
    assert result["reason"] == "below_confidence_threshold"


def test_semantic_match_picks_best_scoring_repo():
    repos = [
        {"name": "unrelated", "readme_text": "A recipe-sharing app."},
        {
            "name": "ml-project",
            "readme_text": "Machine learning pipeline using scikit-learn and pandas.",
        },
    ]
    result = semantic_match("Machine Learning", repos)
    assert result["evidence_repo"] == "ml-project"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/skill_verification
python -m pytest tests/test_semantic_matcher.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'semantic_matcher'`

- [ ] **Step 3: Write the minimal implementation**

`services/skill_verification/semantic_matcher.py`:
```python
"""Phase 2 — semantic similarity matching (module spec §7)."""

from functools import lru_cache

from sentence_transformers import SentenceTransformer, util

MODEL_NAME = "all-MiniLM-L6-v2"

# Rough starting point, not tuned. Confidence is stored regardless of
# whether it clears this — do not tune this value against the project's
# expert-ranking dataset (reserved for the scoring module).
THRESHOLD = 0.65


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    # Loaded once per process (module-level singleton via lru_cache), not
    # once per request — loading it fresh each call would dominate latency.
    return SentenceTransformer(MODEL_NAME)


def build_evidence_chunks(repos: list) -> list:
    """One evidence chunk per repo: repo name + README text, truncated."""
    chunks = []
    for repo in repos:
        text = f"{repo['name']} {repo.get('readme_text') or ''}".strip()
        if text:
            chunks.append({"repo": repo["name"], "text": text})
    return chunks


def semantic_match(claimed_skill: str, repos: list) -> dict:
    """
    Embeds `claimed_skill` and every evidence chunk built from `repos`,
    returns the best-scoring chunk's result regardless of whether it clears
    THRESHOLD. Precondition: `repos` is non-empty (callers must handle the
    empty case as "no_public_repos" before reaching here).
    """
    chunks = build_evidence_chunks(repos)
    model = _model()

    skill_embedding = model.encode(claimed_skill, convert_to_tensor=True)
    chunk_embeddings = model.encode([c["text"] for c in chunks], convert_to_tensor=True)
    scores = util.cos_sim(skill_embedding, chunk_embeddings)[0]

    best_idx = int(scores.argmax())
    best_score = float(scores[best_idx])
    verified = best_score >= THRESHOLD

    return {
        "skill": claimed_skill,
        "verified": verified,
        "method": "semantic_match",
        "confidence": round(best_score, 4),
        "evidence_repo": chunks[best_idx]["repo"],
        "reason": None if verified else "below_confidence_threshold",
    }
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/skill_verification
python -m pytest tests/test_semantic_matcher.py -v
```
Expected: PASS (3 tests). First run downloads the model — allow extra time.

- [ ] **Step 5: Commit**

```bash
git add services/skill_verification/semantic_matcher.py services/skill_verification/tests/test_semantic_matcher.py
git commit -m "Add Phase 2 semantic skill matcher"
```

---

### Task 5: Orchestration (`main.py`)

**Files:**
- Create: `services/skill_verification/main.py`
- Test: `services/skill_verification/tests/test_main.py`

**Interfaces:**
- Consumes: `direct_matcher.direct_match` (Task 2), `semantic_matcher.semantic_match` (Task 4)
- Produces: `main.match_skills(claimed_skills: list[str], repos: list[dict]) -> list[dict]` — one result per claimed skill, same order as input, each `{"skill", "verified", "method", "confidence", "evidence_repo", "reason"}`. Used by Task 6's `/match-skills` route.

- [ ] **Step 1: Write the failing test**

`services/skill_verification/tests/test_main.py`:
```python
from main import match_skills


def test_match_skills_direct_match_short_circuits_semantic():
    repos = [{"name": "app", "languages": {"Python": 5000}, "readme_text": ""}]
    results = match_skills(["Python"], repos)
    assert results == [{
        "skill": "Python",
        "verified": True,
        "method": "direct_match",
        "confidence": 1.0,
        "evidence_repo": "app",
        "reason": None,
    }]


def test_match_skills_empty_repos_marks_no_public_repos():
    results = match_skills(["Kubernetes"], [])
    assert results == [{
        "skill": "Kubernetes",
        "verified": False,
        "method": "unverified",
        "confidence": None,
        "evidence_repo": None,
        "reason": "no_public_repos",
    }]


def test_match_skills_falls_back_to_semantic():
    repos = [{
        "name": "ml-project",
        "languages": {"Python": 5000},
        "readme_text": "A deep learning pipeline using TensorFlow for image classification.",
    }]
    results = match_skills(["Machine Learning"], repos)
    assert results[0]["method"] == "semantic_match"


def test_match_skills_preserves_input_order():
    repos = [{"name": "app", "languages": {"Python": 5000}, "readme_text": ""}]
    results = match_skills(["Kubernetes", "Python"], repos)
    assert [r["skill"] for r in results] == ["Kubernetes", "Python"]
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/skill_verification
python -m pytest tests/test_main.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write the minimal implementation**

`services/skill_verification/main.py`:
```python
"""Orchestrates Phase 1 (direct) then Phase 2 (semantic) matching per skill."""

from direct_matcher import direct_match
from semantic_matcher import semantic_match


def match_skills(claimed_skills: list, repos: list) -> list:
    """
    Runs direct matching first, then falls back to semantic matching for
    anything unresolved. Returns one result dict per claimed skill, in the
    same order as `claimed_skills`.
    """
    results = []
    for skill in claimed_skills:
        direct_result = direct_match(skill, repos)
        if direct_result is not None:
            results.append(direct_result)
            continue

        if not repos:
            results.append({
                "skill": skill,
                "verified": False,
                "method": "unverified",
                "confidence": None,
                "evidence_repo": None,
                "reason": "no_public_repos",
            })
            continue

        results.append(semantic_match(skill, repos))
    return results
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/skill_verification
python -m pytest tests/test_main.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add services/skill_verification/main.py services/skill_verification/tests/test_main.py
git commit -m "Add skill-matching orchestration combining direct and semantic phases"
```

---

### Task 6: Flask app (routes + shared-secret auth)

**Files:**
- Create: `services/skill_verification/app.py`
- Test: `services/skill_verification/tests/test_app.py`

**Interfaces:**
- Consumes: `github_fetch.fetch_repos`, `github_fetch.InvalidTokenError` (Task 3), `main.match_skills` (Task 5)
- Produces: HTTP routes `GET /health`, `POST /fetch-evidence`, `POST /match-skills` — consumed by Node's `server/src/utils/skillVerification.js` (Task 8).

- [ ] **Step 1: Write the failing test**

`services/skill_verification/tests/test_app.py`:
```python
import base64
from unittest.mock import patch

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_fetch_evidence_requires_fields(client):
    resp = client.post("/fetch-evidence", json={})
    assert resp.status_code == 400


def test_fetch_evidence_returns_repos(client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "fetch_repos",
        lambda username, token: {"repos": [{"name": "a"}], "rate_limited": False},
    )
    resp = client.post(
        "/fetch-evidence",
        json={"github_username": "octocat", "access_token": "tok"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["repos"] == [{"name": "a"}]


def test_fetch_evidence_invalid_token_returns_401(client, monkeypatch):
    def raise_invalid(username, token):
        raise app_module.InvalidTokenError()

    monkeypatch.setattr(app_module, "fetch_repos", raise_invalid)
    resp = client.post(
        "/fetch-evidence",
        json={"github_username": "octocat", "access_token": "bad"},
    )
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "invalid_token"}


def test_match_skills_route(client):
    repos = [{"name": "app", "languages": {"Python": 5000}, "readme_text": ""}]
    resp = client.post(
        "/match-skills",
        json={"claimed_skills": ["Python"], "repos": repos},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body[0]["method"] == "direct_match"


def test_unauthorized_without_api_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "secret123")
    resp = client.get("/fetch-evidence")
    resp = client.post("/fetch-evidence", json={})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/skill_verification
python -m pytest tests/test_app.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write the minimal implementation**

`services/skill_verification/app.py`:
```python
"""
HTTP wrapper around github_fetch.fetch_repos() and main.match_skills() —
the skill-verification microservice (Module 1). Stateless, like cv_parser:
it never touches Supabase. Node POSTs a GitHub token or evidence here and
gets JSON back; Node does all persistence.
"""

import os

from flask import Flask, jsonify, request

from github_fetch import InvalidTokenError, fetch_repos
from main import match_skills

app = Flask(__name__)

# Shared secret with the Node backend, same pattern as cv_parser's
# PARSER_API_KEY. No key configured (local dev) degrades to open access.
API_KEY = os.environ.get("SKILL_VERIFICATION_API_KEY", "")


def _authorized(req) -> bool:
    if not API_KEY:
        return True
    return req.headers.get("X-Api-Key") == API_KEY


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/fetch-evidence")
def fetch_evidence_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    username = body.get("github_username")
    token = body.get("access_token")
    if not username or not token:
        return jsonify({"error": "github_username and access_token are required"}), 400

    try:
        result = fetch_repos(username, token)
    except InvalidTokenError:
        return jsonify({"error": "invalid_token"}), 401
    return jsonify(result)


@app.post("/match-skills")
def match_skills_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    claimed_skills = body.get("claimed_skills") or []
    repos = body.get("repos") or []
    return jsonify(match_skills(claimed_skills, repos))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5002)))
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/skill_verification
python -m pytest tests/test_app.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full Python test suite**

```bash
cd services/skill_verification
python -m pytest -v
```
Expected: all tests across all files PASS.

- [ ] **Step 6: Commit**

```bash
git add services/skill_verification/app.py services/skill_verification/tests/test_app.py
git commit -m "Add skill-verification Flask app with shared-secret auth"
```

---

## Part B — Node integration

### Task 7: Database schema and environment configuration

**Files:**
- Modify: `server/supabase/schema.sql`
- Modify: `server/.env.example`
- Modify: `server/src/config/env.js`

**Interfaces:**
- Produces: Supabase tables `github_evidence`, `skill_verification`; `env.skillVerification.url` / `env.skillVerification.apiKey` — consumed by Task 8.

- [ ] **Step 1: Append the new tables to `server/supabase/schema.sql`**

Add after the existing `job_applications` block and before the final RLS-enabling section:

```sql
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
  evidence_repo_id uuid references public.github_evidence (id),
  reason           text check (reason in (
                     'github_not_connected', 'no_public_repos',
                     'below_confidence_threshold'
                   )),
  computed_at      timestamptz not null default now(),
  unique (user_id, skill_id)
);
create index if not exists skill_verification_user_id_idx on public.skill_verification (user_id);
```

And add these two lines alongside the existing `alter table ... enable row level security;` block at the bottom of the file:
```sql
alter table public.github_evidence enable row level security;
alter table public.skill_verification enable row level security;
```

- [ ] **Step 2: Apply the migration**

Run the new `create table` / `alter table` statements from Step 1 via the Supabase SQL editor (or `supabase db push` if the CLI is configured locally) against the project's database.

- [ ] **Step 3: Add environment variables to `server/.env.example`**

Append after the existing `CV_PARSER_API_KEY=` line:
```
# Skill-verification microservice (GitHub evidence + skill matching).
SKILL_VERIFICATION_URL=http://localhost:5002
SKILL_VERIFICATION_API_KEY=
```

- [ ] **Step 4: Add the config block to `server/src/config/env.js`**

Modify the `env` object — add after the existing `cvParser` block:
```js
  skillVerification: {
    url: process.env.SKILL_VERIFICATION_URL || 'http://localhost:5002',
    apiKey: process.env.SKILL_VERIFICATION_API_KEY || '',
  },
```

- [ ] **Step 5: Commit**

```bash
git add server/supabase/schema.sql server/.env.example server/src/config/env.js
git commit -m "Add github_evidence and skill_verification tables and service config"
```

---

### Task 8: Node HTTP client for the Python service

**Files:**
- Create: `server/src/utils/skillVerification.js`

**Interfaces:**
- Consumes: `env.skillVerification` (Task 7)
- Produces: `fetchGithubEvidence(username, accessToken) -> Promise<{repos, rate_limited}>` (throws `Error('invalid_github_token')` on a 401), `matchSkills(claimedSkills, repos) -> Promise<Array<{skill, verified, method, confidence, evidence_repo, reason}>>`. Consumed by Task 12's controller.

No automated test for this file — it is a thin HTTP-call wrapper with no branching logic beyond status-code checks, mirroring `server/src/utils/cvParser.js` (also untested in this codebase). It is exercised by Task 14's manual integration test.

- [ ] **Step 1: Write the implementation**

`server/src/utils/skillVerification.js`:
```js
import { env } from '../config/env.js';

// The fetch-evidence route can make up to ~60 GitHub API calls (30 repos x
// languages + readme); match cv_parser's timeout pattern but sized for that.
const REQUEST_TIMEOUT_MS = 60_000;

function headers() {
  return {
    'Content-Type': 'application/json',
    ...(env.skillVerification.apiKey ? { 'X-Api-Key': env.skillVerification.apiKey } : {}),
  };
}

/** Calls the skill-verification service's /fetch-evidence route. */
export async function fetchGithubEvidence(username, accessToken) {
  const res = await fetch(`${env.skillVerification.url}/fetch-evidence`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ github_username: username, access_token: accessToken }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (res.status === 401) {
    throw new Error('invalid_github_token');
  }
  if (!res.ok) {
    throw new Error(`skill_verification fetch-evidence responded ${res.status}`);
  }
  return res.json();
}

/** Calls the skill-verification service's /match-skills route. */
export async function matchSkills(claimedSkills, repos) {
  const res = await fetch(`${env.skillVerification.url}/match-skills`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ claimed_skills: claimedSkills, repos }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!res.ok) {
    throw new Error(`skill_verification match-skills responded ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 2: Commit**

```bash
git add server/src/utils/skillVerification.js
git commit -m "Add Node HTTP client for the skill-verification service"
```

---

### Task 9: Pure helper functions (cache freshness + not-connected results)

**Files:**
- Create: `server/src/utils/skillVerificationHelpers.js`
- Test: `server/src/utils/skillVerificationHelpers.test.js`

**Interfaces:**
- Produces: `isCacheFresh(fetchedAt, now = Date.now()) -> boolean`, `buildNotConnectedResults(skillRows: Array<{skillId, name}>) -> Array<{skillId, verified: false, method: 'unverified', confidence: null, evidenceRepoId: null, reason: 'github_not_connected'}>`. Consumed by Task 12's controller.

- [ ] **Step 1: Write the failing test**

`server/src/utils/skillVerificationHelpers.test.js`:
```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isCacheFresh, buildNotConnectedResults } from './skillVerificationHelpers.js';

const DAY_MS = 24 * 60 * 60 * 1000;

test('isCacheFresh: null fetchedAt is never fresh', () => {
  assert.equal(isCacheFresh(null), false);
});

test('isCacheFresh: under 24h old is fresh', () => {
  const now = Date.now();
  const fetchedAt = new Date(now - DAY_MS + 1000).toISOString();
  assert.equal(isCacheFresh(fetchedAt, now), true);
});

test('isCacheFresh: over 24h old is stale', () => {
  const now = Date.now();
  const fetchedAt = new Date(now - DAY_MS - 1000).toISOString();
  assert.equal(isCacheFresh(fetchedAt, now), false);
});

test('buildNotConnectedResults: maps every skill row to a github_not_connected result', () => {
  const rows = [
    { skillId: 'skill-1', name: 'Python' },
    { skillId: 'skill-2', name: 'Kubernetes' },
  ];
  const results = buildNotConnectedResults(rows);
  assert.equal(results.length, 2);
  for (const r of results) {
    assert.equal(r.verified, false);
    assert.equal(r.method, 'unverified');
    assert.equal(r.confidence, null);
    assert.equal(r.evidenceRepoId, null);
    assert.equal(r.reason, 'github_not_connected');
  }
  assert.equal(results[0].skillId, 'skill-1');
  assert.equal(results[1].skillId, 'skill-2');
});

test('buildNotConnectedResults: empty input gives empty output', () => {
  assert.deepEqual(buildNotConnectedResults([]), []);
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd server
node --test src/utils/skillVerificationHelpers.test.js
```
Expected: FAIL — cannot find module `./skillVerificationHelpers.js`

- [ ] **Step 3: Write the minimal implementation**

`server/src/utils/skillVerificationHelpers.js`:
```js
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;

/** True if `fetchedAt` is within the 24h cache window. */
export function isCacheFresh(fetchedAt, now = Date.now()) {
  if (!fetchedAt) return false;
  return now - new Date(fetchedAt).getTime() < CACHE_TTL_MS;
}

/**
 * Builds a github_not_connected verification result for every claimed
 * skill — used when a student has no active GitHub connection at all
 * (the "unverifiable, not unverified" case).
 */
export function buildNotConnectedResults(skillRows) {
  return skillRows.map((row) => ({
    skillId: row.skillId,
    verified: false,
    method: 'unverified',
    confidence: null,
    evidenceRepoId: null,
    reason: 'github_not_connected',
  }));
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd server
node --test src/utils/skillVerificationHelpers.test.js
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add server/src/utils/skillVerificationHelpers.js server/src/utils/skillVerificationHelpers.test.js
git commit -m "Add pure cache-freshness and not-connected-result helpers"
```

---

### Task 10: Recruiter-owns-candidate ownership helper

**Files:**
- Create: `server/src/utils/candidateOwnership.js`
- Test: `server/src/utils/candidateOwnership.test.js`

**Interfaces:**
- Consumes: `ROLES` (`server/src/models/User.js`), `findById` (`User.js`), `listJobsByRecruiter` (`server/src/models/Job.js`), `listApplicationsForStudentInJobs` (`server/src/models/JobApplication.js`)
- Produces: `isOwnedCandidate(user, applications) -> boolean` (pure, tested directly), `findOwnedCandidate(recruiterId, studentId) -> Promise<user | null>` (I/O, used by Task 12's controller; exercised via the manual integration test in Task 14, not unit-tested directly — it is a thin wrapper around already-tested model functions and the pure predicate below).

- [ ] **Step 1: Write the failing test**

`server/src/utils/candidateOwnership.test.js`:
```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isOwnedCandidate } from './candidateOwnership.js';

test('isOwnedCandidate: false when user does not exist', () => {
  assert.equal(isOwnedCandidate(null, [{ id: 'app-1' }]), false);
});

test('isOwnedCandidate: false when user is not a student', () => {
  const recruiter = { id: 'u1', role: 'recruiter' };
  assert.equal(isOwnedCandidate(recruiter, [{ id: 'app-1' }]), false);
});

test('isOwnedCandidate: false when there are no applications', () => {
  const student = { id: 'u1', role: 'student' };
  assert.equal(isOwnedCandidate(student, []), false);
});

test('isOwnedCandidate: true for a student with at least one application', () => {
  const student = { id: 'u1', role: 'student' };
  assert.equal(isOwnedCandidate(student, [{ id: 'app-1' }]), true);
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd server
node --test src/utils/candidateOwnership.test.js
```
Expected: FAIL — cannot find module `./candidateOwnership.js`

- [ ] **Step 3: Write the minimal implementation**

`server/src/utils/candidateOwnership.js`:
```js
import { ROLES, findById } from '../models/User.js';
import { listJobsByRecruiter } from '../models/Job.js';
import { listApplicationsForStudentInJobs } from '../models/JobApplication.js';

/**
 * True if `user` is a student who has at least one application among the
 * given `applications` — the ownership rule behind a recruiter viewing a
 * candidate's evidence (they must have applied to one of the recruiter's
 * postings).
 */
export function isOwnedCandidate(user, applications) {
  return Boolean(user) && user.role === ROLES.STUDENT && applications.length > 0;
}

/**
 * Resolves the student `studentId` if `recruiterId` may view their
 * evidence, else null. Callers should respond 404 (not 403) on null, so a
 * recruiter cannot probe which student ids exist.
 */
export async function findOwnedCandidate(recruiterId, studentId) {
  const user = await findById(studentId);
  const jobs = await listJobsByRecruiter(recruiterId);
  const jobIds = jobs.map((j) => j.id);
  const applications = jobIds.length
    ? await listApplicationsForStudentInJobs(studentId, jobIds)
    : [];
  return isOwnedCandidate(user, applications) ? user : null;
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd server
node --test src/utils/candidateOwnership.test.js
```
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add server/src/utils/candidateOwnership.js server/src/utils/candidateOwnership.test.js
git commit -m "Add recruiter-owns-candidate ownership helper"
```

---

### Task 11: Data-access models

**Files:**
- Create: `server/src/models/GithubEvidence.js`
- Create: `server/src/models/SkillVerification.js`
- Modify: `server/src/models/Resume.js`

**Interfaces:**
- Produces:
  - `GithubEvidence.findByUserId(userId) -> Promise<row[]>`
  - `GithubEvidence.latestFetchedAt(userId) -> Promise<string | null>`
  - `GithubEvidence.replaceForUser(userId, repos) -> Promise<row[]>` (`repos` = the Python service's `/fetch-evidence` `repos` array)
  - `SkillVerification.findByUserId(userId) -> Promise<Array<{skill, verified, method, confidence, reason, computedAt}>>`
  - `SkillVerification.replaceForUser(userId, results) -> Promise<row[]>` (`results` items: `{skillId, verified, method, confidence, evidenceRepoId, reason}`)
  - `Resume.getSkillRows(resumeId) -> Promise<Array<{skillId, name, category}>>`
- All consumed by Task 12's controller. No automated tests — these are Supabase CRUD wrappers with no branching logic, following the exact style of the existing untested `Resume.js`/`Skill.js` models; exercised by Task 14's manual integration test.

- [ ] **Step 1: Add `getSkillRows` to `server/src/models/Resume.js`**

Add this export after the existing `getSkills` function:
```js
/**
 * Fetch a resume's extracted skills as raw rows (keeping skill_id) — for
 * callers that need the id, not just the grouped display shape (e.g. skill
 * verification, which writes one row per skill_id).
 */
export async function getSkillRows(resumeId) {
  const { data, error } = await supabase
    .from('resume_skills')
    .select('skill_id, skills(name, category)')
    .eq('resume_id', resumeId);
  if (error) throw new Error(error.message);
  return data.map((row) => ({
    skillId: row.skill_id,
    name: row.skills.name,
    category: row.skills.category,
  }));
}
```

- [ ] **Step 2: Create `server/src/models/GithubEvidence.js`**

```js
import { supabase } from '../config/db.js';

/**
 * Raw per-repo GitHub evidence for a student (Phase 0 output). Replaced
 * wholesale on each re-fetch — see replaceForUser.
 */

/** Fetch stored evidence rows for a user, newest fetch first. */
export async function findByUserId(userId) {
  const { data, error } = await supabase
    .from('github_evidence')
    .select('*')
    .eq('user_id', userId)
    .order('fetched_at', { ascending: false });
  if (error) throw new Error(error.message);
  return data;
}

/** The most recent fetched_at for a user, or null if never fetched. */
export async function latestFetchedAt(userId) {
  const { data, error } = await supabase
    .from('github_evidence')
    .select('fetched_at')
    .eq('user_id', userId)
    .order('fetched_at', { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data?.fetched_at || null;
}

/**
 * Replace all evidence rows for a user with a fresh fetch result. `repos`
 * is the skill-verification service's /fetch-evidence "repos" array shape:
 * [{ name, is_fork, languages, readme_text, pushed_at }].
 */
export async function replaceForUser(userId, repos) {
  const { error: deleteError } = await supabase
    .from('github_evidence')
    .delete()
    .eq('user_id', userId);
  if (deleteError) throw new Error(deleteError.message);

  if (repos.length === 0) return [];

  const rows = repos.map((repo) => ({
    user_id: userId,
    repo_name: repo.name,
    is_fork: repo.is_fork,
    languages: repo.languages,
    readme_text: repo.readme_text,
    last_pushed_at: repo.pushed_at,
  }));
  const { data, error } = await supabase.from('github_evidence').insert(rows).select();
  if (error) throw new Error(error.message);
  return data;
}
```

- [ ] **Step 3: Create `server/src/models/SkillVerification.js`**

```js
import { supabase } from '../config/db.js';

/** Reshape a skill_verification+skills join row into the API's flat shape. */
function toPublic(row) {
  return {
    skill: row.skills.name,
    verified: row.verified,
    method: row.method,
    confidence: row.confidence,
    reason: row.reason,
    computedAt: row.computed_at,
  };
}

/** Fetch stored verification results for a user, joined to skill names. */
export async function findByUserId(userId) {
  const { data, error } = await supabase
    .from('skill_verification')
    .select('verified, method, confidence, reason, computed_at, skills(name, category)')
    .eq('user_id', userId);
  if (error) throw new Error(error.message);
  return data.map(toPublic);
}

/**
 * Replace all verification rows for a user with a fresh result set.
 * `results` items: { skillId, verified, method, confidence, evidenceRepoId, reason }.
 */
export async function replaceForUser(userId, results) {
  const { error: deleteError } = await supabase
    .from('skill_verification')
    .delete()
    .eq('user_id', userId);
  if (deleteError) throw new Error(deleteError.message);

  if (results.length === 0) return [];

  const rows = results.map((r) => ({
    user_id: userId,
    skill_id: r.skillId,
    verified: r.verified,
    method: r.method,
    confidence: r.confidence,
    evidence_repo_id: r.evidenceRepoId || null,
    reason: r.reason || null,
  }));
  const { data, error } = await supabase.from('skill_verification').insert(rows).select();
  if (error) throw new Error(error.message);
  return data;
}
```

- [ ] **Step 4: Commit**

```bash
git add server/src/models/GithubEvidence.js server/src/models/SkillVerification.js server/src/models/Resume.js
git commit -m "Add GithubEvidence and SkillVerification models"
```

---

### Task 12: Controller and routes

**Files:**
- Create: `server/src/controllers/skillVerificationController.js`
- Create: `server/src/routes/skillVerificationRoutes.js`
- Modify: `server/src/app.js`

**Interfaces:**
- Consumes: `ROLES` (`User.js`), `findOwnedCandidate` (Task 10), `findActiveByUserAndProvider` (`OAuthSession.js`), `decryptToken` (`secureToken.js`), `GithubConnection.findByUserId`, `Resume.findByUserId` / `getSkillRows` (Task 11), `GithubEvidence.*` / `SkillVerification.*` (Task 11), `fetchGithubEvidence` / `matchSkills` (Task 8), `isCacheFresh` / `buildNotConnectedResults` (Task 9)
- Produces: `POST /api/skill-verification/run`, `GET /api/skill-verification/:studentId` — the module's public API surface, per spec §5. No automated test — this orchestrates five different I/O-bound modules with no new pure logic of its own (all the branching logic it uses was already unit-tested in Tasks 9-10); it is exercised end-to-end by Task 14's manual integration test.

- [ ] **Step 1: Create `server/src/controllers/skillVerificationController.js`**

```js
import { ROLES } from '../models/User.js';
import { findActiveByUserAndProvider } from '../models/OAuthSession.js';
import { decryptToken } from '../utils/secureToken.js';
import * as GithubConnection from '../models/GithubConnection.js';
import * as Resume from '../models/Resume.js';
import * as GithubEvidence from '../models/GithubEvidence.js';
import * as SkillVerification from '../models/SkillVerification.js';
import { fetchGithubEvidence, matchSkills } from '../utils/skillVerification.js';
import { isCacheFresh, buildNotConnectedResults } from '../utils/skillVerificationHelpers.js';
import { findOwnedCandidate } from '../utils/candidateOwnership.js';

/** Resolves which student a request targets; recruiters must own the candidate. */
async function resolveStudentId(req, studentIdInput) {
  if (req.user.role === ROLES.STUDENT) return req.user.id;
  if (req.user.role === ROLES.RECRUITER) {
    if (!studentIdInput) return null;
    const candidate = await findOwnedCandidate(req.user.id, studentIdInput);
    return candidate ? candidate.id : null;
  }
  return null;
}

/** A 502 for the Node error handler to surface when the Python service is unreachable or errors. */
function serviceUnavailableError() {
  const err = new Error('skill_verification_service_unavailable');
  err.status = 502;
  err.expose = true;
  return err;
}

/** Writes every claimed skill as github_not_connected and responds. */
async function respondNotConnected(res, studentId) {
  const resume = await Resume.findByUserId(studentId);
  const skillRows = resume ? await Resume.getSkillRows(resume.id) : [];
  const persisted = buildNotConnectedResults(skillRows);
  await SkillVerification.replaceForUser(studentId, persisted);

  return res.json({
    status: 'completed',
    skills_verified: 0,
    skills_unverified: persisted.length,
    results: skillRows.map((s) => ({
      claimed_skill: s.name,
      verified: false,
      method: 'unverified',
      confidence: null,
      reason: 'github_not_connected',
    })),
  });
}

/** Runs the fetch (if needed) + match pipeline for one student and persists results. */
export async function runVerification(req, res, next) {
  try {
    const studentId = await resolveStudentId(req, req.body?.studentId);
    if (!studentId) {
      return res.status(404).json({ error: 'Candidate not found' });
    }

    const [connection, session] = await Promise.all([
      GithubConnection.findByUserId(studentId),
      findActiveByUserAndProvider(studentId, 'github'),
    ]);
    if (!connection || !session) {
      return respondNotConnected(res, studentId);
    }

    const force = req.query?.force === '1';
    const latestFetch = await GithubEvidence.latestFetchedAt(studentId);

    let evidenceRows;
    if (!force && isCacheFresh(latestFetch)) {
      evidenceRows = await GithubEvidence.findByUserId(studentId);
    } else {
      const accessToken = decryptToken(session.encrypted_access_token);
      let fetchResult;
      try {
        fetchResult = await fetchGithubEvidence(connection.username, accessToken);
      } catch (err) {
        if (err.message === 'invalid_github_token') {
          return respondNotConnected(res, studentId);
        }
        return next(serviceUnavailableError());
      }
      evidenceRows = await GithubEvidence.replaceForUser(studentId, fetchResult.repos);
    }

    const resume = await Resume.findByUserId(studentId);
    const skillRows = resume ? await Resume.getSkillRows(resume.id) : [];
    if (skillRows.length === 0) {
      await SkillVerification.replaceForUser(studentId, []);
      return res.json({ status: 'completed', skills_verified: 0, skills_unverified: 0, results: [] });
    }

    const evidenceForMatching = evidenceRows.map((row) => ({
      name: row.repo_name,
      is_fork: row.is_fork,
      languages: row.languages,
      readme_text: row.readme_text,
      pushed_at: row.last_pushed_at,
    }));

    let matchResults;
    try {
      matchResults = await matchSkills(skillRows.map((s) => s.name), evidenceForMatching);
    } catch {
      return next(serviceUnavailableError());
    }

    const evidenceRepoIdByName = Object.fromEntries(evidenceRows.map((r) => [r.repo_name, r.id]));
    const skillIdByName = Object.fromEntries(skillRows.map((s) => [s.name, s.skillId]));
    const persisted = matchResults.map((r) => ({
      skillId: skillIdByName[r.skill],
      verified: r.verified,
      method: r.method,
      confidence: r.confidence,
      evidenceRepoId: r.evidence_repo ? evidenceRepoIdByName[r.evidence_repo] : null,
      reason: r.reason,
    }));
    await SkillVerification.replaceForUser(studentId, persisted);

    res.json({
      status: 'completed',
      skills_verified: matchResults.filter((r) => r.verified).length,
      skills_unverified: matchResults.filter((r) => !r.verified).length,
      results: matchResults,
    });
  } catch (err) {
    next(err);
  }
}

/** Reads stored verification results — no recompute. */
export async function getVerification(req, res, next) {
  try {
    let studentId;
    if (req.user.role === ROLES.STUDENT) {
      if (req.params.studentId !== req.user.id) {
        return res.status(404).json({ error: 'Candidate not found' });
      }
      studentId = req.user.id;
    } else if (req.user.role === ROLES.RECRUITER) {
      const candidate = await findOwnedCandidate(req.user.id, req.params.studentId);
      if (!candidate) return res.status(404).json({ error: 'Candidate not found' });
      studentId = candidate.id;
    } else {
      return res.status(403).json({ error: 'You do not have access to this resource' });
    }

    const results = await SkillVerification.findByUserId(studentId);
    res.json({ results });
  } catch (err) {
    next(err);
  }
}
```

- [ ] **Step 2: Create `server/src/routes/skillVerificationRoutes.js`**

```js
import { Router } from 'express';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { runVerification, getVerification } from '../controllers/skillVerificationController.js';

const router = Router();

router.post('/run', requireAuth, requireRole('student', 'recruiter'), runVerification);
router.get('/:studentId', requireAuth, requireRole('student', 'recruiter'), getVerification);

export default router;
```

- [ ] **Step 3: Mount the router in `server/src/app.js`**

Add the import alongside the other route imports:
```js
import skillVerificationRoutes from './routes/skillVerificationRoutes.js';
```
And mount it alongside the other `app.use('/api/...')` lines:
```js
  app.use('/api/skill-verification', skillVerificationRoutes);
```

- [ ] **Step 4: Commit**

```bash
git add server/src/controllers/skillVerificationController.js server/src/routes/skillVerificationRoutes.js server/src/app.js
git commit -m "Wire up skill-verification API endpoints"
```

---

### Task 13: Node test script and full-suite run

**Files:**
- Modify: `server/package.json`

**Interfaces:** None — this wires up test discovery for Tasks 9-10's tests.

- [ ] **Step 1: Add a `test` script**

Add to the `"scripts"` block in `server/package.json`:
```json
    "test": "node --test src"
```

- [ ] **Step 2: Run the full Node test suite**

```bash
cd server
npm test
```
Expected: PASS — all tests from Tasks 9 and 10 (9 tests total).

- [ ] **Step 3: Run the full Python test suite once more**

```bash
cd services/skill_verification
python -m pytest -v
```
Expected: PASS — all tests from Tasks 1-6.

- [ ] **Step 4: Commit**

```bash
git add server/package.json
git commit -m "Add node:test script to server package.json"
```

---

### Task 14: Manual end-to-end integration test

**Files:** None created — this is a manual verification pass, not automated (per spec §8: exact thresholds are not asserted in code; this is a sanity check against real data).

- [ ] **Step 1: Start both services locally**

```bash
cd services/skill_verification
python -m pip install -r requirements-dev.txt
python app.py
```
In a second terminal:
```bash
cd server
npm run dev
```

- [ ] **Step 2: Prepare test data**

Using the running app (or direct Supabase writes), ensure at least one test student has:
- A resume with claimed skills extracted via `cv_parser` (upload a real resume through the existing flow, or insert `skills`/`resume_skills` rows directly for a quick test).
- A connected GitHub account pointing at a real public GitHub profile with actual repos (your own account, or a teammate's, per the spec's guidance on using real accounts for this test).

- [ ] **Step 3: Trigger verification**

```bash
curl -X POST http://localhost:5000/api/skill-verification/run \
  -H "Content-Type: application/json" \
  -H "Cookie: devscore_session=<a real session cookie from logging in as that student>"
```

- [ ] **Step 4: Sanity-check the results**

Confirm, by eye, against the test student's actual GitHub profile:
- Skills matching a language the student's repos are written in show `method: "direct_match"`.
- Concept skills (e.g. "Machine Learning", "REST API") that plausibly appear in a README show `method: "semantic_match"` with a reasonable confidence score, not necessarily crossing 0.65 — the point is that the *relative* ordering makes sense (an ML-related README scores higher for "Machine Learning" than an unrelated repo would), not that the absolute threshold is correct.
- A skill with no plausible evidence anywhere shows `verified: false`.

- [ ] **Step 5: Confirm the GET endpoint reads back the same data**

```bash
curl http://localhost:5000/api/skill-verification/<student-id> \
  -H "Cookie: devscore_session=<same session cookie>"
```
Confirm the `results` array matches what Step 3 just wrote, without triggering a new GitHub fetch (check `services/skill_verification` logs / add a temporary print to confirm `/fetch-evidence` was not called again).

- [ ] **Step 6: Note findings**

No commit for this task. If this surfaces a real bug, fix it as a follow-up task with its own test (per this plan's TDD approach) rather than patching silently.
