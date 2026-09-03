"""
CV project ↔ repository binding.

Skill-level matching answers "does React appear anywhere in this candidate's
repositories?". That is a claim about the *candidate*. This module answers a
claim about a *project*:

    the CV says "Lanka Mall E-Commerce Platform — React, Node.js, MongoDB"
    the bound repository has React and nothing resembling a backend

Those are different findings and they fail differently. "React: no public
evidence" means we could not find proof. "This project claims MongoDB and its
own linked repository has none" means we looked exactly where the candidate
pointed us and it was not there. The second is falsifiable; the first is only
an absence.

------------------------------------------------------------------------
WHY THIS DOES NOT MOVE THE SCORE
------------------------------------------------------------------------
Bindings are produced two ways, and only one of them is certain:

    explicit_url   the CV entry carries `github.com/owner/repo`. The candidate
                   pointed at the repository themselves. Certain.
    name_match     fuzzy string agreement between the project title and a repo
                   name/description. A guess, and guesses compound.

A wrong binding produces a confident accusation about a specific project, which
is the single most damaging output this system could emit. So bindings are
REPORTED, never scored: they appear on the dashboard with their confidence and
method, and Σ Wᵢ·Vᵢ is untouched. Folding a fuzzy string match into a number
that a recruiter reads as objective would be exactly the false precision this
project exists to remove — and unlike the skill-level signals, there is no
honest way to calibrate it against the 32-candidate cohort.

The finding is the value. The number stays out of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from typing import Any

from ..models import RepoEvidence, SkillVerdict
from ..resume.projects import CVProject

# Tokens that carry no identifying information — nearly every student project
# is a "system" or a "management application", so matching on them would bind
# everything to everything.
_GENERIC = {
    "system", "systems", "app", "apps", "application", "applications",
    "project", "projects", "website", "web", "site", "platform", "portal",
    "management", "managing", "manager", "online", "smart", "based", "using",
    "full", "stack", "fullstack", "mobile", "desktop", "tool", "tools",
    "software", "solution", "service", "services", "api", "ui", "frontend",
    "backend", "dashboard", "monitoring", "tracker", "tracking", "the", "and",
    "for", "with", "of", "a", "an", "my", "new", "final", "year", "research",
}

# Confidence needed before a fuzzy binding is reported at all.
MIN_CONFIDENCE = 0.55
# Below this, a binding is shown but flagged as tentative.
TENTATIVE_BELOW = 0.72


@dataclass
class ProjectBinding:
    project_title: str
    repo: str | None = None
    confidence: float = 0.0
    method: str = "unbound"          # explicit_url | name_match | unbound
    claimed_skills: list[str] = field(default_factory=list)
    evidenced_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    # Whether the bound repository actually had source files sampled. False
    # means we never looked inside it, so `missing_skills` stays empty — see
    # bind_projects for why that distinction is load-bearing.
    inspected: bool = False
    explanation: str = ""

    @property
    def tentative(self) -> bool:
        return self.method == "name_match" and self.confidence < TENTATIVE_BELOW

    @property
    def has_conflict(self) -> bool:
        return bool(self.repo and self.inspected and self.missing_skills)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["confidence"] = round(self.confidence, 3)
        d["tentative"] = self.tentative
        d["has_conflict"] = self.has_conflict
        return d


def _tokens(text: str) -> set[str]:
    words = re.split(r"[^A-Za-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _GENERIC}


def _similarity(title: str, repo: RepoEvidence) -> tuple[float, str]:
    """
    Best agreement between a project title and a repository, plus which field
    produced it. Repo names are hyphen/underscore separated, so they are
    flattened to words before comparison.
    """
    title_norm = " ".join(sorted(_tokens(title)))
    if not title_norm:
        return 0.0, "name"

    best, source = 0.0, "name"
    for field_name, value in (("name", repo.name.replace("-", " ").replace("_", " ")),
                              ("description", repo.description or "")):
        candidate_tokens = _tokens(value)
        if not candidate_tokens:
            continue

        overlap = _tokens(title) & candidate_tokens
        # Jaccard on the smaller side: a long description should not be
        # penalised for containing words the short title never had.
        coverage = len(overlap) / max(1, min(len(_tokens(title)), len(candidate_tokens)))
        ratio = SequenceMatcher(None, title_norm, " ".join(sorted(candidate_tokens))).ratio()

        # Two distinctive shared words beat a high character ratio on generic
        # text, so coverage leads and the ratio only refines.
        score = 0.65 * coverage + 0.35 * ratio
        if len(overlap) >= 2:
            score = min(1.0, score + 0.12)
        if field_name == "description":
            score *= 0.9   # a description match is weaker than a name match

        if score > best:
            best, source = score, field_name

    return best, source


def bind_projects(
    projects: list[CVProject],
    repos: list[RepoEvidence],
    verdicts: list[SkillVerdict],
    *,
    ontology_resolver=None,
) -> list[ProjectBinding]:
    """
    Attach each CV project to a repository where possible, then check whether
    that repository actually evidences the stack the CV attributes to it.

    `ontology_resolver` maps a cv_parser skill name to an ontology Skill (i.e.
    `ontology.from_cv_parser`); it is injected so this module does not import
    the ontology directly and stays testable with plain fakes.
    """
    if not projects:
        return []

    by_full_name = {r.full_name.lower(): r for r in repos}

    # skill name -> every repo showing ANY sign of it: language share, a
    # manifest dependency, an import, or an idiom.
    #
    # Deliberately the widest channel set, and NOT `code_repos`. An earlier
    # version used code evidence only and produced a textbook false accusation:
    # a gym-management project was reported as "claims MongoDB and Node.js, its
    # repository shows none" when that repository contains `server/package.json`
    # declaring exactly those — the file sampler had simply spent its budget on
    # the client folder and never opened the backend.
    #
    # Skill-level scoring is right to demand real code, because it is measuring
    # depth. A project-level conflict is an accusation about a specific claim,
    # so the burden runs the other way: it may only be raised when there is no
    # trace of the technology in that repository through any channel at all.
    evidence_index: dict[str, set[str]] = {}
    for verdict in verdicts:
        evidence_index[verdict.skill] = set(verdict.repos or []) | set(verdict.code_repos or [])

    taken: set[str] = set()
    bindings: list[ProjectBinding] = []

    for project in projects:
        binding = ProjectBinding(project_title=project.title)

        # The declared "Technologies:" line is the candidate's own attribution
        # and is preferred; prose mentions are a weaker basis for an accusation.
        claimed_raw = project.declared_stack or project.skills
        binding.claimed_skills = list(claimed_raw)

        matched: RepoEvidence | None = None

        if project.explicit_repo:
            matched = by_full_name.get(project.explicit_repo.lower())
            if matched is None:
                # Points at a repo we did not mine — a fork, renamed, deleted,
                # or another account. Report the pointer, claim nothing.
                binding.method = "unbound"
                binding.explanation = (
                    f"The CV links this project to {project.explicit_repo}, which is not "
                    "among the public repositories mined for this account."
                )
                bindings.append(binding)
                continue
            binding.method = "explicit_url"
            binding.confidence = 1.0
        else:
            best_score, best_repo = 0.0, None
            for repo in repos:
                if repo.full_name in taken:
                    continue
                score, _source = _similarity(project.title, repo)
                if score > best_score:
                    best_score, best_repo = score, repo
            # A character-similarity score with ZERO distinctive tokens in
            # common is a coincidence, not a match: "Fabric Defect Detection
            # System" scored against a repo called FIVORA purely on description
            # text. Require at least one shared identifying word.
            if (best_repo is not None and best_score >= MIN_CONFIDENCE
                    and _tokens(project.title) & (
                        _tokens(best_repo.name.replace("-", " ").replace("_", " "))
                        | _tokens(best_repo.description or "")
                    )):
                matched = best_repo
                binding.method = "name_match"
                binding.confidence = best_score

        if matched is None:
            binding.explanation = (
                "No repository matched this project by name. It may be private, "
                "named differently, or not on GitHub at all — nothing is concluded "
                "from the absence."
            )
            bindings.append(binding)
            continue

        taken.add(matched.full_name)
        binding.repo = matched.name
        binding.inspected = bool(matched.fetched_files)

        if not binding.inspected:
            # The sampler never opened this repository — it ranked below the
            # per-candidate file budget. Saying "claims React, repo has none"
            # here would be an accusation about code we never read, which is
            # the single most damaging thing this module could emit. Report the
            # binding, claim nothing about its contents.
            binding.explanation = (
                f"Matched to {matched.name}, but that repository was not among the "
                "ones sampled for source code, so its contents were never inspected. "
                "No conclusion is drawn about the technologies attributed to it."
            )
            bindings.append(binding)
            continue

        # Which of the attributed skills does THIS repo actually evidence?
        for raw_name in claimed_raw:
            skill = ontology_resolver(raw_name) if ontology_resolver else None
            canonical = skill.name if skill is not None else raw_name
            if skill is not None and not skill.verifiable:
                continue                      # not checkable from code either way
            repos_with_any_sign = evidence_index.get(canonical, set())
            if matched.name in repos_with_any_sign:
                binding.evidenced_skills.append(raw_name)
            else:
                binding.missing_skills.append(raw_name)

        binding.explanation = _explain(binding, matched)
        bindings.append(binding)

    return bindings


def _explain(binding: ProjectBinding, repo: RepoEvidence) -> str:
    how = {
        "explicit_url": f"The CV links this project directly to {repo.name}.",
        "name_match": (
            f"Matched to {repo.name} by name"
            f" ({binding.confidence:.0%} confidence)"
            + (" — tentative." if binding.tentative else ".")
        ),
    }.get(binding.method, "")

    if not binding.claimed_skills:
        return f"{how} The CV attributes no specific technologies to this project."

    if not binding.missing_skills:
        return (
            f"{how} All {len(binding.evidenced_skills)} attributed "
            f"{'technology is' if len(binding.evidenced_skills) == 1 else 'technologies are'} "
            "present in that repository's code."
        )

    missing = ", ".join(binding.missing_skills)
    caveat = (
        " Treat this as a lead rather than a finding — the repository match is fuzzy."
        if binding.tentative else
        " Worth asking about; it is not proof, since private history and "
        "unsampled files stay invisible."
    )
    return (
        f"{how} The CV attributes {missing} to it, but that repository shows no "
        f"sign of {'it' if len(binding.missing_skills) == 1 else 'them'} — not in "
        "its languages, its dependency manifests, or its sampled code."
        f"{caveat}"
    )
