"""
Claim ↔ evidence matching: where "the CV says React" becomes "yes, and here
are the four files that prove it, and here is how good they are."

For each skill this runs every ontology channel over the mined pool and
promotes the result to an evidence tier. The promotion rules are the
substance of the module, so they are stated plainly:

    AMBIENT    the repo contains the skill's language above a floor share,
               and nothing else. "There is JavaScript here" — which for a
               React claim is nearly worthless, and is scored accordingly.

    DECLARED   a manifest lists the dependency, but no source file we
               sampled imports it. Common and informative: it is what
               `create-react-app`, a cloned template, or an abandoned
               experiment looks like from the outside.

    USED       an import/require/using of the skill appears in code. The
               candidate wrote a line that pulls the thing in.

    APPLIED    used, plus idiomatic markers at volume (≥ MARKER_FLOOR
               distinct marker hits). Someone writing `useState`,
               `useEffect` and `props` is building components, not
               following step 3 of a tutorial.

    MASTERED   applied, and across ≥ 2 repositories THAT CONTAIN REAL CODE
               for it, and the code carries real complexity. Repetition
               across projects separates "did it once for a module" from
               "reaches for this by default". The repository count here
               deliberately excludes repos matched only by language share:
               a TypeScript-heavy account would otherwise hand React an
               ambient hit in every repo and coast to mastery on it.

Two properties worth calling out because they are the project's actual
research contribution over a keyword matcher:

  1. Markers are matched against comment- and string-stripped source (see
     analysis/textprep.py), so a README, a tutorial link, or a commented-out
     line never promotes a tier. Evidence must be executable.

  2. UNCLAIMED STRENGTHS are surfaced. A candidate with three strong Django
     repos who forgot to put Django on their resume is a *hiring signal*,
     not a scoring event. It cannot raise the integrity score — the score
     measures claim honesty, and rewarding omission would corrupt that —
     but it goes on the dashboard, because the recruiter should see it.
     This directly addresses the "verification false negative" risk in the
     project summary: the tool must not silently punish people whose
     resumes undersell them.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .. import ontology
from ..analysis import textprep
from ..analysis.dispatch import (
    analyze_files,
    complexity_score,
    craft_score,
    depth_score,
    recency_score,
)
from ..github.miner import months_since
from ..models import (
    TIER_AMBIENT,
    TIER_APPLIED,
    TIER_DECLARED,
    TIER_MASTERED,
    TIER_NONE,
    TIER_STRENGTH,
    TIER_USED,
    ClaimedSkill,
    CodeMetrics,
    EvidenceHit,
    GithubProfile,
    RepoEvidence,
    SkillVerdict,
    SourceFile,
)

# A language must be at least this share of a repo before "the repo contains
# this language" counts as even ambient evidence. Below it, we are looking at
# a stray config file or a single vendored snippet.
LANGUAGE_FLOOR = 0.08
LANGUAGE_BYTES_FLOOR = 2_000

# Distinct marker patterns that must hit before USED is promoted to APPLIED.
MARKER_FLOOR = 2

# Complexity a skill's code must reach before APPLIED can become MASTERED.
MASTERY_COMPLEXITY = 0.55


def _compile(patterns: tuple[str, ...]) -> list[re.Pattern[str]]:
    out = []
    for pattern in patterns:
        try:
            out.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        except re.error:  # pragma: no cover - guards a bad ontology edit
            continue
    return out


class _Prepared:
    """A mined file with its source stripped once, reused by every skill."""

    __slots__ = ("file", "stripped", "raw", "metrics")

    def __init__(self, file: SourceFile, metrics: CodeMetrics) -> None:
        self.file = file
        self.raw = file.text
        self.stripped, _ = textprep.strip_noise(file.text, file.language)
        self.metrics = metrics


def _prepare(github: GithubProfile) -> dict[str, list[_Prepared]]:
    """Strip and analyse every mined file exactly once, grouped by repo."""
    by_repo: dict[str, list[_Prepared]] = defaultdict(list)
    for repo in github.repos:
        if not repo.fetched_files:
            continue
        metrics = analyze_files(repo.fetched_files)
        by_path = {m.path: m for m in metrics}
        for file in repo.fetched_files:
            metric = by_path.get(file.path)
            if metric is None:
                continue
            by_repo[repo.name].append(_Prepared(file, metric))
    return by_repo


def _evidence_for_skill(
    skill: ontology.Skill,
    repos: list[RepoEvidence],
    prepared: dict[str, list[_Prepared]],
) -> tuple[list[EvidenceHit], list[CodeMetrics], set[str], set[str], int, str]:
    """
    Run every evidence channel for one skill.

    Returns (hits, metrics of files that evidenced it, all repo names,
    repo names with real code evidence, lines analysed, last activity).
    """
    import_patterns = _compile(skill.imports)
    marker_patterns = _compile(skill.markers)
    path_patterns = _compile(skill.paths)
    dep_set = {d.lower() for d in skill.deps}
    allowed_languages = ontology.evidence_languages(skill)

    hits: list[EvidenceHit] = []
    metrics: list[CodeMetrics] = []
    repo_names: set[str] = set()
    # Repositories where the skill was found in ACTUAL CODE (import, marker,
    # path or commit), as opposed to merely inferred from a language
    # percentage or a manifest entry. The two counts diverge sharply: a
    # TypeScript-heavy account gives React an ambient hit in every repo, which
    # would otherwise read as "verified across 13 repositories" on the
    # strength of 6 files in 4 of them.
    code_repo_names: set[str] = set()
    loc_total = 0
    last_activity = ""

    for repo in repos:
        repo_hit = False
        code_hit = False

        # -- channel 0: commit authorship (Git only) -----------------------
        if skill.from_commits and repo.commits_by_owner > 0:
            hits.append(EvidenceHit(
                channel="import",  # scored at "used" strength — authored work
                repo=repo.name,
                detail=f"{repo.commits_by_owner} commit(s) authored in this repository",
                count=repo.commits_by_owner,
            ))
            repo_hit = code_hit = True

        # -- channel 5: repository paths (Dockerfile, workflows, configs) ---
        for pattern in path_patterns:
            matched = [p for p in repo.file_paths if pattern.search(p)]
            if matched:
                hits.append(EvidenceHit(
                    channel="import",  # authored config files, not a declaration
                    repo=repo.name,
                    detail=f"{matched[0]}" + (f" (+{len(matched) - 1} more)" if len(matched) > 1 else ""),
                    count=len(matched),
                ))
                repo_hit = code_hit = True

        # -- channel 1: language share -------------------------------------
        for language in skill.languages:
            share = repo.language_share(language)
            byte_count = repo.languages.get(language, 0)
            if share >= LANGUAGE_FLOOR and byte_count >= LANGUAGE_BYTES_FLOOR:
                hits.append(EvidenceHit(
                    channel="language",
                    repo=repo.name,
                    detail=f"{language} is {share:.0%} of the repo ({byte_count:,} bytes)",
                ))
                repo_hit = True

        # -- channel 2: declared dependency --------------------------------
        for dep in dep_set:
            if dep in repo.dependencies:
                hits.append(EvidenceHit(
                    channel="dependency",
                    repo=repo.name,
                    detail=f"'{dep}' declared in {', '.join(repo.manifests[:2]) or 'a manifest'}",
                ))
                repo_hit = True

        # -- channels 3 & 4: imports and idioms, in stripped source --------
        for item in prepared.get(repo.name, []):
            # Language gate. A skill's idioms can only prove anything in a
            # file of a language that skill is actually written in.
            if allowed_languages and item.file.language not in allowed_languages:
                continue

            haystack = item.raw if skill.search_raw else item.stripped
            file_matched = False

            for pattern in import_patterns:
                match = pattern.search(item.stripped)
                if match:
                    hits.append(EvidenceHit(
                        channel="import",
                        repo=repo.name,
                        detail=f"{item.file.path}: {match.group(0).strip()[:70]}",
                    ))
                    file_matched = True
                    break

            marker_hits = 0
            for pattern in marker_patterns:
                found = pattern.findall(haystack)
                if found:
                    marker_hits += 1
                    hits.append(EvidenceHit(
                        channel="marker",
                        repo=repo.name,
                        detail=f"{item.file.path}: {pattern.pattern[:48]}",
                        count=len(found),
                    ))
            if marker_hits:
                file_matched = True

            if file_matched:
                metrics.append(item.metrics)
                loc_total += item.metrics.loc
                repo_hit = code_hit = True

        if repo_hit:
            repo_names.add(repo.name)
            stamp = repo.last_owner_commit or repo.pushed_at
            if stamp > last_activity:
                last_activity = stamp
        if code_hit:
            code_repo_names.add(repo.name)

    return hits, metrics, repo_names, code_repo_names, loc_total, last_activity


def _promote(
    skill: ontology.Skill,
    hits: list[EvidenceHit],
    repo_count: int,
    complexity: float,
) -> str:
    channels = {h.channel for h in hits}
    if not channels:
        return TIER_NONE

    marker_hits = [h for h in hits if h.channel == "marker"]
    distinct_markers = len({h.detail.split(": ", 1)[-1] for h in marker_hits})
    marker_volume = sum(h.count for h in marker_hits)
    has_import = "import" in channels
    has_dep = "dependency" in channels

    # Diversity OR volume, not diversity alone. Requiring two *distinct*
    # idioms permanently pinned Tailwind at 'declared': it has two markers
    # and one of them (the @tailwind directive) only ever appears in a single
    # global stylesheet, so thousands of utility classes across a dozen
    # components still counted as one distinct marker. One idiom used
    # heavily is applied usage; the volume path says so.
    floor = min(MARKER_FLOOR, len(skill.markers)) if skill.markers else MARKER_FLOOR
    strong_markers = (distinct_markers >= floor and marker_volume >= 3) or marker_volume >= 8

    if has_import or strong_markers:
        tier = TIER_USED
        strong_usage = marker_volume >= 8 or distinct_markers >= 3
        if strong_usage and (has_import or has_dep or distinct_markers >= floor):
            tier = TIER_APPLIED
            if repo_count >= 2 and complexity >= MASTERY_COMPLEXITY:
                tier = TIER_MASTERED
        return tier

    if has_dep:
        return TIER_DECLARED
    return TIER_AMBIENT


def _explain(verdict: SkillVerdict, repo_count: int) -> str:
    if verdict.tier == TIER_NONE:
        if not verdict.verifiable:
            return "Not verifiable from public code — reported for recruiter context only."
        return (
            "Claimed on the CV, but no supporting code was found in the public "
            "repositories that were mined. This means unevidenced, not untrue: "
            "private or organisation repositories are out of scope by design."
        )

    channels = {h.channel for h in verdict.evidence}
    parts: list[str] = []

    if verdict.tier == TIER_AMBIENT:
        parts.append(
            "Only ambient evidence: the language appears in the candidate's repositories, "
            "but nothing shows this specific technology being used."
        )
    elif verdict.tier == TIER_DECLARED:
        parts.append(
            "Declared as a dependency but never seen in the sampled source — consistent with "
            "a scaffolded or abandoned project."
        )
    elif not verdict.content_based:
        # Git, Docker, CI/CD, Kubernetes, Nginx — evidenced by authored
        # configuration or commit history, so there is no source file to
        # describe and no complexity to report.
        detail = verdict.evidence[0].detail if verdict.evidence else ""
        parts.append(
            f"Evidenced by authored configuration or commit history in {repo_count} "
            f"{'repository' if repo_count == 1 else 'repositories'}"
            + (f" (e.g. {detail})" if detail else "")
            + ". There is no source file to measure complexity on for this skill."
        )
    else:
        marker_total = sum(h.count for h in verdict.evidence if h.channel == "marker")
        parts.append(
            f"Verified in code across {repo_count} "
            f"{'repository' if repo_count == 1 else 'repositories'}: "
            f"{verdict.files_analyzed} file(s), {verdict.loc_analyzed:,} lines analysed"
            + (f", {marker_total} idiomatic usages" if marker_total else "")
            + "."
        )

    if verdict.contribution_only:
        # Real evidence they write the technology, but it is code added to
        # someone else's repository, so no complexity was derived from it and
        # the sentence must not imply otherwise.
        parts.append(
            "All of it is code they added to a repository someone else owns, so it "
            "shows they write this technology but says nothing about how they "
            "structure a project of their own."
        )
    elif verdict.content_based:
        if verdict.complexity >= 0.75:
            parts.append("Code shows substantial branching and structure.")
        elif verdict.complexity >= 0.4:
            parts.append("Code is straightforward but non-trivial.")
        elif verdict.tier in (TIER_USED, TIER_APPLIED, TIER_MASTERED):
            parts.append("Code is present but simple — limited evidence of depth.")

    if verdict.recency < 0.35 and verdict.last_activity:
        parts.append(f"Last touched {verdict.last_activity[:10]} — evidence is dated.")

    if verdict.craft >= 0.6:
        parts.append("Supporting repositories show tests and/or CI.")
    elif verdict.craft < 0.25:
        parts.append("No tests or CI found in the supporting repositories.")

    marker_total = sum(h.count for h in verdict.evidence if h.channel == "marker")
    if ("dependency" in channels and "import" not in channels
            and verdict.tier != TIER_DECLARED and marker_total < 20):
        # Only worth saying when usage is thin. Modern React and Next.js code
        # legitimately never writes `import React`, so flagging it on a file
        # with hundreds of hook and JSX hits reads as a doubt we do not have.
        parts.append("Dependency declared, though no explicit import appeared in the sampled files.")

    return " ".join(parts)


def match_skills(
    claimed: list[ClaimedSkill],
    github: GithubProfile,
) -> list[SkillVerdict]:
    """
    Produce one SkillVerdict per claimed skill, plus verdicts for unclaimed
    skills that the code clearly demonstrates.
    """
    prepared = _prepare(github)
    repos = github.repos

    claimed_by_name = {c.name: c for c in claimed if c.recognised}
    verdicts: list[SkillVerdict] = []

    # Everything we might have something to say about: what was claimed, plus
    # every verifiable skill in the ontology (to surface unclaimed strengths).
    candidates = set(claimed_by_name) | {s.name for s in ontology.verifiable_skills()}

    for name in sorted(candidates):
        skill = ontology.get(name)
        if skill is None:
            continue

        claim = claimed_by_name.get(name)
        is_claimed = claim is not None

        verdict = SkillVerdict(
            skill=skill.name,
            category=skill.category,
            weight=skill.weight,
            claimed=is_claimed,
            verifiable=skill.verifiable,
        )

        if not skill.verifiable:
            if is_claimed:
                verdict.explanation = _explain(verdict, 0)
                verdicts.append(verdict)
            continue

        hits, metrics, repo_names, code_repos, loc_total, last_activity = _evidence_for_skill(
            skill, repos, prepared
        )

        if not hits and not is_claimed:
            continue  # nothing claimed, nothing found — no row to show

        supporting = [r for r in repos if r.name in repo_names]
        verdict.evidence = hits
        verdict.metrics = metrics
        verdict.repos = sorted(repo_names)
        verdict.loc_analyzed = loc_total
        verdict.files_analyzed = len(metrics)
        verdict.last_activity = last_activity

        verdict.complexity = complexity_score(metrics)
        verdict.craft = craft_score(metrics, supporting)
        verdict.depth = depth_score(loc_total, len(metrics), len(repo_names))
        verdict.recency = recency_score(months_since(last_activity)) if last_activity else 0.0

        # Skills evidenced by configuration or commit history rather than by
        # source files (Git, Docker, CI/CD, Kubernetes, Nginx) have no code to
        # measure, so complexity and depth are structurally zero for them.
        verdict.content_based = bool(skill.markers or skill.imports)
        verdict.contribution_only = bool(metrics) and all(
            m.analyzed_with == "contribution_fragment" for m in metrics
        )
        verdict.code_repos = sorted(code_repos)
        # Mastery counts repositories with real code, not repositories that
        # merely contain the language.
        verdict.tier = _promote(skill, hits, len(code_repos), verdict.complexity)
        verdict.evidence_strength = TIER_STRENGTH[verdict.tier]
        verdict.unclaimed_evidence = (not is_claimed) and verdict.tier in (
            TIER_USED, TIER_APPLIED, TIER_MASTERED
        )
        verdict.explanation = _explain(verdict, len(code_repos) or len(repo_names))

        if not is_claimed and not verdict.unclaimed_evidence:
            continue  # weak, unclaimed — noise, drop it

        verdicts.append(verdict)

    # Unrecognised resume terms still deserve a row on the dashboard.
    for claim in claimed:
        if claim.recognised:
            continue
        verdicts.append(SkillVerdict(
            skill=claim.name,
            category="uncategorized",
            weight=0.0,
            claimed=True,
            verifiable=False,
            explanation=(
                "Listed in the CV's skills section but not in the verification ontology, "
                "so it is shown for context and excluded from the score."
            ),
        ))

    return verdicts
