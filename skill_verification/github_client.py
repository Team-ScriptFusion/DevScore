"""
Phase 0 — fetch raw GitHub evidence WITHOUT cloning any repository.

Why no clone (deviation from the spec's original suggestion, kept from the
real-run findings): the real run's local, extension-based language fallback
is what produced the false positives (Flutter's generated desktop
scaffolding counted as C++; launcher-icon PNGs counted as "Mobile App
Development"). GitHub's own `languages` endpoint already runs Linguist
server-side and excludes generated/vendored files — using it directly is
*more* correct than a local heuristic, not just cheaper.

Why GraphQL instead of one REST call per endpoint: the spec's REST plan
(GET /user/repos, then per-repo languages/readme/commits) costs ~250-300
requests per candidate for a student with several active repos. A single
GraphQT query can ask for repos + languages + README + manifest files +
paginated commit authors in one HTTP round trip, which is what actually
brings the per-candidate cost down (the real run's ~80-request number came
from git clone; this brings it lower still, with no disk I/O and no cloning
step to fail/timeout on a large repo).

Only public data is ever requested — GraphQL's `viewerCanAdminister` /
private-repo fields are never selected, and `isPrivate: false` is asserted
client-side as a second check on every repo returned.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

from models import CommitAuthor, RepoEvidence

GRAPHQL_URL = "https://api.github.com/graphql"

# Manifest files we look for, aliased individually so ONE query returns all
# of them per repo. Keep this list small and add to it as synonyms.py grows
# — every extra alias costs a small, fixed amount of GraphQL "node cost",
# not an extra HTTP round trip.
MANIFEST_FILES = {
    "package_json": "package.json",
    "requirements_txt": "requirements.txt",
    "pubspec_yaml": "pubspec.yaml",
    "pom_xml": "pom.xml",
    "build_gradle": "build.gradle",
    "go_mod": "go.mod",
    "cargo_toml": "Cargo.toml",
    "gemfile": "Gemfile",
}

REPOS_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(first: 30, after: $after, isFork: false, privacy: PUBLIC,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        isFork
        isPrivate
        description
        pushedAt
        defaultBranchRef {
          target {
            ... on Commit {
              history(first: 100) {
                totalCount
                pageInfo { hasNextPage endCursor }
                nodes { committedDate author { name email } }
              }
            }
          }
        }
        languages(first: 15, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
        readme: object(expression: "HEAD:README.md") { ... on Blob { text } }
        readmeAlt: object(expression: "HEAD:readme.md") { ... on Blob { text } }
        %(manifests)s
      }
    }
  }
  rateLimit { remaining resetAt cost }
}
"""


def _manifest_fragment() -> str:
    frags = []
    for alias, path in MANIFEST_FILES.items():
        frags.append(f'{alias}: object(expression: "HEAD:{path}") {{ ... on Blob {{ text }} }}')
    return "\n        ".join(frags)


class GitHubEvidenceClient:
    def __init__(self, token: str, min_remaining: int = 200):
        if not token:
            raise ValueError(
                "A token is required even for public data: unauthenticated GraphQL "
                "isn't supported, and unauthenticated REST is capped at 60 req/hour "
                "which won't clear more than one or two candidates."
            )
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        })
        self.min_remaining = min_remaining

    def _post(self, query: str, variables: dict) -> dict:
        resp = self.session.post(GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=30)
        if resp.status_code == 401:
            raise RuntimeError("GitHub token rejected (401) — check it hasn't expired or been revoked.")
        resp.raise_for_status()
        payload = resp.json()
        if "errors" in payload:
            raise RuntimeError(f"GitHub GraphQL error: {payload['errors']}")
        remaining = payload["data"]["rateLimit"]["remaining"]
        if remaining < self.min_remaining:
            reset_at = payload["data"]["rateLimit"]["resetAt"]
            wait_hint = (
                f"{remaining} points left, resets at {reset_at} — "
                f"backing off rather than risking a hard stop mid-batch."
            )
            print(f"[github_client] rate limit low: {wait_hint}")
            time.sleep(2)
        return payload["data"]

    def fetch_all_public_repos(self, username: str) -> list[RepoEvidence]:
        """One query per page of up to 30 repos (most candidates fit in one
        page). Everything Phase 0 needs comes back in this single call:
        no separate languages/readme/commits requests, no clone."""
        query = REPOS_QUERY % {"manifests": _manifest_fragment()}
        results: list[RepoEvidence] = []
        after = None
        while True:
            data = self._post(query, {"login": username, "after": after})
            user = data.get("user")
            if user is None:
                raise RuntimeError(f"GitHub user '{username}' not found (deleted, renamed, or typo).")
            repos = user["repositories"]
            for node in repos["nodes"]:
                results.append(self._parse_repo_node(node))
            if not repos["pageInfo"]["hasNextPage"]:
                break
            after = repos["pageInfo"]["endCursor"]
        return results

    def _parse_repo_node(self, node: dict) -> RepoEvidence:
        # Defense-in-depth: even though the query filters privacy: PUBLIC,
        # never trust a single filter for an ethical-clearance constraint.
        if node.get("isPrivate"):
            raise RuntimeError(f"Refusing to process private repo '{node['name']}' — public repos only.")

        languages = {edge["node"]["name"]: edge["size"] for edge in node["languages"]["edges"]}

        manifests = {}
        for alias, path in MANIFEST_FILES.items():
            blob = node.get(alias)
            if blob and blob.get("text"):
                manifests[path] = blob["text"]

        readme_text = ""
        if node.get("readme") and node["readme"].get("text"):
            readme_text = node["readme"]["text"]
        elif node.get("readmeAlt") and node["readmeAlt"].get("text"):
            readme_text = node["readmeAlt"]["text"]

        commit_authors: list[CommitAuthor] = []
        last_commit_at: Optional[datetime] = None
        commit_count = 0
        history_cursor = None
        history_has_more = False
        branch = node.get("defaultBranchRef")
        if branch and branch.get("target"):
            history = branch["target"]["history"]
            commit_count = history["totalCount"]
            history_has_more = history["pageInfo"]["hasNextPage"]
            history_cursor = history["pageInfo"]["endCursor"]
            for c in history["nodes"]:
                author = c.get("author") or {}
                if not author.get("email"):
                    continue
                commit_authors.append(CommitAuthor(
                    name=author.get("name") or "",
                    email=author["email"],
                    committed_at=_parse_ts(c["committedDate"]),
                ))
            if history["nodes"]:
                last_commit_at = _parse_ts(history["nodes"][0]["committedDate"])

        evidence = RepoEvidence(
            repo_name=node["name"],
            is_fork=node["isFork"],
            description=node.get("description"),
            languages=languages,
            manifests=manifests,
            readme_text=readme_text,
            commit_count=commit_count,
            last_commit_at=last_commit_at,
            commit_authors=commit_authors,
        )
        # Stashed for fill_full_commit_history's continuation cursor — not
        # part of the persisted schema, just plumbing between these two calls.
        evidence._history_cursor = history_cursor
        evidence._history_has_more = history_has_more
        return evidence


def _parse_ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


REPO_HISTORY_PAGE_QUERY = """
query($login: String!, $repo: String!, $after: String) {
  repository(owner: $login, name: $repo) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $after) {
            pageInfo { hasNextPage endCursor }
            nodes { committedDate author { name email } }
          }
        }
      }
    }
  }
  rateLimit { remaining resetAt cost }
}
"""


def fill_full_commit_history(client: "GitHubEvidenceClient", username: str,
                              evidence: RepoEvidence, max_commits: int = 500) -> None:
    """The main query's `history(first: 100)` only returns the newest 100
    commits per repo. For authorship classification (mine/disputed/other)
    that's fine for most student repos, but task-manager alone in the real
    run had 146 — undercounting here would misclassify a student's own
    commit share. Page in additional commits up to `max_commits` (a cap,
    not a promise of completeness — a repo with thousands of commits from
    a large open-source fork is out of scope for this ethical-clearance
    project anyway)."""
    if not getattr(evidence, "_history_has_more", False):
        return
    after = getattr(evidence, "_history_cursor", None)
    while after and len(evidence.commit_authors) < min(evidence.commit_count, max_commits):
        data = client._post(REPO_HISTORY_PAGE_QUERY, {
            "login": username, "repo": evidence.repo_name, "after": after,
        })
        repo = data.get("repository")
        if not repo or not repo.get("defaultBranchRef"):
            break
        history = repo["defaultBranchRef"]["target"]["history"]
        for c in history["nodes"]:
            author = c.get("author") or {}
            if not author.get("email"):
                continue
            evidence.commit_authors.append(CommitAuthor(
                name=author.get("name") or "", email=author["email"],
                committed_at=_parse_ts(c["committedDate"]),
            ))
        if not history["pageInfo"]["hasNextPage"]:
            break
        after = history["pageInfo"]["endCursor"]
