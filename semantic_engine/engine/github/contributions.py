"""
Contribution mining — what the candidate personally wrote inside a repository
they do not own outright.

The problem this solves
-----------------------
Forking is one click. A forked repository sits in the candidate's account
looking exactly like their own work, and its entire history — every file, every
line, every language byte — belongs to whoever wrote the original. Treating a
fork as evidence would credit a button press as engineering, so the miner has
always excluded forks wholesale.

But wholesale exclusion is wrong in the other direction. Someone who forks a
project and then lands 40 commits of real feature work has genuinely written
code, and refusing to look means their strongest evidence is invisible while a
classmate who pushed a tutorial to a fresh repo scores higher.

So: fork repositories are now mined, but ONLY for the lines the candidate
themselves added.

How
---
1. `GET /repos/{full}/commits?author={username}` — one call. Server-side
   filtering is correct *here*, unlike in authorship classification: the
   question is "what did they write", so commits GitHub cannot attribute to
   them are precisely the ones we must not credit.
2. If that returns nothing, the fork is a button click. Stop; spend nothing.
3. Otherwise fetch up to `max_commits` commit details, each of which carries a
   per-file unified diff, and keep the ADDED lines only.

What comes back is a set of fragments: the candidate's own lines, per file.

Why fragments, and what they can and cannot support
---------------------------------------------------
An added-lines fragment is not a parseable program. You cannot run an AST over
"the 40 lines this person added" and get a meaningful cyclomatic complexity —
it is not valid syntax on its own, and the surrounding structure it plugs into
was written by someone else.

So contributed code is deliberately a *weaker* class of evidence:

    marker / import channels   YES. A regex for `useState(` or `import torch`
                               works perfectly on a fragment, and a hit means
                               this person wrote that line. This is the
                               strongest possible proof of the skill.
    depth (volume)             YES, counted from contributed lines only.
    recency                    YES, from their own commit dates.
    complexity                 NO. Scoring the structure of a file the
                               candidate added twenty lines to would credit
                               them with the original author's architecture.
                               Fragments report `analyzed_with =
                               "contribution_fragment"` and are excluded from
                               the complexity aggregate by dispatch.py.
    craft (tests/CI)           NO. The repository's test suite and CI are the
                               upstream project's, not theirs.

A useful consequence falls out of this for free: because mastery requires a
complexity floor, and fragments contribute no complexity, fork contributions
alone can never promote a skill to `mastered`. They can prove a candidate
*writes* React; only their own repositories can show they can *structure* it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# A unified-diff hunk header: @@ -old,+new @@
_HUNK = re.compile(r"^@@ ")

# Paths that are never the candidate's engineering, even when they touched them.
_NOISE_PATH = re.compile(
    r"(^|/)(node_modules|vendor|dist|build|out|target|coverage|\.next|__pycache__)/"
    r"|\.(min|bundle)\.(js|css)$"
    r"|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock)$",
    re.IGNORECASE,
)

# Below this many added lines in a file, the contribution is a typo fix or a
# version bump rather than evidence of writing the technology.
MIN_ADDED_LINES = 8


@dataclass
class ContributedFile:
    """The lines one candidate added to one file, across their commits."""

    path: str
    language: str
    added_lines: int = 0
    # The added lines themselves, newline-joined. A fragment, not a program.
    text: str = ""
    commits: int = 0


@dataclass
class Contribution:
    """Everything one candidate personally added to one repository."""

    repo_full_name: str
    commits_examined: int = 0
    commits_by_candidate: int = 0
    files: list[ContributedFile] = field(default_factory=list)
    last_commit: str = ""
    truncated: bool = False

    @property
    def total_added_lines(self) -> int:
        return sum(f.added_lines for f in self.files)


def added_lines_from_patch(patch: str) -> list[str]:
    """
    Pull the added lines out of a unified diff.

    Lines beginning with a single '+' are additions; '+++' is the file header
    and must not be mistaken for one. Removed and context lines are dropped —
    deleting someone else's code is not writing your own.
    """
    out: list[str] = []
    for line in (patch or "").splitlines():
        if _HUNK.match(line) or line.startswith("+++"):
            continue
        if line.startswith("+"):
            out.append(line[1:])
    return out


def mine_contribution(
    client,
    full_name: str,
    username: str,
    *,
    classify_language,
    max_commits: int = 8,
) -> Contribution:
    """
    Collect the candidate's own added lines across a repository.

    `classify_language` is injected (it is `miner.classify`) so this module
    does not import the miner and can be tested with a stub.

    Cost: 1 call to list their commits, then at most `max_commits` calls for
    the per-commit diffs — and zero of the latter when they never committed,
    which is the common case for a fork.
    """
    contribution = Contribution(repo_full_name=full_name)

    try:
        commits = client.commits_by_author(full_name, username)
    except Exception:
        # A repository we cannot read the log of contributes nothing. Never a
        # reason to abandon the candidate.
        return contribution

    contribution.commits_by_candidate = len(commits)
    if not commits:
        return contribution                       # forked, never touched

    if len(commits) > max_commits:
        contribution.truncated = True

    by_path: dict[str, ContributedFile] = {}
    for commit in commits[:max_commits]:
        sha = commit.get("sha")
        if not sha:
            continue
        when = ((commit.get("commit") or {}).get("author") or {}).get("date") or ""
        if when > contribution.last_commit:
            contribution.last_commit = when

        try:
            detail = client.commit_detail(full_name, sha)
        except Exception:
            continue
        contribution.commits_examined += 1

        for entry in (detail or {}).get("files") or []:
            path = entry.get("filename") or ""
            if not path or _NOISE_PATH.search(path):
                continue
            language = classify_language(path)
            if not language or language == "YAML":
                continue

            # GitHub omits `patch` for binary files and very large diffs. When
            # it is missing we still know the file was touched, but we have no
            # lines to attribute, so it cannot become evidence.
            added = added_lines_from_patch(entry.get("patch") or "")
            if not added:
                continue

            record = by_path.get(path)
            if record is None:
                record = ContributedFile(path=path, language=language)
                by_path[path] = record
            record.added_lines += len(added)
            record.commits += 1
            record.text = (record.text + "\n" + "\n".join(added)).strip()

    contribution.files = [
        f for f in by_path.values() if f.added_lines >= MIN_ADDED_LINES
    ]
    return contribution
