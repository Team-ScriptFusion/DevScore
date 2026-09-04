"""
GitHub mining: turn a username into a bounded, relevance-targeted pool of
real source code.

The naive approach — download everything — is impossible inside the API
budget and wrong anyway. What matters is *targeted sampling*: if the resume
claims React, spend the budget on `.jsx`/`.tsx` files in repos that declare
`react`, not on the candidate's dotfiles repo.

Sampling policy, in order:

  REPO FILTER   Forks are not mined as though the candidate wrote them — a
                fork is one click, and its whole history belongs to the
                original author. But they are no longer discarded either:
                a fork the candidate actually committed to is mined in
                CONTRIBUTION MODE, where only the lines they personally added
                are read (see contributions.py). A fork they never touched
                still contributes nothing and costs one call to establish.
                Repos with zero language bytes (empty, or docs-only) are
                skipped.

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
from ..models import CommitAuthorship, GithubProfile, RepoEvidence, SourceFile
from .contributions import mine_contribution
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
# Commit authorship
# ---------------------------------------------------------------------------

def _normalise_person(value: str) -> str:
    """Fold a display name for comparison: lowercase, alphanumerics only."""
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def known_identities(username: str, display_name: str) -> tuple[set[str], set[str]]:
    """
    (name forms, email forms) that count as this candidate.

    GitHub's noreply addresses are included because they are what the web UI
    and most GitHub Desktop setups commit under, and a candidate whose whole
    history is web-edited would otherwise look like a stranger in their own
    repository.
    """
    names = {_normalise_person(username)}
    if display_name:
        names.add(_normalise_person(display_name))
        # "Anura Perera" -> also match a bare "anura"
        first = display_name.split()[0] if display_name.split() else ""
        if len(first) > 3:
            names.add(_normalise_person(first))
    names.discard("")

    emails = {
        f"{username.lower()}@users.noreply.github.com",
    }
    return names, emails


def classify_authorship(
    commits: list[dict],
    username: str,
    display_name: str = "",
) -> CommitAuthorship:
    """
    Sort a repository's commit log into mine / disputed / other.

    Two passes on purpose. The first learns which raw email addresses GitHub
    itself attributes to this account; the second uses that learned set to
    judge commits GitHub could NOT attribute (author object null, because the
    email is not registered on the account). Without the learning pass a
    candidate who commits from a personal address that is simply not added to
    their GitHub profile would have every such commit marked `other`.
    """
    result = CommitAuthorship()
    if not commits:
        return result

    names, emails = known_identities(username, display_name)
    login = username.lower()

    # Pass 1 — learn addresses GitHub has already linked to this account.
    for commit in commits:
        author = commit.get("author") or {}
        if (author.get("login") or "").lower() == login:
            email = ((commit.get("commit") or {}).get("author") or {}).get("email") or ""
            if email and "noreply" not in email:
                emails.add(email.lower())

    # Pass 2 — classify.
    disputed_names: set[str] = set()
    for commit in commits:
        author = commit.get("author") or {}
        meta = (commit.get("commit") or {}).get("author") or {}
        commit_login = (author.get("login") or "").lower()
        commit_name = meta.get("name") or ""
        commit_email = (meta.get("email") or "").lower()
        when = meta.get("date") or ""

        if commit_login == login:
            bucket = "mine"
        elif commit_login:
            bucket = "other"          # GitHub attributes it to someone else
        else:
            name_match = _normalise_person(commit_name) in names
            email_match = commit_email in emails
            if name_match and email_match:
                bucket = "mine"
            elif name_match or email_match:
                bucket = "disputed"
            else:
                bucket = "other"

        if bucket == "mine":
            result.mine += 1
            if when > result.last_mine:
                result.last_mine = when
        elif bucket == "disputed":
            result.disputed += 1
            if commit_name:
                disputed_names.add(f"{commit_name} <{commit_email or 'no email'}>")
        else:
            result.other += 1

    result.disputed_names = sorted(disputed_names)[:4]
    return result


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


def prerank_repos(repos: list[RepoEvidence], claimed: list[str]) -> list[RepoEvidence]:
    """
    Order repositories using ONLY what the repo-list response already gave us.

    This runs before any language call, so it cannot look at language bytes —
    that is the whole point. It ranks on size, recency, stars and whether the
    name or description mentions something the CV claims, which is enough to
    put the repositories worth paying for at the top.
    """
    claimed_tokens = {c.lower() for c in claimed}
    for skill_name in list(claimed_tokens):
        skill = ontology.get(skill_name) if hasattr(ontology, "get") else None
        if skill:
            claimed_tokens.update(a.lower() for a in skill.all_aliases)

    def score(repo: RepoEvidence) -> float:
        haystack = f"{repo.name} {repo.description}".lower().replace("-", " ").replace("_", " ")
        mentions = sum(1 for token in claimed_tokens if token and token in haystack)
        size_signal = min(repo.size_kb / 1500.0, 1.0)
        recency_signal = max(0.0, 1.0 - months_since(repo.pushed_at) / 36.0)
        star_signal = min(repo.stars / 20.0, 0.5)
        return min(mentions, 4) * 0.5 + size_signal + recency_signal + star_signal

    return sorted(repos, key=score, reverse=True)


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
    max_repos_languages: int = 18,
    max_repos_deep: int = 12,
    files_per_repo: int = 10,
    max_files_total: int = 70,
    include_forks: bool = True,
    max_forks: int = 6,
    fork_commits: int = 8,
    call_budget: int | None = None,
) -> GithubProfile:
    client = client or GitHubClient()
    profile = GithubProfile(username=username)

    # Per-candidate spend cap.
    #
    # The disk cache makes RE-runs free, but it does nothing for the first pass,
    # and a 40-candidate cohort against a fresh 5,000/hour budget is exactly
    # when this matters. Without a cap the run is unplannable: early candidates
    # mine deeply, the budget runs out, and everyone after them is scored on
    # less evidence than everyone before — a systematic bias in favour of
    # whoever happens to sort first.
    #
    # With a cap, every candidate gets the same allowance and the shortfall is
    # visible instead of silent. Exceeding it stops further deep mining; it
    # never abandons what has already been gathered.
    start_calls = client.calls

    def budget_spent() -> bool:
        return call_budget is not None and (client.calls - start_calls) >= call_budget

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
    forks: list[RepoEvidence] = []
    for raw in raw_repos:
        if raw.get("archived") and (raw.get("size") or 0) == 0:
            continue
        entry = RepoEvidence(
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
        )
        if entry.is_fork:
            # Held back from the owned-repo pipeline entirely. A fork never
            # contributes language share, dependency manifests or whole files,
            # because none of that is the candidate's work.
            entry.evidence_mode = "contributions"
            forks.append(entry)
        else:
            shallow.append(entry)

    profile.forks_seen = len(forks)

    # Language stats cost ONE CALL PER REPOSITORY, and a student with 40 repos
    # therefore spent 40 calls before any evidence was read — the single largest
    # line in the per-candidate budget, most of it on repos that would never be
    # mined deeply anyway.
    #
    # So repositories are pre-ranked on the data the repo LIST already returned
    # (size, recency, stars, and whether the name or description mentions
    # anything the CV claims), and only the top `max_repos_languages` get a
    # language call. Breadth still sees plenty; the tail that contributed one
    # ambient hit at best no longer costs a request each.
    for repo in prerank_repos(shallow, claimed_skills)[:max_repos_languages]:
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
    repos_deep_mined = 0
    for repo in ranked[:max_repos_deep]:
        if budget_spent():
            profile.error = (
                f"per-candidate API budget of {call_budget} calls reached after "
                f"{repos_deep_mined} repositories; the rest were not opened"
            )
            break
        repos_deep_mined += 1
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

        # Authorship + recency, straight from the commit log. The log is
        # fetched unfiltered and sorted locally so that commits GitHub cannot
        # attribute (unregistered email) are visible as `disputed` rather than
        # invisible — same one request either way.
        commits = client.commits(repo.full_name)
        repo.authorship = classify_authorship(commits, username, profile.name)
        repo.commits_by_owner = repo.authorship.mine
        repo.last_owner_commit = repo.authorship.last_mine

    # ---- forks: contribution mode ---------------------------------------
    #
    # Ranked by recency and size so the fork most likely to hold real work is
    # examined first. Each costs one call to find out whether the candidate
    # ever committed; only those that did cost anything more.
    if include_forks and forks:
        for repo in prerank_repos(forks, claimed_skills)[:max_forks]:
            if budget_spent():
                break
            try:
                contribution = mine_contribution(
                    client, repo.full_name, username,
                    classify_language=classify,
                    max_commits=fork_commits,
                )
            except RateLimitExhausted:
                profile.error = "rate limit reached during fork contribution mining"
                break
            except GitHubError:
                continue

            repo.commits_by_owner = contribution.commits_by_candidate
            repo.last_owner_commit = contribution.last_commit
            repo.authorship = CommitAuthorship(
                mine=contribution.commits_by_candidate,
                last_mine=contribution.last_commit,
            )
            if not contribution.files:
                continue          # forked and never meaningfully touched

            repo.contributed_lines = contribution.total_added_lines
            for contributed in contribution.files:
                repo.fetched_files.append(SourceFile(
                    repo=repo.name,
                    path=contributed.path,
                    language=contributed.language,
                    size_bytes=len(contributed.text.encode("utf-8")),
                    text=contributed.text,
                    is_fragment=True,
                ))
            profile.forks_contributed_to += 1
            ranked.append(repo)

    profile.repos = ranked
    profile.repos_deep_mined = repos_deep_mined
    profile.calls_spent = client.calls - start_calls
    profile.api_calls = client.calls
    profile.rate_limit_remaining = client.rate_remaining
    return profile
