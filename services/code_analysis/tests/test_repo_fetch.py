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
