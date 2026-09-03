from datetime import datetime

from authorship import Identity, authorship_share, classify_commit, classify_repo_authorship
from models import AuthorshipClass, CommitAuthor, RepoEvidence


def _author(name, email):
    return CommitAuthor(name=name, email=email, committed_at=datetime(2026, 1, 1))


def test_both_match_is_mine():
    identities = [Identity(name="Sandun Madhushan", email="sandun@example.com")]
    result = classify_commit(_author("Sandun Madhushan", "sandun@example.com"), identities)
    assert result == AuthorshipClass.MINE


def test_neither_matches_is_other():
    identities = [Identity(name="Sandun Madhushan", email="sandun@example.com")]
    result = classify_commit(_author("Teammate Name", "teammate@example.com"), identities)
    assert result == AuthorshipClass.OTHER


def test_name_matches_but_email_does_not_is_disputed():
    # Regression test for the real-run finding: a teammate's name paired
    # with the student's email (shared/misconfigured machine) must NOT be
    # silently counted as "mine" — that's exactly the bug that inflated
    # authorship from 27% to 51% on a real repo.
    identities = [Identity(name="Sandun Madhushan", email="sandun@example.com")]
    result = classify_commit(_author("Chanuka Lakshan", "sandun@example.com"), identities)
    assert result == AuthorshipClass.DISPUTED


def test_email_matches_but_name_does_not_is_disputed():
    identities = [Identity(name="Sandun Madhushan", email="sandun@example.com")]
    result = classify_commit(_author("Sandun Madhushan", "teammate@example.com"), identities)
    assert result == AuthorshipClass.DISPUTED


def test_disputed_commits_excluded_from_authorship_share():
    repo = RepoEvidence(
        repo_name="devscore-like", is_fork=False, description="", languages={}, manifests={},
        readme_text="", commit_count=3, last_commit_at=None,
        commit_authors=[
            _author("Sandun Madhushan", "sandun@example.com"),   # mine
            _author("Chanuka Lakshan", "sandun@example.com"),    # disputed
            _author("Chanuka Lakshan", "chanuka@example.com"),   # other
        ],
    )
    identities = [Identity(name="Sandun Madhushan", email="sandun@example.com")]
    classify_repo_authorship(repo, identities)
    assert repo.authorship[AuthorshipClass.MINE] == 1
    assert repo.authorship[AuthorshipClass.DISPUTED] == 1
    assert repo.authorship[AuthorshipClass.OTHER] == 1
    # share = mine / (mine + other), disputed excluded entirely -> 1/2, not 1/3 or 2/3
    assert authorship_share(repo) == 0.5
