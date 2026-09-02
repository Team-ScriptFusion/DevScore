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

# GitHub answers an already-exhausted quota (or secondary/abuse limiting) with
# 403 or 429 rather than a low X-RateLimit-Remaining header on a 200 — the
# header-based floor above never gets a chance to engage. Treat these the same
# way: stop, and return whatever was gathered so far.
RATE_LIMITED_STATUSES = (403, 429)

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
    if list_resp.status_code in RATE_LIMITED_STATUSES:
        # Quota already exhausted before we gathered anything — degrade to an
        # empty evidence set rather than failing the whole request.
        return {"repos": [], "rate_limited": True}
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
        if lang_resp.status_code in RATE_LIMITED_STATUSES:
            # Nothing gathered for this repo at all — return the earlier ones.
            return {"repos": repos, "rate_limited": True}
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
            if readme_resp.status_code in RATE_LIMITED_STATUSES:
                # Keep this repo's already-fetched languages, drop the README,
                # and stop before the next repo.
                rate_limited = True
            else:
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
