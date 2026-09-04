"""
GitHub REST client: caching, rate limiting, and honest failure.

The SRS names the 5,000 req/hour authenticated limit as an interoperability
requirement, and the project summary flags it as a live risk: "GitHub API
rate limits will bite when scoring many candidates or mining deeply."
Scoring one candidate properly costs roughly

    1 (user) + 1 (repo list) + R×(languages + tree) + F (file fetches)

which for a student with 20 repos and 60 sampled files is ~100 calls. A
100-candidate validation run is therefore ~10,000 calls — twice the hourly
budget. Three mechanisms make that survivable:

  DISK CACHE     Every GET is cached to disk keyed by URL. Re-running the
                 batch (which you will, constantly, while tuning weights)
                 costs zero API calls. Cache entries carry the ETag, so a
                 refresh revalidates with `If-None-Match` and a 304 does
                 not count against the rate limit at all.

  BUDGET GUARD   The client refuses to start work it cannot finish. When
                 `X-RateLimit-Remaining` drops below `reserve`, calls raise
                 RateLimitExhausted rather than returning partial data that
                 would silently produce a *lower* score for the candidate
                 unlucky enough to be scored at the end of the batch. A
                 wrong score is worse than a missing one.

  BACKOFF        403/429 with `Retry-After` or a future `X-RateLimit-Reset`
                 is respected; secondary-rate-limit 403s back off
                 exponentially.

Unauthenticated use (60 req/hour) works for a single demo candidate and is
useless for anything else — set GITHUB_TOKEN.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com"
USER_AGENT = "ScriptFusion-DevScore-Engine/0.2 (final-year research project)"


class GitHubError(RuntimeError):
    """Any non-retryable GitHub failure (404, bad token, malformed response)."""


class RateLimitExhausted(GitHubError):
    """Budget guard tripped — we stop rather than produce a partial score."""


@dataclass
class _CacheEntry:
    etag: str
    body: Any


def _token_from_gh_cli() -> str:
    """
    Borrow the GitHub CLI's token when GITHUB_TOKEN is unset.

    Unauthenticated GitHub allows 60 requests an hour — roughly half of one
    candidate — so an unset token turns every batch run into a wall of
    RateLimitExhausted. Most developers on this project already have `gh`
    logged in, so checking it removes the single most common setup failure.
    Read-only: the token is used for public repository reads and nothing else.
    """
    import shutil
    import subprocess

    if not shutil.which("gh"):
        return ""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    token = (result.stdout or "").strip()
    return token if result.returncode == 0 and token.startswith(("gho_", "ghp_", "github_pat_")) else ""


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        cache_dir: str | Path = ".cache/github",
        *,
        reserve: int = 100,
        max_retries: int = 4,
        offline: bool = False,
        timeout: int = 30,
    ) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN") or _token_from_gh_cli()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.reserve = reserve if self.token else 5
        self.max_retries = max_retries
        self.offline = offline
        self.timeout = timeout

        self.calls = 0
        self.cache_hits = 0
        self.rate_remaining: int | None = None
        self.rate_reset: int | None = None

    # -- cache ---------------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:40]
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, url: str) -> _CacheEntry | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return _CacheEntry(etag=raw.get("etag", ""), body=raw.get("body"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache(self, url: str, etag: str, body: Any) -> None:
        try:
            self._cache_path(url).write_text(
                json.dumps({"url": url, "etag": etag, "body": body}),
                encoding="utf-8",
            )
        except OSError:
            pass  # a read-only cache dir degrades to "no cache", not a crash

    # -- transport -----------------------------------------------------------

    def _headers(self, etag: str = "") -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if etag:
            headers["If-None-Match"] = etag
        return headers

    def _note_limits(self, headers: Any) -> None:
        try:
            remaining = headers.get("X-RateLimit-Remaining")
            reset = headers.get("X-RateLimit-Reset")
            if remaining is not None:
                self.rate_remaining = int(remaining)
            if reset is not None:
                self.rate_reset = int(reset)
        except (TypeError, ValueError):
            pass

    def get(self, path: str, *, params: dict[str, Any] | None = None, allow_404: bool = False) -> Any:
        url = path if path.startswith("http") else f"{API_ROOT}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        cached = self._read_cache(url)
        if self.offline:
            if cached is None:
                raise GitHubError(f"offline mode and no cached response for {url}")
            self.cache_hits += 1
            return cached.body

        # Fresh-enough cache with no ETag (e.g. raw file content) is returned
        # without a network round trip at all.
        if cached is not None and not cached.etag:
            self.cache_hits += 1
            return cached.body

        if (
            self.rate_remaining is not None
            and self.rate_remaining <= self.reserve
            and cached is None
        ):
            raise RateLimitExhausted(
                f"rate limit budget exhausted ({self.rate_remaining} left, reserve={self.reserve}); "
                f"resets at {self.rate_reset}"
            )

        etag = cached.etag if cached else ""
        for attempt in range(self.max_retries):
            request = urllib.request.Request(url, headers=self._headers(etag), method="GET")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self.calls += 1
                    self._note_limits(response.headers)
                    body = json.loads(response.read().decode("utf-8"))
                    self._write_cache(url, response.headers.get("ETag", ""), body)
                    return body

            except urllib.error.HTTPError as err:
                self.calls += 1
                self._note_limits(err.headers)

                if err.code == 304 and cached is not None:
                    # Revalidated — free, does not consume rate budget.
                    self.cache_hits += 1
                    return cached.body

                if err.code == 404:
                    if allow_404:
                        return None
                    raise GitHubError(f"404 not found: {url}") from err

                if err.code == 401:
                    raise GitHubError("GitHub rejected the token (401).") from err

                if err.code in (403, 429):
                    if cached is not None:
                        return cached.body
                    wait = self._retry_after(err.headers, attempt)
                    if wait is None or attempt == self.max_retries - 1:
                        raise RateLimitExhausted(
                            f"{err.code} from GitHub and no cached copy of {url}"
                        ) from err
                    time.sleep(wait)
                    continue

                if 500 <= err.code < 600:
                    time.sleep(2 ** attempt)
                    continue

                raise GitHubError(f"HTTP {err.code} for {url}") from err

            except (OSError, http.client.HTTPException, json.JSONDecodeError) as err:
                # Every transient way a GitHub response can fail to arrive:
                #   OSError      URLError, TimeoutError, and ConnectionResetError
                #                (GitHub dropping a keep-alive mid-stream)
                #   HTTPException  IncompleteRead — the body was cut short. Not
                #                an OSError, so an earlier version let it escape
                #                and kill the candidate being scored.
                #   JSONDecodeError  a truncated body that still read cleanly.
                # All are worth retrying; none should end a cohort run.
                if cached is not None:
                    return cached.body
                if attempt == self.max_retries - 1:
                    raise GitHubError(f"network failure for {url}: {err}") from err
                time.sleep(2 ** attempt)

        raise GitHubError(f"exhausted retries for {url}")

    @staticmethod
    def _retry_after(headers: Any, attempt: int) -> float | None:
        try:
            retry_after = headers.get("Retry-After")
            if retry_after:
                return min(float(retry_after), 90.0)
            reset = headers.get("X-RateLimit-Reset")
            if reset:
                delta = int(reset) - time.time()
                # A primary-limit reset can be up to an hour away; waiting
                # that long inside a batch run is worse than failing loudly.
                if 0 < delta <= 90:
                    return delta + 1
                if delta > 90:
                    return None
        except (TypeError, ValueError):
            pass
        return 2.0 * (2 ** attempt)

    def paginate(self, path: str, *, params: dict[str, Any] | None = None, max_pages: int = 4) -> list[Any]:
        out: list[Any] = []
        params = dict(params or {})
        params.setdefault("per_page", 100)
        for page in range(1, max_pages + 1):
            params["page"] = page
            batch = self.get(path, params=params)
            if not isinstance(batch, list) or not batch:
                break
            out.extend(batch)
            if len(batch) < params["per_page"]:
                break
        return out

    # -- typed helpers -------------------------------------------------------

    def user(self, username: str) -> dict[str, Any] | None:
        return self.get(f"/users/{urllib.parse.quote(username)}", allow_404=True)

    def repos(self, username: str, max_repos: int = 100) -> list[dict[str, Any]]:
        repos = self.paginate(
            f"/users/{urllib.parse.quote(username)}/repos",
            params={"sort": "pushed", "type": "owner"},
            max_pages=2,
        )
        return repos[:max_repos]

    def languages(self, full_name: str) -> dict[str, int]:
        data = self.get(f"/repos/{full_name}/languages", allow_404=True)
        return data if isinstance(data, dict) else {}

    def tree(self, full_name: str, branch: str) -> tuple[list[dict[str, Any]], bool]:
        data = self.get(
            f"/repos/{full_name}/git/trees/{urllib.parse.quote(branch)}",
            params={"recursive": "1"},
            allow_404=True,
        )
        if not isinstance(data, dict):
            return [], False
        return data.get("tree", []) or [], bool(data.get("truncated"))

    def file_text(self, full_name: str, path: str, *, max_bytes: int = 400_000) -> str:
        """
        Contents API returns base64 for files under 1 MB. Larger files are
        skipped rather than pulled through the raw endpoint: a 1 MB source
        file is a bundle or a data blob, not something a person wrote, and
        including it would inflate every volume metric.
        """
        data = self.get(
            f"/repos/{full_name}/contents/{urllib.parse.quote(path)}",
            allow_404=True,
        )
        if not isinstance(data, dict):
            return ""
        if data.get("encoding") != "base64" or not data.get("content"):
            return ""
        if int(data.get("size") or 0) > max_bytes:
            return ""
        try:
            return base64.b64decode(data["content"]).decode("utf-8", "replace")
        except (ValueError, TypeError):
            return ""

    def commits_by_author(self, full_name: str, author: str,
                          max_pages: int = 1) -> list[dict[str, Any]]:
        """
        Commits GitHub attributes to one account, server-side filtered.

        The opposite choice from `commits()` below, and deliberately so. There
        the question is "whose commits are these?", which needs the raw log so
        that half-matching identities stay visible. Here the question is "what
        did this person write?", so commits GitHub cannot attribute to them are
        precisely the ones that must not be credited - filtering server-side is
        both correct and one call instead of a full log fetch.
        """
        try:
            return self.paginate(
                f"/repos/{full_name}/commits",
                params={"author": author, "per_page": 100},
                max_pages=max_pages,
            )
        except GitHubError:
            return []

    def commit_detail(self, full_name: str, sha: str) -> dict[str, Any] | None:
        """
        One commit with its per-file unified diff.

        The `files[].patch` field is what makes contribution mining possible:
        it is the only place GitHub's REST API tells you which LINES a person
        added, as opposed to which files exist now. Omitted for binary files
        and very large diffs, which the caller treats as "no attributable
        lines" rather than as an error.
        """
        return self.get(f"/repos/{full_name}/commits/{sha}", allow_404=True)

    def commits(self, full_name: str, max_pages: int = 1) -> list[dict[str, Any]]:
        """
        Recent commits, UNFILTERED by author.

        Deliberately not `?author=<username>`. Filtering server-side returns
        only what GitHub already attributes to the account, which makes the
        interesting cases invisible: a commit authored under a different email
        on a shared or misconfigured machine never appears, so it can be neither
        credited nor questioned. Fetching the raw log costs exactly the same one
        request and lets `miner.classify_authorship` sort them out locally.
        """
        try:
            return self.paginate(
                f"/repos/{full_name}/commits",
                params={"per_page": 100},
                max_pages=max_pages,
            )
        except GitHubError:
            # Empty repositories 409 here; that is not a failure worth
            # aborting the whole candidate for.
            return []
