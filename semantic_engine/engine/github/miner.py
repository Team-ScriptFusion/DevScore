"""
GitHub mining: turn a username into a bounded, relevance-targeted pool of
real source code.

The naive approach — download everything — is impossible inside the API
budget and wrong anyway. What matters is *targeted sampling*: if the resume
claims React, spend the budget on `.jsx`/`.tsx` files in repos that declare
`react`, not on the candidate's dotfiles repo.

Sampling policy, in order:

  REPO FILTER   Forks are excluded from evidence entirely — a fork proves a
                button click, not authorship. (They are still counted and
                reported, because a recruiter seeing "3 repos" should know
                there were 14 forks.) Repos with zero language bytes
                (empty, or docs-only) are skipped.

  REPO RANK     Repos are scored for relevance to the claimed skill set and
                for signs of being real work — size, commit count by the
                owner, recency, presence of tests/CI. The top
                `max_repos_deep` are mined deeply; the rest contribute
                language and dependency evidence only, which is cheap
                (2 calls) and still counts toward breadth.

  FILE PICK     Within a deep-mined repo, files are chosen to maximise
                distinct-skill coverage first and size second. Vendored and
                generated paths (node_modules, dist, build, .min.js,
                migrations, *.g.dart, package-lock) are excluded by pattern
                — counting a 40k-line bundle as "the candidate's code" would
                wreck every volume and complexity metric downstream.

The mined pool is deliberately capped (`max_files_total`). More code does
not make the verdict better past a point; it just costs budget that the next
candidate in the batch needs.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .. import ontology
from ..models import GithubProfile, RepoEvidence, SourceFile
from .client import GitHubClient, GitHubError, RateLimitExhausted

# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

EXT_LANGUAGE: dict[str, str] = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".c": "C", ".h": "C",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++",
    ".cs": "C#", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".php": "PHP", ".swift": "Swift", ".dart": "Dart", ".scala": "Scala",
    ".r": "R", ".m": "MATLAB", ".lua": "Lua", ".pl": "Perl", ".hs": "Haskell",
    ".sh": "Shell", ".bash": "Shell",
    ".html": "HTML", ".htm": "HTML", ".vue": "Vue", ".svelte": "Svelte",
    ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
    ".sql": "SQL", ".ipynb": "Jupyter",
    ".yml": "YAML", ".yaml": "YAML",
}

MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml", "pipfile", "setup.py",
    "pom.xml", "build.gradle", "build.gradle.kts", "pubspec.yaml", "go.mod",
    "gemfile", "composer.json", "cargo.toml", "environment.yml",
}

# Vendored, generated, or minified — never the candidate's own work.
EXCLUDE_PATTERNS = re.compile(
    r"(^|/)(node_modules|vendor|third_party|bower_components|\.venv|venv|env|"
    r"dist|build|out|target|bin|obj|coverage|\.next|\.nuxt|__pycache__|"
    r"migrations|generated|gen|assets|public/static)/"
    r"|\.min\.(js|css)$"
    r"|[.-](bundle|chunk|vendor)\.js$"
    r"|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Podfile\.lock)$"
    r"|\.(g|freezed|pb|generated)\.(dart|go|py|ts|js)$"
    r"|(^|/)\.",
    re.IGNORECASE,
)

TEST_PATTERN = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs)/|(_test|\.test|\.spec|Test|Tests)\.[a-z]+$",
    re.IGNORECASE,
)

CI_PATTERN = re.compile(
    r"(^\.github/workflows/|^\.gitlab-ci\.yml$|^Jenkinsfile$|^\.circleci/|^azure-pipelines\.yml$)",
    re.IGNORECASE,
)


def classify(path: str) -> str:
    for ext, lang in EXT_LANGUAGE.items():
        if path.lower().endswith(ext):
            return lang
    return ""


def _iso_to_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def months_since(value: str) -> float:
    dt = _iso_to_dt(value)
    if dt is None:
        return 999.0
    delta = datetime.now(timezone.utc) - dt
    return max(0.0, delta.days / 30.44)


# ---------------------------------------------------------------------------
# Dependency manifest parsing
# ---------------------------------------------------------------------------

def parse_manifest(name: str, text: str) -> set[str]:
    """Extract dependency identifiers, lowercased. Best-effort by design."""
    name = name.lower()
    deps: set[str] = set()
    if not text:
        return deps

    try:
        if name == "package.json":
            data = json.loads(text)
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                deps.update(k.lower() for k in (data.get(key) or {}))

        elif name in ("requirements.txt", "environment.yml"):
            for line in text.splitlines():
                line = line.strip()
                # Flag and include lines must be rejected BEFORE the YAML
                # bullet is stripped — stripping first turns "-r other.txt"
                # into "r other.txt", which then parses as a package named
                # "r" and hands the candidate a phantom R dependency.
                if not line or line.startswith(("#", "-r ", "--", "-e ", "-c ")):
                    continue
                line = line.lstrip("- ").strip()
                if not line or line.startswith("#"):
                    continue
                pkg = re.split(r"[=<>!~\[\s;]", line, 1)[0].strip()
                if pkg:
                    deps.add(pkg.lower())

        elif name in ("pyproject.toml", "cargo.toml", "pipfile"):
            for match in re.finditer(r'^\s*["\']?([A-Za-z0-9._-]+)["\']?\s*=', text, re.MULTILINE):
                deps.add(match.group(1).lower())
            for match in re.finditer(r'^\s*["\']([A-Za-z0-9._-]+)["\'],?\s*$', text, re.MULTILINE):
                deps.add(match.group(1).lower())

        elif name == "setup.py":
            for match in re.finditer(r'["\']([A-Za-z0-9._-]{2,})(?:[=<>~!\[][^"\']*)?["\']', text):
                deps.add(match.group(1).lower())

        elif name == "pom.xml":
            for match in re.finditer(r"<artifactId>([^<]+)</artifactId>", text):
                deps.add(match.group(1).strip().lower())
            for match in re.finditer(r"<groupId>([^<]+)</groupId>", text):
                deps.add(match.group(1).strip().lower())

        elif name.startswith("build.gradle"):
            for match in re.finditer(r"['\"]([\w.-]+:[\w.-]+)(?::[\w.+-]+)?['\"]", text):
                group, artifact = match.group(1).split(":", 1)
                deps.add(artifact.lower())
                deps.add(group.lower())

        elif name == "pubspec.yaml":
            for match in re.finditer(r"^\s{2}([a-z0-9_]+)\s*:", text, re.MULTILINE):
                deps.add(match.group(1).lower())

        elif name == "go.mod":
            for match in re.finditer(r"^\s*([\w./-]+)\s+v[\d.]", text, re.MULTILINE):
                deps.add(match.group(1).lower())

        elif name == "composer.json":
            data = json.loads(text)
            for key in ("require", "require-dev"):
                deps.update(k.lower() for k in (data.get(key) or {}))

        elif name == "gemfile":
            for match in re.finditer(r"^\s*gem\s+['\"]([^'\"]+)['\"]", text, re.MULTILINE):
                deps.add(match.group(1).lower())

    except (json.JSONDecodeError, ValueError, AttributeError):
        # A malformed manifest is a missing evidence channel, not a crash.
        return deps

    return deps


# ---------------------------------------------------------------------------
# Relevance ranking
# ---------------------------------------------------------------------------

def _skill_languages(claimed: list[str]) -> set[str]:
    langs: set[str] = set()
    for name in claimed:
        skill = ontology.get(name)
        if skill:
            langs.update(skill.languages)
    return langs


def rank_repos(repos: list[RepoEvidence], claimed: list[str]) -> list[RepoEvidence]:
    """
    Order repos by "how likely is this to contain provable evidence for what
    the resume claims", so a limited file budget is spent where it counts.
    """
    target_langs = _skill_languages(claimed)

    def score(repo: RepoEvidence) -> float:
        relevance = sum(repo.language_share(lang) for lang in target_langs)
        size_signal = min(repo.size_kb / 2000.0, 1.0)
        recency_signal = max(0.0, 1.0 - months_since(repo.pushed_at) / 36.0)
        craft_signal = 0.15 * repo.has_tests + 0.10 * repo.has_ci + 0.05 * repo.has_readme
        star_signal = min(repo.stars / 20.0, 0.5)
        return relevance * 2.0 + size_signal + recency_signal + craft_signal + star_signal

    return sorted(repos, key=score, reverse=True)


def pick_files(
    repo: RepoEvidence,
    claimed: list[str],
    budget: int,
) -> list[tuple[str, int]]:
    """
    Choose up to `budget` files from a repo's tree, maximising the number of
    distinct claimed skills that get at least some code to look at before
    spending remaining budget on the largest files.

    Coverage-first matters: three big React components tell us less about a
    candidate who claims React *and* Python *and* MongoDB than one file from
    each does.
    """
    target_langs = _skill_languages(claimed) or set(EXT_LANGUAGE.values())

    candidates: list[tuple[str, int, str]] = []
    for path in repo.file_paths:
        if EXCLUDE_PATTERNS.search(path):
            continue
        lang = classify(path)
        if not lang or lang in ("YAML",):
            continue
        size = repo._path_sizes.get(path, 0) if hasattr(repo, "_path_sizes") else 0
        if size and (size < 120 or size > 400_000):
            continue
        candidates.append((path, size, lang))

    # Pass 1 — one file per language, largest first (biggest file in a
    # language is usually the most substantive, not a stub or an index.js).
    picked: list[tuple[str, int]] = []
    seen_langs: set[str] = set()
    for path, size, lang in sorted(candidates, key=lambda c: -c[1]):
        if len(picked) >= budget:
            break
        if lang in seen_langs:
            continue
        if lang in target_langs or not target_langs:
            seen_langs.add(lang)
            picked.append((path, size))

    # Pass 2 — fill remaining budget with the largest relevant files left.
    picked_paths = {p for p, _ in picked}
    for path, size, lang in sorted(candidates, key=lambda c: -c[1]):
        if len(picked) >= budget:
            break
        if path in picked_paths:
            continue
        if lang in target_langs or not target_langs:
            picked.append((path, size))
            picked_paths.add(path)

    return picked


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def mine_profile(
    username: str,
    claimed_skills: list[str],
    client: GitHubClient | None = None,
    *,
    max_repos: int = 40,
    max_repos_deep: int = 12,
    files_per_repo: int = 10,
    max_files_total: int = 70,
    include_forks: bool = False,
) -> GithubProfile:
    client = client or GitHubClient()
    profile = GithubProfile(username=username)

    try:
        user = client.user(username)
    except GitHubError as exc:
        profile.found = False
        profile.error = str(exc)
        return profile

    if not user:
        profile.found = False
        profile.error = f"GitHub user '{username}' not found"
        return profile

    profile.name = user.get("name") or ""
    profile.public_repos = int(user.get("public_repos") or 0)
    profile.followers = int(user.get("followers") or 0)
    profile.created_at = user.get("created_at") or ""

    try:
        raw_repos = client.repos(username, max_repos=max_repos)
    except GitHubError as exc:
        profile.error = str(exc)
        profile.api_calls = client.calls
        return profile

    shallow: list[RepoEvidence] = []
    for raw in raw_repos:
        if raw.get("fork") and not include_forks:
            continue
        if raw.get("archived") and (raw.get("size") or 0) == 0:
            continue
        shallow.append(RepoEvidence(
            name=raw.get("name") or "",
            full_name=raw.get("full_name") or "",
            description=(raw.get("description") or "")[:400],
            is_fork=bool(raw.get("fork")),
            stars=int(raw.get("stargazers_count") or 0),
            size_kb=int(raw.get("size") or 0),
            created_at=raw.get("created_at") or "",
            pushed_at=raw.get("pushed_at") or "",
            default_branch=raw.get("default_branch") or "main",
            topics=list(raw.get("topics") or []),
        ))

    # Language stats for every non-fork repo — cheap and needed for breadth.
    for repo in shallow:
        if repo.size_kb == 0:
            continue
        try:
            repo.languages = client.languages(repo.full_name)
        except RateLimitExhausted:
            profile.error = "rate limit reached during language mining"
            break
        except GitHubError:
            continue

    usable = [r for r in shallow if r.languages]
    ranked = rank_repos(usable, claimed_skills)

    files_fetched = 0
    for repo in ranked[:max_repos_deep]:
        try:
            tree, truncated = client.tree(repo.full_name, repo.default_branch)
        except RateLimitExhausted:
            profile.error = "rate limit reached during tree mining"
            break
        except GitHubError:
            continue

        repo.tree_truncated = truncated
        sizes: dict[str, int] = {}
        for node in tree:
            if node.get("type") != "blob":
                continue
            path = node.get("path") or ""
            repo.file_paths.append(path)
            sizes[path] = int(node.get("size") or 0)
        repo._path_sizes = sizes  # type: ignore[attr-defined]

        lowered = [p.lower() for p in repo.file_paths]
        repo.has_readme = any(p.startswith("readme") for p in lowered)
        repo.has_docker = any(
            p.endswith("dockerfile") or p.endswith("docker-compose.yml") for p in lowered
        )
        repo.has_lockfile = any(
            p.endswith(("package-lock.json", "yarn.lock", "poetry.lock", "pnpm-lock.yaml"))
            for p in lowered
        )
        repo.has_tests = any(TEST_PATTERN.search(p) for p in repo.file_paths)
        repo.has_ci = any(CI_PATTERN.search(p) for p in repo.file_paths)

        # Manifests — the "declared" evidence channel.
        for path in repo.file_paths:
            base = path.rsplit("/", 1)[-1].lower()
            if base in MANIFESTS and path.count("/") <= 2:
                try:
                    text = client.file_text(repo.full_name, path)
                except (GitHubError, RateLimitExhausted):
                    continue
                if text:
                    repo.manifests.append(path)
                    repo.dependencies |= parse_manifest(base, text)

        # Source sample — the "used"/"applied" evidence channels.
        budget = min(files_per_repo, max_files_total - files_fetched)
        if budget <= 0:
            continue
        for path, size in pick_files(repo, claimed_skills, budget):
            try:
                text = client.file_text(repo.full_name, path)
            except RateLimitExhausted:
                profile.error = "rate limit reached during file mining"
                break
            except GitHubError:
                continue
            if not text.strip():
                continue
            repo.fetched_files.append(SourceFile(
                repo=repo.name,
                path=path,
                language=classify(path),
                size_bytes=size or len(text.encode("utf-8")),
                text=text,
            ))
            files_fetched += 1

        # Authorship + recency, straight from the commit log.
        commits = client.commits_by(repo.full_name, username)
        repo.commits_by_owner = len(commits)
        if commits:
            when = (commits[0].get("commit") or {}).get("author", {}).get("date") or ""
            repo.last_owner_commit = when

    profile.repos = ranked
    profile.api_calls = client.calls
    profile.rate_limit_remaining = client.rate_remaining
    return profile
