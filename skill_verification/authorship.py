"""
Three-way authorship classification (Section 5.1's real-run finding).

The spec never addressed authorship at all — Phase 0/1 treated every commit
in a student's repo list as if it were automatically theirs. The real run
found that's wrong even for a student's OWN repos: DevScore had commits with
a teammate's name paired with the student's email and vice versa (a shared,
misconfigured git setup). A naive "name OR email matches" rule inflated
authorship from 27% to 51% on that repo — nearly double, and wrong.

Rule: classify commits by whether BOTH the name and email plausibly belong
to the student's known identities, not either alone.

  mine      - name AND email both match a known identity for this student
  disputed  - exactly one matches (ambiguous — could be misattributed)
  other     - neither matches (a teammate's commit)

`known_identities` should be seeded from every email/name pair the student
has EVER committed under, not just their current GitHub profile email — the
real run found 4 different identities for one student; matching only the
profile email found 11 of 402 commits.
"""

from __future__ import annotations

from dataclasses import dataclass

from models import AuthorshipClass, CommitAuthor, RepoEvidence


@dataclass
class Identity:
    name: str
    email: str


def infer_identities(all_repos: list[RepoEvidence], github_username: str,
                      known_emails: list[str] | None = None) -> list[Identity]:
    """Seed the student's identity set from their own commit history rather
    than trusting a single profile email. Heuristic: any (name, email) pair
    that appears as an author in a repo where this is the student's own
    account context, weighted toward the most frequent pairs. In production,
    seed `known_emails` from every email the student's OAuth/account record
    has ever shown (signup email, GitHub-verified emails) — that is a much
    stronger signal than frequency alone and should be checked first."""
    from collections import Counter
    counts: Counter[tuple[str, str]] = Counter()
    for repo in all_repos:
        for author in repo.commit_authors:
            counts[(author.name, author.email)] += 1

    known_emails = {e.lower() for e in (known_emails or [])}
    identities = []
    for (name, email), _ in counts.most_common():
        if known_emails and email.lower() not in known_emails:
            continue
        identities.append(Identity(name=name, email=email))

    if not identities:
        # Nothing seeded from known_emails (or none supplied) — fall back to
        # every identity that ever committed to the repo the account claims
        # to own. This is weaker and should be flagged for review, not
        # silently trusted the way a single profile-email match would be.
        identities = [Identity(name=n, email=e) for (n, e) in counts]
    return identities


def classify_commit(author: CommitAuthor, identities: list[Identity]) -> AuthorshipClass:
    name_matches = any(author.name == i.name for i in identities)
    email_matches = any(author.email.lower() == i.email.lower() for i in identities)
    if name_matches and email_matches:
        return AuthorshipClass.MINE
    if name_matches or email_matches:
        return AuthorshipClass.DISPUTED
    return AuthorshipClass.OTHER


def classify_repo_authorship(repo: RepoEvidence, identities: list[Identity]) -> dict[AuthorshipClass, int]:
    counts = {AuthorshipClass.MINE: 0, AuthorshipClass.DISPUTED: 0, AuthorshipClass.OTHER: 0}
    for author in repo.commit_authors:
        counts[classify_commit(author, identities)] += 1
    repo.authorship = counts
    return counts


def authorship_share(repo: RepoEvidence) -> float:
    """Mine / (mine + other) — disputed commits are EXCLUDED from the
    denominator entirely (Section 5.1), not counted as a partial credit or
    silently folded into either bucket."""
    counted = repo.authorship.get(AuthorshipClass.MINE, 0) + repo.authorship.get(AuthorshipClass.OTHER, 0)
    if counted == 0:
        return 0.0
    return repo.authorship.get(AuthorshipClass.MINE, 0) / counted
