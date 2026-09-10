# AST-Based Code Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given a student's public GitHub repos, fetch their actual source code, compute structural complexity metrics via `lizard`, and store per-repo + per-student aggregate signals as a second, independent input to the WVR formula's `Vi` term (alongside Module 1's skill-verification signal).

**Architecture:** A new stateless Python/Flask microservice (`services/code_analysis/`) downloads each repo's source as a tarball (no `git` binary dependency), filters and analyzes it with `lizard`, and aggregates results — called over HTTP from a new Node controller (`server/src`) that owns persistence, caching, and authorization, mirroring both `cv_parser` and Module 1's `skill_verification` integration pattern.

**Tech Stack:** Python 3 / Flask / `requests` / `lizard` (new service); Node/Express / `@supabase/supabase-js` (existing server, extended); `pytest` (Python tests); Node's built-in `node:test` (Node tests, no new dependency).

**Spec:** `docs/superpowers/specs/2026-09-03-ast-code-analysis-design.md`

## Global Constraints

- The Python service is stateless — it never touches Supabase, exactly like `cv_parser` and `skill_verification`.
- Only public, non-fork repos may be fetched — never request or use private-repo data.
- Cap at the 15 most-recently-pushed non-fork public repos per analysis run.
- Skip any repo whose tarball `Content-Length` (or actual streamed size, if the header is absent or understated) exceeds 25MB — exclude with `reason: "too_large"`, never fail the whole run.
- Within a repo: skip files over 500KB; cap total files analyzed at 300.
- **Nesting depth requires the `nd` extension to be explicitly loaded**: `lizard.FileAnalyzer(lizard.get_extensions(['nd']))`. The naive `lizard.analyze_file(...)` shortcut has zero extensions loaded and silently returns `max_nesting_depth: 0` for every function regardless of actual nesting — verified directly during design. Never use the naive form in this module.
- Tarball extraction uses Python's stdlib `tarfile` module with `extractall(..., filter="data")` — no shelling out to `git` or any other binary. Verified end-to-end against a real GitHub tarball during design.
- New tables (`code_analysis`, `code_analysis_summary`) get RLS enabled with **zero policies** — service-role key only, matching every existing table.
- Node ↔ Python auth uses a shared-secret `X-Api-Key` header; an unset key means open access (matches the other two services' local-dev degradation).
- Reuse cached `code_analysis` results if the newest `analyzed_at` is under 24h old, unless the caller forces a re-run.
- `force=1` is gated to the student themselves only — a recruiter viewing a candidate may never force a re-run (this was a fix-round lesson from Module 1; apply it from the start here rather than discovering it in review).
- A Python-service failure must produce a 502 `{"error": "code_analysis_service_unavailable"}`, never a generic 500 (also a Module 1 fix-round lesson, applied from the start).
- The Python service's `/analyze-repos` route must catch unexpected exceptions and return structured JSON with a 500 status, never Flask's default HTML error page (same lesson, Python side).
- Aggregation (per-repo → per-student summary) is computed once, in Python (`aggregation.py`), and returned alongside the per-repo results. Node persists it as-is and never recomputes it — including on a cache-hit read, which simply reads the already-stored summary row.
- No new Node test-runner dependency — use the built-in `node:test` module. The existing `server/package.json` test script (`node --test src/**/*.test.js`) already covers any new `*.test.js` file under `src/` — no change needed there.
- Source code is never persisted after analysis — every temp directory created during a repo's analysis is deleted (`shutil.rmtree`) before moving to the next repo, in a `finally` block.

---

## Part A — Python code-analysis service

### Task 1: Scaffold the service + exclusion rules

**Files:**
- Create: `services/code_analysis/exclusion_rules.py`
- Create: `services/code_analysis/requirements.txt`
- Create: `services/code_analysis/requirements-dev.txt`
- Create: `services/code_analysis/tests/__init__.py` (empty)
- Create: `services/code_analysis/tests/conftest.py`
- Test: `services/code_analysis/tests/test_exclusion_rules.py`

**Interfaces:**
- Produces: `exclusion_rules.is_fork(repo_metadata: dict) -> bool`, `exclusion_rules.is_too_large(content_length_bytes: int | None) -> bool`, `exclusion_rules.is_empty(total_lines: int) -> bool`, `exclusion_rules.matches_tutorial_heuristic(repo_name: str) -> bool`, plus constants `MAX_TARBALL_BYTES = 25 * 1024 * 1024` and `MIN_TOTAL_LINES = 20`. Used by Task 5's orchestration.

- [ ] **Step 1: Create the service directory and dependency files**

`services/code_analysis/requirements.txt`:
```
flask==3.1.3
gunicorn==26.0.0
requests==2.32.3
lizard==1.17.31
```

`services/code_analysis/requirements-dev.txt`:
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

Also create an empty `services/code_analysis/tests/__init__.py`.

- [ ] **Step 3: Write the failing test**

`services/code_analysis/tests/test_exclusion_rules.py`:
```python
from exclusion_rules import (
    MAX_TARBALL_BYTES,
    MIN_TOTAL_LINES,
    is_empty,
    is_fork,
    is_too_large,
    matches_tutorial_heuristic,
)


def test_is_fork_true_when_flag_set():
    assert is_fork({"fork": True}) is True


def test_is_fork_false_when_flag_missing():
    assert is_fork({}) is False


def test_is_too_large_true_over_limit():
    assert is_too_large(MAX_TARBALL_BYTES + 1) is True


def test_is_too_large_false_under_limit():
    assert is_too_large(1000) is False


def test_is_too_large_false_when_unknown():
    assert is_too_large(None) is False


def test_is_empty_true_under_minimum():
    assert is_empty(MIN_TOTAL_LINES - 1) is True


def test_is_empty_false_at_minimum():
    assert is_empty(MIN_TOTAL_LINES) is False


def test_matches_tutorial_heuristic_case_insensitive():
    assert matches_tutorial_heuristic("My-Tutorial-App") is True


def test_matches_tutorial_heuristic_various_patterns():
    assert matches_tutorial_heuristic("react-bootcamp-2024") is True
    assert matches_tutorial_heuristic("hello-world") is True
    assert matches_tutorial_heuristic("js-starter") is True


def test_matches_tutorial_heuristic_no_match():
    assert matches_tutorial_heuristic("fraud-detection-model") is False
```

- [ ] **Step 4: Install dependencies and run the test to verify it fails**

```bash
cd services/code_analysis
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_exclusion_rules.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'exclusion_rules'`

- [ ] **Step 5: Write the minimal implementation**

`services/code_analysis/exclusion_rules.py`:
```python
"""Phase 3 — exclusion rules (module spec section 6). Each rule is a
pure predicate; the caller (main.py) is responsible for recording the
matching reason rather than silently dropping a repo."""

MAX_TARBALL_BYTES = 25 * 1024 * 1024  # 25MB
MIN_TOTAL_LINES = 20

# Soft, unreliable heuristic — documented as such, not presented as a
# solved problem (module spec's own framing). Substring match, case
# insensitive, against the repo name only.
TUTORIAL_NAME_PATTERNS = (
    "tutorial", "clone", "practice", "bootcamp", "learning",
    "-starter", "hello-world",
)


def is_fork(repo_metadata: dict) -> bool:
    return bool(repo_metadata.get("fork"))


def is_too_large(content_length_bytes) -> bool:
    return content_length_bytes is not None and content_length_bytes > MAX_TARBALL_BYTES


def is_empty(total_lines: int) -> bool:
    return total_lines < MIN_TOTAL_LINES


def matches_tutorial_heuristic(repo_name: str) -> bool:
    name = repo_name.lower()
    return any(pattern in name for pattern in TUTORIAL_NAME_PATTERNS)
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd services/code_analysis
python -m pytest tests/test_exclusion_rules.py -v
```
Expected: PASS (10 tests)

- [ ] **Step 7: Commit**

```bash
git add services/code_analysis/exclusion_rules.py services/code_analysis/requirements.txt services/code_analysis/requirements-dev.txt services/code_analysis/tests/
git commit -m "Add code-analysis service scaffold and exclusion rules"
```

---

### Task 2: Repo fetch — tarball download, extraction, filtering

**Files:**
- Create: `services/code_analysis/repo_fetch.py`
- Test: `services/code_analysis/tests/test_repo_fetch.py`

**Interfaces:**
- Produces:
  - `repo_fetch.InvalidTokenError`, `repo_fetch.TarballTooLargeError` (exception classes)
  - `repo_fetch.fetch_repo_metadata(full_name: str, access_token: str) -> dict` — raises `InvalidTokenError` on 401.
  - `repo_fetch.download_tarball(full_name: str, access_token: str) -> bytes` — raises `InvalidTokenError` on 401, `TarballTooLargeError` if `Content-Length` exceeds `MAX_TARBALL_BYTES` or if streamed bytes exceed it even without a trustworthy header.
  - `repo_fetch.extract_and_filter(tarball_bytes: bytes) -> tuple[str, list[str]]` — extracts into a fresh temp directory, returns `(tmp_dir_path, filtered_file_paths)`. Caller must call `cleanup(tmp_dir_path)` when done.
  - `repo_fetch.cleanup(tmp_dir: str) -> None`
  - Module constants: `MAX_TARBALL_BYTES` (25MB, same value as `exclusion_rules.MAX_TARBALL_BYTES`), `MAX_FILE_BYTES = 500 * 1024`, `MAX_FILES_PER_REPO = 300`, `SKIP_DIRS`.
  - Used by Task 5's orchestration.

- [ ] **Step 1: Write the failing test**

`services/code_analysis/tests/test_repo_fetch.py`:
```python
import io
import os
import tarfile
from unittest.mock import patch

import pytest

import repo_fetch
from repo_fetch import (
    InvalidTokenError,
    TarballTooLargeError,
    cleanup,
    download_tarball,
    extract_and_filter,
    fetch_repo_metadata,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, content_chunks=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300
        self._chunks = content_chunks or []

    def json(self):
        return self._json

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        for chunk in self._chunks:
            yield chunk

    def close(self):
        pass


def test_fetch_repo_metadata_success():
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(200, {"fork": False, "full_name": "octocat/hello"})

    with patch("repo_fetch.requests.get", side_effect=fake_get):
        result = fetch_repo_metadata("octocat/hello", "token")
    assert result["fork"] is False


def test_fetch_repo_metadata_raises_on_invalid_token():
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(401)

    with patch("repo_fetch.requests.get", side_effect=fake_get):
        with pytest.raises(InvalidTokenError):
            fetch_repo_metadata("octocat/hello", "bad-token")


def test_download_tarball_success():
    def fake_get(url, headers=None, timeout=None, stream=None):
        return FakeResponse(200, headers={"Content-Length": "10"}, content_chunks=[b"hello", b"world"])

    with patch("repo_fetch.requests.get", side_effect=fake_get):
        data = download_tarball("octocat/hello", "token")
    assert data == b"helloworld"


def test_download_tarball_raises_on_invalid_token():
    def fake_get(url, headers=None, timeout=None, stream=None):
        return FakeResponse(401)

    with patch("repo_fetch.requests.get", side_effect=fake_get):
        with pytest.raises(InvalidTokenError):
            download_tarball("octocat/hello", "bad-token")


def test_download_tarball_raises_when_content_length_too_large():
    def fake_get(url, headers=None, timeout=None, stream=None):
        return FakeResponse(200, headers={"Content-Length": str(repo_fetch.MAX_TARBALL_BYTES + 1)})

    with patch("repo_fetch.requests.get", side_effect=fake_get):
        with pytest.raises(TarballTooLargeError):
            download_tarball("octocat/hello", "token")


def test_download_tarball_raises_when_streamed_bytes_exceed_cap_without_header():
    big_chunk = b"x" * (repo_fetch.MAX_TARBALL_BYTES + 1)

    def fake_get(url, headers=None, timeout=None, stream=None):
        return FakeResponse(200, headers={}, content_chunks=[big_chunk])

    with patch("repo_fetch.requests.get", side_effect=fake_get):
        with pytest.raises(TarballTooLargeError):
            download_tarball("octocat/hello", "token")


def _build_tarball(file_map: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, content in file_map.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_extract_and_filter_skips_ignored_dirs():
    tarball = _build_tarball({
        "repo/main.py": b"print(1)\n",
        "repo/node_modules/lib.js": b"module.exports = {};\n",
    })
    tmp_dir, files = extract_and_filter(tarball)
    try:
        names = [os.path.basename(f) for f in files]
        assert "main.py" in names
        assert "lib.js" not in names
    finally:
        cleanup(tmp_dir)


def test_extract_and_filter_skips_oversized_files():
    tarball = _build_tarball({
        "repo/small.py": b"x = 1\n",
        "repo/huge.py": b"x" * (repo_fetch.MAX_FILE_BYTES + 1),
    })
    tmp_dir, files = extract_and_filter(tarball)
    try:
        names = [os.path.basename(f) for f in files]
        assert "small.py" in names
        assert "huge.py" not in names
    finally:
        cleanup(tmp_dir)


def test_extract_and_filter_caps_total_files(monkeypatch):
    monkeypatch.setattr(repo_fetch, "MAX_FILES_PER_REPO", 2)
    tarball = _build_tarball({f"repo/file{i}.py": b"x = 1\n" for i in range(5)})
    tmp_dir, files = extract_and_filter(tarball)
    try:
        assert len(files) == 2
    finally:
        cleanup(tmp_dir)


def test_cleanup_removes_directory():
    tarball = _build_tarball({"repo/a.py": b"x = 1\n"})
    tmp_dir, _ = extract_and_filter(tarball)
    cleanup(tmp_dir)
    assert not os.path.exists(tmp_dir)
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/code_analysis
python -m pytest tests/test_repo_fetch.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_fetch'`

- [ ] **Step 3: Write the minimal implementation**

`services/code_analysis/repo_fetch.py`:
```python
"""Phase 1 — tarball fetch, extraction, and file filtering (module spec
section 4/5). No git binary is used anywhere in this module — fetching
uses GitHub's tarball endpoint plus Python's stdlib tarfile module,
verified end-to-end against a real GitHub repo during design."""

import io
import os
import shutil
import tarfile
import tempfile

import requests

GITHUB_API = "https://api.github.com"

MAX_TARBALL_BYTES = 25 * 1024 * 1024  # 25MB
MAX_FILE_BYTES = 500 * 1024  # 500KB
MAX_FILES_PER_REPO = 300

SKIP_DIRS = {"node_modules", "vendor", "dist", "build", ".git", "__pycache__", ".venv", "venv"}


class InvalidTokenError(Exception):
    """Raised when GitHub reports the access token as invalid/revoked (401)."""


class TarballTooLargeError(Exception):
    """Raised when a repo's tarball exceeds MAX_TARBALL_BYTES."""


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "DevScore-CodeAnalysis",
    }


def fetch_repo_metadata(full_name: str, access_token: str) -> dict:
    """Fetches a single repo's metadata (used for its `fork` flag)."""
    resp = requests.get(f"{GITHUB_API}/repos/{full_name}", headers=_headers(access_token), timeout=15)
    if resp.status_code == 401:
        raise InvalidTokenError()
    resp.raise_for_status()
    return resp.json()


def download_tarball(full_name: str, access_token: str) -> bytes:
    """
    Downloads a repo's tarball. Aborts early (without downloading the
    whole thing) if Content-Length reports over MAX_TARBALL_BYTES, and
    also aborts mid-stream if the actual bytes exceed the cap even when
    the header is absent or understated.
    """
    resp = requests.get(
        f"{GITHUB_API}/repos/{full_name}/tarball",
        headers=_headers(access_token),
        timeout=30,
        stream=True,
    )
    if resp.status_code == 401:
        raise InvalidTokenError()
    resp.raise_for_status()

    content_length = resp.headers.get("Content-Length")
    if content_length is not None and int(content_length) > MAX_TARBALL_BYTES:
        resp.close()
        raise TarballTooLargeError()

    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > MAX_TARBALL_BYTES:
            resp.close()
            raise TarballTooLargeError()
        chunks.append(chunk)
    return b"".join(chunks)


def extract_and_filter(tarball_bytes: bytes):
    """
    Extracts the tarball into a fresh temp directory using the 'data'
    extraction filter (blocks path traversal / symlink escapes), then
    walks it filtering out SKIP_DIRS and oversized files, capping the
    total file count at MAX_FILES_PER_REPO. Returns
    (tmp_dir, filtered_file_paths). Caller must call cleanup(tmp_dir).
    """
    tmp_dir = tempfile.mkdtemp(prefix="code_analysis_")
    with tarfile.open(fileobj=io.BytesIO(tarball_bytes)) as tar:
        tar.extractall(tmp_dir, filter="data")

    filtered = []
    for root, dirs, files in os.walk(tmp_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            if len(filtered) >= MAX_FILES_PER_REPO:
                return tmp_dir, filtered
            path = os.path.join(root, fname)
            try:
                if os.path.getsize(path) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            filtered.append(path)
    return tmp_dir, filtered


def cleanup(tmp_dir: str) -> None:
    shutil.rmtree(tmp_dir, ignore_errors=True)
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/code_analysis
python -m pytest tests/test_repo_fetch.py -v
```
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add services/code_analysis/repo_fetch.py services/code_analysis/tests/test_repo_fetch.py
git commit -m "Add Phase 1 tarball fetch, extraction, and file filtering"
```

---

### Task 3: Static analysis — lizard invocation with the nesting-depth extension

**Files:**
- Create: `services/code_analysis/static_analysis.py`
- Test: `services/code_analysis/tests/test_static_analysis.py`

**Interfaces:**
- Produces: `static_analysis.analyze_files(file_paths: list[str]) -> dict` returning `{"language": str | None, "avg_cyclomatic_complexity": float | None, "total_functions": int, "total_lines": int, "max_nesting_depth": int}`. When `file_paths` is empty, or none are analyzable, returns the all-null/zero shape shown in the test below. Used by Task 5's orchestration.

This task's tests use real `lizard` (no mocking) against real temporary files (via pytest's built-in `tmp_path` fixture) — `lizard` is small, fast, and fully local, so there's no reason to mock it, matching how Module 1 tested its own local model.

- [ ] **Step 1: Write the failing test**

`services/code_analysis/tests/test_static_analysis.py`:
```python
import os

from static_analysis import analyze_files


def _write(tmp_path, name, content):
    path = os.path.join(str(tmp_path), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_analyze_files_computes_metrics_and_real_nesting_depth(tmp_path):
    # This is the exact regression case for the gotcha found during design:
    # lizard.analyze_file() alone silently reports max_nesting_depth=0 for
    # every function, because it has zero extensions loaded by default.
    # This test fails loudly if that naive form ever creeps back in.
    path = _write(tmp_path, "sample.py", (
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def complex_fn(x, y, z):\n"
        "    if x > 0:\n"
        "        if y > 0:\n"
        "            for i in range(z):\n"
        "                if i % 2 == 0:\n"
        "                    while i > 0:\n"
        "                        i -= 1\n"
        "                else:\n"
        "                    continue\n"
        "        else:\n"
        "            return -1\n"
        "    return x + y\n"
    ))
    result = analyze_files([path])
    assert result["language"] == "python"
    assert result["total_functions"] == 2
    assert result["max_nesting_depth"] == 5
    assert result["avg_cyclomatic_complexity"] == 3.5


def test_analyze_files_skips_unsupported_extensions(tmp_path):
    path = _write(tmp_path, "notes.txt", "just some notes, not code\n")
    result = analyze_files([path])
    assert result["total_functions"] == 0
    assert result["language"] is None
    assert result["avg_cyclomatic_complexity"] is None


def test_analyze_files_picks_dominant_language_by_nloc(tmp_path):
    py_path = _write(tmp_path, "big.py", "def f():\n" + "    x = 1\n" * 50 + "    return x\n")
    js_path = _write(tmp_path, "small.js", "function g() { return 1; }\n")
    result = analyze_files([py_path, js_path])
    assert result["language"] == "python"


def test_analyze_files_empty_list_returns_zeroed_result():
    result = analyze_files([])
    assert result == {
        "language": None,
        "avg_cyclomatic_complexity": None,
        "total_functions": 0,
        "total_lines": 0,
        "max_nesting_depth": 0,
    }
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/code_analysis
python -m pytest tests/test_static_analysis.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'static_analysis'`

- [ ] **Step 3: Write the minimal implementation**

`services/code_analysis/static_analysis.py`:
```python
"""
Phase 2 — static analysis via lizard (module spec section 5/8).

CRITICAL: lizard.analyze_file(...) is NOT used here. It is a pre-built
FileAnalyzer with ZERO extensions loaded (see lizard's own source:
`analyze_file = FileAnalyzer(get_extensions([]))`), so its
max_nesting_depth field silently stays 0 for every function regardless
of actual nesting depth. Verified directly during design against a
5-level-deep test function. The 'nd' (nesting depth) extension must be
loaded explicitly, as done below.
"""

import lizard

_ANALYZER = lizard.FileAnalyzer(lizard.get_extensions(['nd']))


def _language_for(path: str):
    """Returns lizard's language name for a file's extension, or None if
    lizard doesn't support it. FileInformation itself has no .language
    attribute (verified directly) — language is derived from the reader
    class lizard would use for this file's extension."""
    reader_cls = lizard.get_reader_for(path)
    if reader_cls is None:
        return None
    return reader_cls.language_names[0]


def analyze_files(file_paths: list) -> dict:
    """
    Runs lizard against every analyzable file in file_paths (silently
    skipping files lizard doesn't support, or that raise on parse), and
    rolls the per-function results up to one repo-level metrics dict.
    """
    all_functions = []
    language_nloc = {}

    for path in file_paths:
        language = _language_for(path)
        if language is None:
            continue
        try:
            file_info = _ANALYZER(path)
        except Exception:
            continue
        if file_info is None:
            continue
        all_functions.extend(file_info.function_list)
        language_nloc[language] = language_nloc.get(language, 0) + (file_info.nloc or 0)

    if not all_functions:
        return {
            "language": None,
            "avg_cyclomatic_complexity": None,
            "total_functions": 0,
            "total_lines": 0,
            "max_nesting_depth": 0,
        }

    dominant_language = max(language_nloc, key=language_nloc.get) if language_nloc else None
    total_ccn = sum(f.cyclomatic_complexity for f in all_functions)
    total_nloc = sum(f.nloc for f in all_functions)
    max_nd = max((f.max_nesting_depth for f in all_functions), default=0)

    return {
        "language": dominant_language,
        "avg_cyclomatic_complexity": round(total_ccn / len(all_functions), 2),
        "total_functions": len(all_functions),
        "total_lines": total_nloc,
        "max_nesting_depth": max_nd,
    }
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/code_analysis
python -m pytest tests/test_static_analysis.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add services/code_analysis/static_analysis.py services/code_analysis/tests/test_static_analysis.py
git commit -m "Add Phase 2 static analysis with correct nesting-depth extension"
```

---

### Task 4: Aggregation — per-repo to per-student rollup

**Files:**
- Create: `services/code_analysis/aggregation.py`
- Test: `services/code_analysis/tests/test_aggregation.py`

**Interfaces:**
- Produces: `aggregation.build_summary(repo_results: list[dict]) -> dict` returning `{"avg_complexity_overall": float | None, "total_loc_overall": int, "qualifying_repo_count": int}`. Computed only from items where `repo_result["included"]` is `True`. Used by Task 5's orchestration.

- [ ] **Step 1: Write the failing test**

`services/code_analysis/tests/test_aggregation.py`:
```python
from aggregation import build_summary


def test_build_summary_averages_across_included_repos():
    repos = [
        {"included": True, "avg_cyclomatic_complexity": 2.0, "total_lines": 100},
        {"included": True, "avg_cyclomatic_complexity": 4.0, "total_lines": 200},
    ]
    assert build_summary(repos) == {
        "avg_complexity_overall": 3.0,
        "total_loc_overall": 300,
        "qualifying_repo_count": 2,
    }


def test_build_summary_excludes_non_included_repos():
    repos = [
        {"included": True, "avg_cyclomatic_complexity": 2.0, "total_lines": 100},
        {"included": False, "avg_cyclomatic_complexity": None, "total_lines": None},
    ]
    assert build_summary(repos) == {
        "avg_complexity_overall": 2.0,
        "total_loc_overall": 100,
        "qualifying_repo_count": 1,
    }


def test_build_summary_no_included_repos_returns_nulls():
    repos = [{"included": False, "avg_cyclomatic_complexity": None, "total_lines": None}]
    assert build_summary(repos) == {
        "avg_complexity_overall": None,
        "total_loc_overall": 0,
        "qualifying_repo_count": 0,
    }


def test_build_summary_empty_list():
    assert build_summary([]) == {
        "avg_complexity_overall": None,
        "total_loc_overall": 0,
        "qualifying_repo_count": 0,
    }


def test_build_summary_counts_qualifying_repo_with_no_functions_found():
    # An included repo where lizard found nothing to measure (e.g. a repo
    # of only config files that passed the line-count filter) should still
    # count toward qualifying_repo_count, and its LOC (0) still sums in,
    # but it must not be averaged into avg_complexity_overall as if it
    # were a real 0-complexity codebase.
    repos = [
        {"included": True, "avg_cyclomatic_complexity": None, "total_lines": 0},
        {"included": True, "avg_cyclomatic_complexity": 2.0, "total_lines": 50},
    ]
    assert build_summary(repos) == {
        "avg_complexity_overall": 2.0,
        "total_loc_overall": 50,
        "qualifying_repo_count": 2,
    }
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/code_analysis
python -m pytest tests/test_aggregation.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'aggregation'`

- [ ] **Step 3: Write the minimal implementation**

`services/code_analysis/aggregation.py`:
```python
"""Phase 2 — per-repo -> per-student rollup (module spec section 4/8)."""


def build_summary(repo_results: list) -> dict:
    """
    Aggregates per-repo results into one per-student summary, computed
    ONLY from repos where `included` is True. A qualifying repo with no
    measurable complexity (avg_cyclomatic_complexity is None, e.g. lizard
    found no functions) still counts toward qualifying_repo_count and its
    line count still sums in, but it is excluded from the complexity
    average itself.
    """
    included = [r for r in repo_results if r.get("included")]
    if not included:
        return {"avg_complexity_overall": None, "total_loc_overall": 0, "qualifying_repo_count": 0}

    complexities = [
        r["avg_cyclomatic_complexity"] for r in included
        if r.get("avg_cyclomatic_complexity") is not None
    ]
    avg_complexity_overall = round(sum(complexities) / len(complexities), 2) if complexities else None
    total_loc_overall = sum(r.get("total_lines") or 0 for r in included)

    return {
        "avg_complexity_overall": avg_complexity_overall,
        "total_loc_overall": total_loc_overall,
        "qualifying_repo_count": len(included),
    }
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/code_analysis
python -m pytest tests/test_aggregation.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add services/code_analysis/aggregation.py services/code_analysis/tests/test_aggregation.py
git commit -m "Add per-repo to per-student aggregation"
```

---

### Task 5: Orchestration (`main.py`)

**Files:**
- Create: `services/code_analysis/main.py`
- Test: `services/code_analysis/tests/test_main.py`

**Interfaces:**
- Consumes: `exclusion_rules.*` (Task 1), `repo_fetch.*` (Task 2), `static_analysis.analyze_files` (Task 3), `aggregation.build_summary` (Task 4)
- Produces:
  - `main.analyze_one_repo(username: str, repo_name: str, access_token: str) -> dict` — one per-repo result matching the `/analyze-repos` response's per-repo shape (design doc section 4).
  - `main.run_analysis(username: str, repo_names: list[str], access_token: str) -> dict` — `{"repos": [...], "summary": {...}}`. Used by Task 6's `/analyze-repos` route.

- [ ] **Step 1: Write the failing test**

`services/code_analysis/tests/test_main.py`:
```python
from unittest.mock import patch

import repo_fetch
import main


def test_analyze_one_repo_excludes_forks():
    with patch("repo_fetch.fetch_repo_metadata", return_value={"fork": True}):
        result = main.analyze_one_repo("octocat", "some-fork", "token")
    assert result["repo_name"] == "some-fork"
    assert result["included"] is False
    assert result["excluded_reason"] == "fork"
    assert result["avg_cyclomatic_complexity"] is None


def test_analyze_one_repo_excludes_too_large():
    with patch("repo_fetch.fetch_repo_metadata", return_value={"fork": False}), \
         patch("repo_fetch.download_tarball", side_effect=repo_fetch.TarballTooLargeError()):
        result = main.analyze_one_repo("octocat", "huge-repo", "token")
    assert result["included"] is False
    assert result["excluded_reason"] == "too_large"


def test_analyze_one_repo_excludes_empty(tmp_path):
    with patch("repo_fetch.fetch_repo_metadata", return_value={"fork": False}), \
         patch("repo_fetch.download_tarball", return_value=b"fake-tarball-bytes"), \
         patch("repo_fetch.extract_and_filter", return_value=(str(tmp_path), [])), \
         patch("repo_fetch.cleanup") as mock_cleanup, \
         patch("static_analysis.analyze_files", return_value={
             "language": None, "avg_cyclomatic_complexity": None,
             "total_functions": 0, "total_lines": 5, "max_nesting_depth": 0,
         }):
        result = main.analyze_one_repo("octocat", "tiny-repo", "token")
    assert result["included"] is False
    assert result["excluded_reason"] == "empty"
    mock_cleanup.assert_called_once()


def test_analyze_one_repo_flags_tutorial_but_still_returns_metrics(tmp_path):
    fake_metrics = {
        "language": "python", "avg_cyclomatic_complexity": 1.5,
        "total_functions": 3, "total_lines": 40, "max_nesting_depth": 2,
    }
    with patch("repo_fetch.fetch_repo_metadata", return_value={"fork": False}), \
         patch("repo_fetch.download_tarball", return_value=b"fake-tarball-bytes"), \
         patch("repo_fetch.extract_and_filter", return_value=(str(tmp_path), ["a.py"])), \
         patch("repo_fetch.cleanup"), \
         patch("static_analysis.analyze_files", return_value=fake_metrics):
        result = main.analyze_one_repo("octocat", "python-tutorial", "token")
    assert result["included"] is False
    assert result["excluded_reason"] == "tutorial_clone_heuristic"
    assert result["avg_cyclomatic_complexity"] == 1.5
    assert result["total_functions"] == 3


def test_analyze_one_repo_includes_qualifying_repo(tmp_path):
    fake_metrics = {
        "language": "python", "avg_cyclomatic_complexity": 4.0,
        "total_functions": 10, "total_lines": 300, "max_nesting_depth": 3,
    }
    with patch("repo_fetch.fetch_repo_metadata", return_value={"fork": False}), \
         patch("repo_fetch.download_tarball", return_value=b"fake-tarball-bytes"), \
         patch("repo_fetch.extract_and_filter", return_value=(str(tmp_path), ["a.py"])), \
         patch("repo_fetch.cleanup"), \
         patch("static_analysis.analyze_files", return_value=fake_metrics):
        result = main.analyze_one_repo("octocat", "real-project", "token")
    assert result["included"] is True
    assert result["excluded_reason"] is None
    assert result["avg_cyclomatic_complexity"] == 4.0


def test_run_analysis_aggregates_across_repos():
    with patch("main.analyze_one_repo") as mock_analyze:
        mock_analyze.side_effect = [
            {
                "repo_name": "a", "included": True, "excluded_reason": None,
                "language": "python", "avg_cyclomatic_complexity": 2.0,
                "total_functions": 5, "total_lines": 100, "max_nesting_depth": 2,
            },
            {
                "repo_name": "b", "included": False, "excluded_reason": "fork",
                "language": None, "avg_cyclomatic_complexity": None,
                "total_functions": None, "total_lines": None, "max_nesting_depth": None,
            },
        ]
        result = main.run_analysis("octocat", ["a", "b"], "token")
    assert len(result["repos"]) == 2
    assert result["summary"] == {
        "avg_complexity_overall": 2.0,
        "total_loc_overall": 100,
        "qualifying_repo_count": 1,
    }
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/code_analysis
python -m pytest tests/test_main.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write the minimal implementation**

`services/code_analysis/main.py`:
```python
"""Orchestrates Phase 1 (fetch) -> Phase 3 (exclude) -> Phase 2 (analyze
+ aggregate) per repo, per module spec section 4."""

import aggregation
import exclusion_rules
import repo_fetch
import static_analysis


def _empty_metrics() -> dict:
    return {
        "language": None,
        "avg_cyclomatic_complexity": None,
        "total_functions": None,
        "total_lines": None,
        "max_nesting_depth": None,
    }


def analyze_one_repo(username: str, repo_name: str, access_token: str) -> dict:
    """Runs the full per-repo pipeline: metadata -> fork check -> tarball
    -> size check -> extract/filter -> empty check -> analyze -> tutorial
    check. Returns one result dict matching the /analyze-repos response's
    per-repo shape."""
    full_name = f"{username}/{repo_name}"

    metadata = repo_fetch.fetch_repo_metadata(full_name, access_token)
    if exclusion_rules.is_fork(metadata):
        return {"repo_name": repo_name, "included": False, "excluded_reason": "fork", **_empty_metrics()}

    try:
        tarball_bytes = repo_fetch.download_tarball(full_name, access_token)
    except repo_fetch.TarballTooLargeError:
        return {"repo_name": repo_name, "included": False, "excluded_reason": "too_large", **_empty_metrics()}

    tmp_dir, files = repo_fetch.extract_and_filter(tarball_bytes)
    try:
        metrics = static_analysis.analyze_files(files)

        if exclusion_rules.is_empty(metrics["total_lines"]):
            return {"repo_name": repo_name, "included": False, "excluded_reason": "empty", **_empty_metrics()}

        if exclusion_rules.matches_tutorial_heuristic(repo_name):
            return {
                "repo_name": repo_name, "included": False,
                "excluded_reason": "tutorial_clone_heuristic", **metrics,
            }

        return {"repo_name": repo_name, "included": True, "excluded_reason": None, **metrics}
    finally:
        repo_fetch.cleanup(tmp_dir)


def run_analysis(username: str, repo_names: list, access_token: str) -> dict:
    """Runs analyze_one_repo for every repo_names entry, then aggregates
    to a per-student summary. Returns {"repos": [...], "summary": {...}}."""
    results = [analyze_one_repo(username, name, access_token) for name in repo_names]
    summary = aggregation.build_summary(results)
    return {"repos": results, "summary": summary}
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/code_analysis
python -m pytest tests/test_main.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add services/code_analysis/main.py services/code_analysis/tests/test_main.py
git commit -m "Add code-analysis orchestration combining fetch, exclusion, and analysis"
```

---

### Task 6: Flask app (routes + shared-secret auth + catch-all error handling)

**Files:**
- Create: `services/code_analysis/app.py`
- Test: `services/code_analysis/tests/test_app.py`

**Interfaces:**
- Consumes: `repo_fetch.InvalidTokenError` (Task 2), `main.run_analysis` (Task 5)
- Produces: HTTP routes `GET /health`, `POST /analyze-repos` — consumed by Node's `server/src/utils/codeAnalysis.js` (Task 8).

- [ ] **Step 1: Write the failing test**

`services/code_analysis/tests/test_app.py`:
```python
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


def test_analyze_repos_requires_fields(client):
    resp = client.post("/analyze-repos", json={})
    assert resp.status_code == 400


def test_analyze_repos_returns_result(client, monkeypatch):
    fake_result = {
        "repos": [],
        "summary": {"avg_complexity_overall": None, "total_loc_overall": 0, "qualifying_repo_count": 0},
    }
    monkeypatch.setattr(app_module, "run_analysis", lambda username, repo_names, token: fake_result)
    resp = client.post(
        "/analyze-repos",
        json={"github_username": "octocat", "access_token": "tok", "repo_names": []},
    )
    assert resp.status_code == 200
    assert resp.get_json() == fake_result


def test_analyze_repos_invalid_token_returns_401(client, monkeypatch):
    def raise_invalid(username, repo_names, token):
        raise app_module.InvalidTokenError()

    monkeypatch.setattr(app_module, "run_analysis", raise_invalid)
    resp = client.post(
        "/analyze-repos",
        json={"github_username": "octocat", "access_token": "bad", "repo_names": ["a"]},
    )
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "invalid_token"}


def test_analyze_repos_unexpected_error_returns_json_500(client, monkeypatch):
    def raise_boom(username, repo_names, token):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "run_analysis", raise_boom)
    resp = client.post(
        "/analyze-repos",
        json={"github_username": "octocat", "access_token": "tok", "repo_names": ["a"]},
    )
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "analysis_failed"


def test_unauthorized_without_api_key(client, monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "secret123")
    resp = client.post("/analyze-repos", json={})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/code_analysis
python -m pytest tests/test_app.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write the minimal implementation**

`services/code_analysis/app.py`:
```python
"""
HTTP wrapper around main.run_analysis() — the code-analysis microservice
(Module 2). Stateless, like cv_parser and skill_verification: it never
touches Supabase. Node POSTs a GitHub token + repo name list here and
gets per-repo metrics + a summary back; Node does all persistence.
"""

import os

from flask import Flask, jsonify, request

from main import run_analysis
from repo_fetch import InvalidTokenError

app = Flask(__name__)

# Shared secret with the Node backend, same pattern as cv_parser/skill_verification.
# No key configured (local dev) degrades to open access.
API_KEY = os.environ.get("CODE_ANALYSIS_API_KEY", "")


def _authorized(req) -> bool:
    if not API_KEY:
        return True
    return req.headers.get("X-Api-Key") == API_KEY


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/analyze-repos")
def analyze_repos_route():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    username = body.get("github_username")
    token = body.get("access_token")
    repo_names = body.get("repo_names") or []
    if not username or not token:
        return jsonify({"error": "github_username and access_token are required"}), 400

    try:
        result = run_analysis(username, repo_names, token)
    except InvalidTokenError:
        return jsonify({"error": "invalid_token"}), 401
    except Exception as e:
        # A single unparseable file or one bad repo is already handled
        # inside main.py/static_analysis.py — reaching here means something
        # truly unexpected happened. Return structured JSON, never Flask's
        # default HTML error page (lesson carried over from Module 1's
        # final review, which found exactly this gap).
        return jsonify({"error": "analysis_failed", "detail": str(e)}), 500

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5003)))
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/code_analysis
python -m pytest tests/test_app.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full Python test suite**

```bash
cd services/code_analysis
python -m pytest -v
```
Expected: all tests across all files PASS (41 total: 10 + 10 + 4 + 5 + 6 + 6 — recount at execution time against actual files).

- [ ] **Step 6: Commit**

```bash
git add services/code_analysis/app.py services/code_analysis/tests/test_app.py
git commit -m "Add code-analysis Flask app with shared-secret auth and catch-all error handling"
```

---

## Part B — Node integration

### Task 7: Database schema and environment configuration

**Files:**
- Modify: `server/supabase/schema.sql`
- Modify: `server/.env.example`
- Modify: `server/src/config/env.js`

**Interfaces:**
- Produces: Supabase tables `code_analysis`, `code_analysis_summary`; `env.codeAnalysis.url` / `env.codeAnalysis.apiKey` — consumed by Task 8.

- [ ] **Step 1: Check whether `server/.env` exists with real Supabase credentials**

```bash
ls server/.env
```
Whether or not it exists, proceed with Steps 2-5 below (the schema file itself is edited either way). **Do not** attempt to apply the migration to a live database yourself, even if real credentials are present — this is a side-effect on shared infrastructure that needs the project owner's explicit action, not an automatic step. Note in your report whether `server/.env` exists, so the controller knows whether to flag this to the user as "ready to apply" vs. "credentials also still needed."

- [ ] **Step 2: Append the new tables to `server/supabase/schema.sql`**

Add after the existing `skill_verification` block (from the prior module) and before the final RLS-enabling section:

```sql
-- ---------------------------------------------------------------------------
-- code_analysis  — per-repo structural complexity metrics (AST-based code
-- analysis module). Replaced wholesale on each re-run (delete + reinsert),
-- same pattern as github_evidence/skill_verification.
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- code_analysis_summary  — per-student rollup, computed once by the
-- code-analysis service's aggregation step and stored as-is. One row per
-- user; replaced wholesale on each re-run.
-- ---------------------------------------------------------------------------
create table if not exists public.code_analysis_summary (
  user_id                uuid primary key references public.users (id) on delete cascade,
  avg_complexity_overall numeric,
  total_loc_overall      int,
  qualifying_repo_count  int not null default 0,
  computed_at            timestamptz not null default now()
);
```

And add these two lines alongside the existing `alter table ... enable row level security;` block at the bottom of the file:
```sql
alter table public.code_analysis enable row level security;
alter table public.code_analysis_summary enable row level security;
```

- [ ] **Step 3: Add environment variables to `server/.env.example`**

Append after the existing `SKILL_VERIFICATION_API_KEY=` line:
```
# Code-analysis microservice (AST/complexity metrics via lizard).
CODE_ANALYSIS_URL=http://localhost:5003
CODE_ANALYSIS_API_KEY=
```

- [ ] **Step 4: Add the config block to `server/src/config/env.js`**

Modify the `env` object — add after the existing `skillVerification` block:
```js
  codeAnalysis: {
    url: process.env.CODE_ANALYSIS_URL || 'http://localhost:5003',
    apiKey: process.env.CODE_ANALYSIS_API_KEY || '',
  },
```

- [ ] **Step 5: Verify JS syntax**

```bash
cd server
node --check src/config/env.js
```

- [ ] **Step 6: Commit**

```bash
git add server/supabase/schema.sql server/.env.example server/src/config/env.js
git commit -m "Add code_analysis and code_analysis_summary tables and service config"
```

---

### Task 8: Node HTTP client for the Python service

**Files:**
- Create: `server/src/utils/codeAnalysis.js`

**Interfaces:**
- Consumes: `env.codeAnalysis` (Task 7)
- Produces: `analyzeRepos(username, accessToken, repoNames) -> Promise<{repos, summary}>` (throws `Error('invalid_github_token')` on a 401). Consumed by Task 11's controller.

No automated test for this file — thin HTTP-call wrapper with no branching logic beyond status-code checks, matching `cvParser.js`/`skillVerification.js`'s precedent in this codebase. Exercised by Task 12's manual integration test.

- [ ] **Step 1: Write the implementation**

`server/src/utils/codeAnalysis.js`:
```js
import { env } from '../config/env.js';

// Tarball download + extraction + lizard across up to 15 repos is heavier
// than either cv_parser's single-PDF parse or skill_verification's
// metadata-only fetch — sized accordingly.
const REQUEST_TIMEOUT_MS = 90_000;

function headers() {
  return {
    'Content-Type': 'application/json',
    ...(env.codeAnalysis.apiKey ? { 'X-Api-Key': env.codeAnalysis.apiKey } : {}),
  };
}

/** Calls the code-analysis service's /analyze-repos route. */
export async function analyzeRepos(username, accessToken, repoNames) {
  const res = await fetch(`${env.codeAnalysis.url}/analyze-repos`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({
      github_username: username,
      access_token: accessToken,
      repo_names: repoNames,
    }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (res.status === 401) {
    throw new Error('invalid_github_token');
  }
  if (!res.ok) {
    throw new Error(`code_analysis analyze-repos responded ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 2: Verify syntax**

```bash
cd server
node --check src/utils/codeAnalysis.js
```

- [ ] **Step 3: Commit**

```bash
git add server/src/utils/codeAnalysis.js
git commit -m "Add Node HTTP client for the code-analysis service"
```

---

### Task 9: Pure cache-freshness helper

**Files:**
- Create: `server/src/utils/codeAnalysisHelpers.js`
- Test: `server/src/utils/codeAnalysisHelpers.test.js`

**Interfaces:**
- Produces: `isCacheFresh(analyzedAt, now = Date.now()) -> boolean`. Consumed by Task 11's controller.

This duplicates Module 1's `skillVerificationHelpers.js`'s `isCacheFresh` function rather than importing it — a deliberate choice (see design doc section 10) to keep the two modules fully independent rather than introduce a cross-module import for a 3-line function.

- [ ] **Step 1: Write the failing test**

`server/src/utils/codeAnalysisHelpers.test.js`:
```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isCacheFresh } from './codeAnalysisHelpers.js';

const DAY_MS = 24 * 60 * 60 * 1000;

test('isCacheFresh: null analyzedAt is never fresh', () => {
  assert.equal(isCacheFresh(null), false);
});

test('isCacheFresh: under 24h old is fresh', () => {
  const now = Date.now();
  const analyzedAt = new Date(now - DAY_MS + 1000).toISOString();
  assert.equal(isCacheFresh(analyzedAt, now), true);
});

test('isCacheFresh: over 24h old is stale', () => {
  const now = Date.now();
  const analyzedAt = new Date(now - DAY_MS - 1000).toISOString();
  assert.equal(isCacheFresh(analyzedAt, now), false);
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd server
node --test src/utils/codeAnalysisHelpers.test.js
```
Expected: FAIL — cannot find module `./codeAnalysisHelpers.js`

- [ ] **Step 3: Write the minimal implementation**

`server/src/utils/codeAnalysisHelpers.js`:
```js
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;

/** True if `analyzedAt` is within the 24h cache window. */
export function isCacheFresh(analyzedAt, now = Date.now()) {
  if (!analyzedAt) return false;
  return now - new Date(analyzedAt).getTime() < CACHE_TTL_MS;
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd server
node --test src/utils/codeAnalysisHelpers.test.js
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add server/src/utils/codeAnalysisHelpers.js server/src/utils/codeAnalysisHelpers.test.js
git commit -m "Add pure cache-freshness helper for code analysis"
```

---

### Task 10: Data-access model

**Files:**
- Create: `server/src/models/CodeAnalysis.js`

**Interfaces:**
- Produces:
  - `findByUserId(userId) -> Promise<row[]>`
  - `findSummaryByUserId(userId) -> Promise<row | null>`
  - `latestAnalyzedAt(userId) -> Promise<string | null>`
  - `replaceForUser(userId, repoResults) -> Promise<row[]>` (`repoResults` = the Python service's `/analyze-repos` `repos` array shape)
  - `upsertSummary(userId, summary) -> Promise<row>` (`summary` = the Python service's `summary` object, stored as-is — see Global Constraints)
- All consumed by Task 11's controller. No automated tests — plain Supabase CRUD with no branching logic, following the exact style of the existing untested `GithubEvidence.js`/`SkillVerification.js` models; exercised by Task 12's manual integration test.

- [ ] **Step 1: Create `server/src/models/CodeAnalysis.js`**

```js
import { supabase } from '../config/db.js';

/**
 * Per-repo structural complexity metrics and their per-student rollup
 * (AST-based code analysis module). Both tables are replaced wholesale
 * on each re-run — see replaceForUser/upsertSummary.
 */

/** Fetch stored per-repo results for a user, newest analysis first. */
export async function findByUserId(userId) {
  const { data, error } = await supabase
    .from('code_analysis')
    .select('*')
    .eq('user_id', userId)
    .order('analyzed_at', { ascending: false });
  if (error) throw new Error(error.message);
  return data;
}

/** Fetch the stored summary row for a user, or null if never computed. */
export async function findSummaryByUserId(userId) {
  const { data, error } = await supabase
    .from('code_analysis_summary')
    .select('*')
    .eq('user_id', userId)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

/** The most recent analyzed_at for a user, or null if never analyzed. */
export async function latestAnalyzedAt(userId) {
  const { data, error } = await supabase
    .from('code_analysis')
    .select('analyzed_at')
    .eq('user_id', userId)
    .order('analyzed_at', { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data?.analyzed_at || null;
}

/**
 * Replace all per-repo results for a user with a fresh analysis result.
 * `repoResults` is the code-analysis service's /analyze-repos "repos"
 * array shape: [{ repo_name, included, excluded_reason, language,
 * avg_cyclomatic_complexity, total_functions, total_lines,
 * max_nesting_depth }].
 */
export async function replaceForUser(userId, repoResults) {
  const { error: deleteError } = await supabase
    .from('code_analysis')
    .delete()
    .eq('user_id', userId);
  if (deleteError) throw new Error(deleteError.message);

  if (repoResults.length === 0) return [];

  const rows = repoResults.map((r) => ({
    user_id: userId,
    repo_name: r.repo_name,
    language: r.language,
    avg_cyclomatic_complexity: r.avg_cyclomatic_complexity,
    total_functions: r.total_functions,
    total_lines: r.total_lines,
    max_nesting_depth: r.max_nesting_depth,
    included: r.included,
    excluded_reason: r.excluded_reason,
  }));
  const { data, error } = await supabase.from('code_analysis').insert(rows).select();
  if (error) throw new Error(error.message);
  return data;
}

/**
 * Upsert the per-student summary row. `summary` is the code-analysis
 * service's already-computed { avg_complexity_overall, total_loc_overall,
 * qualifying_repo_count } object — stored as-is, never recomputed here.
 */
export async function upsertSummary(userId, summary) {
  const { data, error } = await supabase
    .from('code_analysis_summary')
    .upsert(
      {
        user_id: userId,
        avg_complexity_overall: summary.avg_complexity_overall,
        total_loc_overall: summary.total_loc_overall,
        qualifying_repo_count: summary.qualifying_repo_count,
        computed_at: new Date().toISOString(),
      },
      { onConflict: 'user_id' },
    )
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}
```

- [ ] **Step 2: Verify syntax**

```bash
cd server
node --check src/models/CodeAnalysis.js
```

- [ ] **Step 3: Commit**

```bash
git add server/src/models/CodeAnalysis.js
git commit -m "Add CodeAnalysis model"
```

---

### Task 11: Controller and routes

**Files:**
- Create: `server/src/controllers/codeAnalysisController.js`
- Create: `server/src/routes/codeAnalysisRoutes.js`
- Modify: `server/src/app.js`

**Interfaces:**
- Consumes: `ROLES` (`User.js`), `findActiveByUserAndProvider` (`OAuthSession.js`), `decryptToken` (`secureToken.js`), `GithubConnection.findByUserId`, `CodeAnalysis.*` (Task 10), `analyzeRepos` (Task 8), `isCacheFresh` (Task 9), `findOwnedCandidate` (`server/src/utils/candidateOwnership.js`, built in the prior module — reused as-is)
- Produces: `POST /api/code-analysis/run`, `GET /api/code-analysis/:studentId/summary` — this module's public API surface, per design doc section 7. No automated test — orchestrates several already-tested I/O-bound pieces with no new pure logic of its own; exercised by Task 12's manual integration test.

- [ ] **Step 1: Verify `server/src/utils/candidateOwnership.js` exists and exports `findOwnedCandidate`**

```bash
cd server
node -e "import('./src/utils/candidateOwnership.js').then(m => console.log(typeof m.findOwnedCandidate))"
```
Expected: `function`. This confirms the reuse target from the prior module is present before importing it below — if this fails, STOP and report NEEDS_CONTEXT rather than writing a new ownership implementation from scratch.

- [ ] **Step 2: Create `server/src/controllers/codeAnalysisController.js`**

```js
import { ROLES } from '../models/User.js';
import { findActiveByUserAndProvider } from '../models/OAuthSession.js';
import { decryptToken } from '../utils/secureToken.js';
import * as GithubConnection from '../models/GithubConnection.js';
import * as CodeAnalysis from '../models/CodeAnalysis.js';
import { analyzeRepos } from '../utils/codeAnalysis.js';
import { isCacheFresh } from '../utils/codeAnalysisHelpers.js';
import { findOwnedCandidate } from '../utils/candidateOwnership.js';

const MAX_REPOS = 15;
const GITHUB_API = 'https://api.github.com';
const EMPTY_SUMMARY = { avg_complexity_overall: null, total_loc_overall: 0, qualifying_repo_count: 0 };

/** A 502 for the Node error handler to surface when the Python service is unreachable or errors. */
function serviceUnavailableError() {
  const err = new Error('code_analysis_service_unavailable');
  err.status = 502;
  err.expose = true;
  return err;
}

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

/** Fetches up to MAX_REPOS public, non-fork repo names for a GitHub user. */
async function listPublicNonForkRepoNames(username, accessToken) {
  const res = await fetch(
    `${GITHUB_API}/users/${username}/repos?per_page=100&sort=pushed&direction=desc`,
    {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'DevScore-CodeAnalysis',
      },
      signal: AbortSignal.timeout(15_000),
    },
  );
  if (res.status === 401) throw new Error('invalid_github_token');
  if (!res.ok) throw new Error(`github repo list responded ${res.status}`);
  const repos = await res.json();
  return repos
    .filter((r) => !r.private && !r.fork)
    .slice(0, MAX_REPOS)
    .map((r) => r.name);
}

/** Clears any prior results and responds with the empty-analysis shape. */
async function respondEmpty(res, studentId) {
  await CodeAnalysis.replaceForUser(studentId, []);
  await CodeAnalysis.upsertSummary(studentId, EMPTY_SUMMARY);
  return res.json({
    status: 'completed',
    repos_analyzed: 0,
    repos_excluded: 0,
    summary: EMPTY_SUMMARY,
  });
}

/** Runs the fetch + analyze pipeline for one student and persists results. */
export async function runAnalysis(req, res, next) {
  try {
    const studentId = await resolveStudentId(req, req.body?.studentId);
    if (!studentId) {
      return res.status(404).json({ error: 'Candidate not found' });
    }

    const [connection, session] = await Promise.all([
      GithubConnection.findByUserId(studentId),
      findActiveByUserAndProvider(studentId, 'github'),
    ]);
    if (!connection || !session?.encrypted_access_token) {
      return respondEmpty(res, studentId);
    }

    const force = req.user.role === ROLES.STUDENT && req.query?.force === '1';
    const latest = await CodeAnalysis.latestAnalyzedAt(studentId);
    if (!force && isCacheFresh(latest)) {
      const summary = await CodeAnalysis.findSummaryByUserId(studentId);
      return res.json({
        status: 'completed',
        repos_analyzed: null,
        repos_excluded: null,
        summary: summary || EMPTY_SUMMARY,
      });
    }

    const accessToken = decryptToken(session.encrypted_access_token);

    let repoNames;
    try {
      repoNames = await listPublicNonForkRepoNames(connection.username, accessToken);
    } catch (err) {
      if (err.message === 'invalid_github_token') {
        return respondEmpty(res, studentId);
      }
      return next(serviceUnavailableError());
    }

    let result;
    try {
      result = await analyzeRepos(connection.username, accessToken, repoNames);
    } catch (err) {
      if (err.message === 'invalid_github_token') {
        return respondEmpty(res, studentId);
      }
      return next(serviceUnavailableError());
    }

    await CodeAnalysis.replaceForUser(studentId, result.repos);
    await CodeAnalysis.upsertSummary(studentId, result.summary);

    res.json({
      status: 'completed',
      repos_analyzed: result.repos.filter((r) => r.included).length,
      repos_excluded: result.repos.filter((r) => !r.included).length,
      summary: result.summary,
    });
  } catch (err) {
    next(err);
  }
}

/** Reads the stored summary — no recompute. */
export async function getSummary(req, res, next) {
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

    const summary = await CodeAnalysis.findSummaryByUserId(studentId);
    res.json({ summary: summary || null });
  } catch (err) {
    next(err);
  }
}
```

- [ ] **Step 3: Create `server/src/routes/codeAnalysisRoutes.js`**

```js
import { Router } from 'express';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { runAnalysis, getSummary } from '../controllers/codeAnalysisController.js';

const router = Router();

router.post('/run', requireAuth, requireRole('student', 'recruiter'), runAnalysis);
router.get('/:studentId/summary', requireAuth, requireRole('student', 'recruiter'), getSummary);

export default router;
```

- [ ] **Step 4: Mount the router in `server/src/app.js`**

Add the import alongside the other route imports:
```js
import codeAnalysisRoutes from './routes/codeAnalysisRoutes.js';
```
And mount it alongside the other `app.use('/api/...')` lines:
```js
  app.use('/api/code-analysis', codeAnalysisRoutes);
```

- [ ] **Step 5: Verify syntax and import resolution**

```bash
cd server
node --check src/controllers/codeAnalysisController.js
node --check src/routes/codeAnalysisRoutes.js
node --check src/app.js
node -e "import('./src/app.js').then(() => console.log('app.js imports resolved OK')).catch(e => { console.error(e); process.exit(1); })"
```
The dynamic import check does not need a real Supabase connection — nothing at module-load time calls the database, only route handlers do.

- [ ] **Step 6: Confirm the app.js diff is purely additive**

```bash
git diff server/src/app.js
```
Only two new lines (one import, one `app.use`) should appear — no existing route mount reordered or removed.

- [ ] **Step 7: Commit**

```bash
git add server/src/controllers/codeAnalysisController.js server/src/routes/codeAnalysisRoutes.js server/src/app.js
git commit -m "Wire up code-analysis API endpoints"
```

---

### Task 12: Full Node test suite run + manual end-to-end integration test

**Files:** None created — this confirms everything from Tasks 7-11 works together, then does a manual verification pass (per design doc section 10: exact metric values aren't asserted in code here; this is a sanity check against real data).

- [ ] **Step 1: Run the full Node test suite**

```bash
cd server
npm test
```
Expected: PASS — all tests from Tasks 9 (this module) plus Module 1's existing tests (9 tests), for 12 total. The existing `node --test src/**/*.test.js` script picks up the new `codeAnalysisHelpers.test.js` file automatically — no `package.json` change needed for this.

- [ ] **Step 2: Run the full Python test suite for this service**

```bash
cd services/code_analysis
python -m pytest -v
```
Expected: PASS — all tests from Tasks 1-6.

- [ ] **Step 3: Start both services locally**

```bash
cd services/code_analysis
python -m pip install -r requirements-dev.txt
python app.py
```
In a second terminal:
```bash
cd server
npm run dev
```
Note: as with the prior module, `server/src/server.js` will refuse to boot without real Supabase credentials in `server/.env` — if those aren't available in this environment, skip to Step 6 instead of Steps 4-5, and note this limitation in your report rather than fabricating results.

- [ ] **Step 4: Prepare test data**

Using the running app (or direct Supabase writes), ensure at least one test student has a connected GitHub account pointing at a real public GitHub profile with actual repos.

- [ ] **Step 5: Trigger analysis and sanity-check results**

```bash
curl -X POST http://localhost:5000/api/code-analysis/run \
  -H "Content-Type: application/json" \
  -H "Cookie: devscore_session=<a real session cookie from logging in as that student>"
```
Confirm, by eye, against the test student's actual GitHub profile: repos you know are forks show up excluded with `reason: "fork"`; a repo you know is substantial shows a plausible `avg_cyclomatic_complexity` and nonzero `max_nesting_depth` (not always 0 — this is the specific regression this module's design was built around); `qualifying_repo_count` in the summary matches the number of non-excluded repos you'd expect.

- [ ] **Step 6: If real credentials aren't available in this environment, run the credential-free smoke test instead**

```bash
cd services/code_analysis
python app.py
```
In another terminal:
```bash
curl -s http://localhost:5003/health
curl -s -X POST http://localhost:5003/analyze-repos \
  -H "Content-Type: application/json" \
  -d '{"github_username": "octocat", "access_token": "", "repo_names": ["Hello-World"]}'
```
This exercises the real GitHub tarball-fetch and `lizard` pipeline against a real public repo without needing a DevScore session or Supabase — `octocat/Hello-World`'s tarball fetch does not require a valid token for a public repo's tarball endpoint in practice, but if GitHub rejects the empty token, use any real personal access token with just `public_repo` read scope instead. Confirm the response's `repos[0]` has non-null metrics (this repo is tiny — a `README` file only — so it will likely be excluded as `"empty"`; if so, additionally try a repo you know has real source code, e.g. one of your own).

- [ ] **Step 7: Note findings**

No commit for this task. If this surfaces a real bug, fix it as a follow-up task with its own test (per this plan's TDD approach) rather than patching silently.
