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

    Ownership of the temp directory transfers to the caller only on the
    success path. If anything fails after mkdtemp — a corrupt or
    truncated tarball, a path-traversal member rejected by the 'data'
    filter (which can leave partially-extracted content behind), or an
    error while walking — this function deletes the directory itself
    before re-raising, since the caller never receives a path it could
    clean up.
    """
    tmp_dir = tempfile.mkdtemp(prefix="code_analysis_")
    try:
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
    except BaseException:
        # BaseException, not Exception: source code is never left on disk
        # after a failed analysis, including on KeyboardInterrupt/SystemExit.
        cleanup(tmp_dir)
        raise


def cleanup(tmp_dir: str) -> None:
    shutil.rmtree(tmp_dir, ignore_errors=True)
