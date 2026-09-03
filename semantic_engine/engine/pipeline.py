"""
End-to-end orchestration: PDF in, ReadinessReport out.

This is the only function the Node backend, the CLI and the batch runner all
share, so the ordering decisions live here rather than being repeated:

  1. Parse the resume FIRST. The claimed-skill set is what makes GitHub
     mining affordable — the miner uses it to rank repositories and pick
     files. Mining blind would cost several times the API budget and return
     mostly irrelevant code.

  2. An explicitly supplied GitHub username always overrides the one
     recovered from the PDF. A recruiter correcting a bad OCR read must win
     over the parser.

  3. Mining failure is not scoring failure. If GitHub is unreachable, rate
     limited, or the profile does not exist, the pipeline still produces a
     report — with every claim unverified, capacity 0, no integrity penalty,
     and a warning that says exactly that. Returning nothing would leave the
     dashboard with a blank cell and no explanation, which is worse.
"""

from __future__ import annotations

from pathlib import Path

from .github.client import GitHubClient, GitHubError
from .github.miner import mine_profile
from .matching.semantic import match_skills
from .models import GithubProfile, ReadinessReport
from .resume.parser import parse_resume
from .scoring.engine import score_candidate


def score_resume(
    resume_path: str | Path,
    github_username: str | None = None,
    *,
    client: GitHubClient | None = None,
    candidate_name: str | None = None,
    boolean_mode: bool = False,
    **mining_options,
) -> ReadinessReport:
    resume = parse_resume(resume_path)
    username = github_username or resume.github_username

    # Identity precedence: an explicit override, then the name printed on the
    # CV, then the filename. The filename is LAST for a reason — in the
    # collected dataset Drive appends the uploader's name, so
    # "Anura Perera ... - Binara Silva.pdf" is Anura's CV uploaded by
    # Binara. Preferring the filename attributes one student's verified skills
    # to another student by name.
    name = candidate_name or resume.person_name or Path(resume_path).stem

    claimed_names = [c.name for c in resume.claimed if c.recognised and c.verifiable]

    github: GithubProfile | None = None
    if username:
        client = client or GitHubClient()
        try:
            github = mine_profile(username, claimed_names, client, **mining_options)
        except GitHubError as exc:
            github = GithubProfile(username=username, found=False, error=str(exc))

    verdicts = match_skills(resume.claimed, github or GithubProfile(username="", found=False))

    report = score_candidate(
        name, resume, github, verdicts, boolean_mode=boolean_mode
    )

    if resume.status == "failed":
        report.warnings.insert(0, f"Resume parsing failed: {resume.reason}")
    if not username:
        report.warnings.insert(
            0,
            "No GitHub profile URL or handle could be found in this CV. "
            "Nothing can be verified without one.",
        )
    return report
