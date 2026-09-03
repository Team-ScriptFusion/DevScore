"""
Tests for the parts of the engine where being wrong is silent.

The bar for what earns a test here: a bug that would produce a *plausible
but incorrect score* rather than a crash. A crash gets noticed; a candidate
quietly scored 12 points low because a marker leaked across languages does
not. Every test below corresponds to a failure mode that was either observed
on the real 47-CV dataset or is one regex edit away from returning.

Run:  python -m pytest tests -q      (or: python tests/test_engine.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import ontology
from engine.analysis import brace, python_ast
from engine.analysis.dispatch import complexity_score, craft_score, depth_score, recency_score
from engine.analysis.textprep import strip_noise
from engine.github.miner import (
    EXCLUDE_PATTERNS, classify, classify_authorship, parse_manifest, prerank_repos,
)
from engine.matching.binding import bind_projects
from engine.matching.semantic import _promote
from engine.resume.projects import CVProject, extract_projects
from engine.models import (
    TIER_AMBIENT, TIER_APPLIED, TIER_DECLARED, TIER_MASTERED, TIER_NONE, TIER_USED,
    CodeMetrics, EvidenceHit, RepoEvidence, SkillVerdict,
)
from engine.resume.identity import extract_github, extract_person_name
from engine.resume.parser import team_cv_parser
from pathlib import Path as pathlib_Path
from engine.selection import (
    RosterEntry, SelectionError, load_handle_overrides, select,
)
from engine.scoring.engine import SIGNAL_WEIGHTS, compute_verification


# ---------------------------------------------------------------------------
# Ontology
# ---------------------------------------------------------------------------

def test_weights_are_derived_not_declared():
    """W_i must always be reproducible from (depth, scarcity)."""
    for skill in ontology.SKILLS.values():
        assert skill.weight == ontology.derive_weight(skill.depth, skill.scarcity)
        assert 0.35 <= skill.weight <= 1.0


def test_weight_ordering_matches_the_proposal():
    """The proposal's worked example: Python must outrank HTML by a lot."""
    assert ontology.SKILLS["Python"].weight > ontology.SKILLS["HTML"].weight
    assert ontology.SKILLS["Python"].weight / ontology.SKILLS["HTML"].weight > 1.8


def test_every_regex_compiles():
    """A bad pattern would silently disable an evidence channel, not crash."""
    import re
    for skill in ontology.SKILLS.values():
        for pattern in skill.imports + skill.markers + skill.paths:
            re.compile(pattern)


def test_symbol_heavy_aliases_match():
    """
    v1's tokenizer bug: \\b is defined by \\w, so r"\\bc\\+\\+\\b" does not bound
    "c++". These four are the canaries.
    """
    text = "Skilled in C++, C#, .NET and Node.js with CI/CD experience."
    # Exercised against the DEPLOYED cv_parser, not a local copy of the logic,
    # so a regressed upstream re-sync fails here instead of silently dropping
    # every symbol-heavy skill from the claim set.
    found = team_cv_parser.dictionary_scan(text)
    for expected in ("C++", "C#", ".NET", "Node.js", "CI/CD"):
        assert expected in found, f"{expected} not detected in {text!r}"


def test_longer_alias_wins():
    """'React Native' must not be swallowed by 'React'."""
    assert ontology.ALIAS_INDEX["react native"] == "React Native"
    assert ontology.ALIAS_INDEX["react"] == "React"


def test_non_verifiable_skills_are_excluded_from_scoring():
    for name in ("Agile/Scrum", "Teamwork", "Leadership", "Communication"):
        assert not ontology.SKILLS[name].verifiable


def test_evidence_languages_resolution():
    """Framework skills inherit the language of what they imply."""
    assert ontology.evidence_languages(ontology.SKILLS["Django"]) == frozenset({"Python"})
    assert ontology.evidence_languages(ontology.SKILLS["Spring Boot"]) == frozenset({"Java"})
    assert "JavaScript" in ontology.evidence_languages(ontology.SKILLS["React"])
    # Genuinely cross-language skills stay unrestricted.
    assert ontology.evidence_languages(ontology.SKILLS["Unit Testing"]) == frozenset()


# ---------------------------------------------------------------------------
# Text preparation — the load-bearing correctness guarantee
# ---------------------------------------------------------------------------

def test_comments_and_strings_are_stripped():
    source = '''
    // TODO: switch this to useState() later
    const label = "useState(";
    const real = 1;
    '''
    stripped, _ = strip_noise(source, "JavaScript")
    assert "useState" not in stripped, "a comment/string mention must not survive"
    assert "const real" in stripped


def test_python_docstring_mention_is_not_evidence():
    source = '''
"""This module talks about pandas and tensorflow at length."""
x = 1
'''
    stripped, _ = strip_noise(source, "Python")
    assert "pandas" not in stripped and "tensorflow" not in stripped


def test_stripping_preserves_line_count():
    source = "a = 1\n# comment\nb = 2\n"
    stripped, comments = strip_noise(source, "Python")
    assert stripped.count("\n") == source.count("\n")
    assert comments == 1


# ---------------------------------------------------------------------------
# Static analysis
# ---------------------------------------------------------------------------

def test_python_cyclomatic_is_exact():
    source = '''
def classify(n, flag):
    if n > 10 and flag:
        return "big"
    elif n > 5:
        return "medium"
    for i in range(n):
        if i % 2 == 0:
            pass
    try:
        pass
    except ValueError:
        pass
    return "small"
'''
    m = python_ast.analyze("x.py", source)
    # 1 function + if + elif + `and` + for + inner if + 1 except handler = 7
    assert m.cyclomatic == 7, m.cyclomatic
    assert m.functions == 1
    assert m.has_error_handling
    assert m.analyzed_with == "python_ast"


def test_python_nesting_depth():
    source = '''
def f():
    for a in x:
        if a:
            while a:
                pass
'''
    m = python_ast.analyze("x.py", source)
    assert m.max_nesting >= 4


def test_python_syntax_error_falls_back_not_crashes():
    m = python_ast.analyze("x.py", "def broken(:\n  pass\n")
    assert m.parse_error, "the parse failure must be recorded, not swallowed"
    assert "brace_heuristic" in m.analyzed_with


def test_brace_analyser_counts_arrow_functions():
    source = """
const add = (a, b) => { if (a > b) { return a; } return b; };
function sub(a, b) { return a - b; }
"""
    m = brace.analyze("x.js", source, "JavaScript")
    assert m.functions >= 2
    assert m.cyclomatic >= 3
    assert m.analyzed_with == "brace_heuristic"


def test_else_is_not_counted_as_a_decision():
    with_else = brace.analyze("a.js", "function f(){ if(x){a();} else {b();} }", "JavaScript")
    without = brace.analyze("b.js", "function f(){ if(x){a();} }", "JavaScript")
    assert with_else.cyclomatic == without.cyclomatic


def test_duplicate_block_detection():
    block = "const a = compute(1);\nconst b = compute(2);\nconst c = compute(3);\n" \
            "const d = compute(4);\nconst e = compute(5);\nconst f = compute(6);\n"
    m = brace.analyze("x.js", block * 4, "JavaScript")
    assert m.duplicate_block_ratio > 0.3


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def test_complexity_is_banded_not_monotonic():
    """Tangled code must NOT outscore well-structured code."""
    def metrics(cc_per_fn: float) -> CodeMetrics:
        m = CodeMetrics(path="f.py", language="Python", analyzed_with="python_ast",
                        loc=200, functions=10)
        m.cyclomatic = int(cc_per_fn * 10)
        return m

    trivial = complexity_score([metrics(1.0)])
    good = complexity_score([metrics(5.0)])
    tangled = complexity_score([metrics(30.0)])
    assert trivial < good
    assert tangled < good, "a god-function must not beat clean branching logic"


def test_heuristic_metrics_are_discounted_against_ast_metrics():
    ast_metric = CodeMetrics(path="a.py", analyzed_with="python_ast", loc=200,
                             functions=10, cyclomatic=50)
    heur_metric = CodeMetrics(path="a.js", analyzed_with="brace_heuristic", loc=200,
                              functions=10, cyclomatic=50)
    assert complexity_score([ast_metric]) > complexity_score([heur_metric])


def test_craft_is_capped_without_tests():
    no_tests = [RepoEvidence(name="r", full_name="u/r", has_ci=True, has_readme=True)]
    perfect_files = [CodeMetrics(path="a.py", loc=100, has_error_handling=True,
                                 has_docstrings=True, has_type_annotations=True)]
    # 0.70 from the five non-test components + 0.03 README nudge.
    assert craft_score(perfect_files, no_tests) <= 0.73


def test_depth_and_recency_bounds():
    assert depth_score(0, 0, 0) == 0.0
    assert depth_score(50, 1, 1) < depth_score(3000, 10, 4)
    assert depth_score(10 ** 7, 500, 90) <= 1.0
    assert recency_score(0) == 1.0
    assert recency_score(14) == 0.5          # documented half-life
    assert recency_score(999) == 0.0


# ---------------------------------------------------------------------------
# Tier promotion
# ---------------------------------------------------------------------------

def _hits(**channels) -> list[EvidenceHit]:
    out = []
    for channel, details in channels.items():
        for detail, count in details:
            out.append(EvidenceHit(channel=channel, repo="r", detail=detail, count=count))
    return out


def test_language_only_evidence_is_ambient():
    react = ontology.SKILLS["React"]
    assert _promote(react, _hits(language=[("40% JavaScript", 1)]), 1, 0.5) == TIER_AMBIENT


def test_dependency_without_code_is_declared():
    react = ontology.SKILLS["React"]
    hits = _hits(language=[("x", 1)], dependency=[("react", 1)])
    assert _promote(react, hits, 1, 0.5) == TIER_DECLARED


def test_import_alone_reaches_used():
    react = ontology.SKILLS["React"]
    assert _promote(react, _hits(**{"import": [("App.jsx: from 'react'", 1)]}), 1, 0.9) == TIER_USED


def test_mastery_requires_multiple_repos_and_real_complexity():
    react = ontology.SKILLS["React"]
    strong = _hits(
        **{"import": [("App.jsx", 1)], "dependency": [("react", 1)],
           "marker": [("useState", 6), ("useEffect", 5), ("JSX", 9)]}
    )
    assert _promote(react, strong, 1, 0.9) == TIER_APPLIED, "one repo is not mastery"
    assert _promote(react, strong, 3, 0.2) == TIER_APPLIED, "simple code is not mastery"
    assert _promote(react, strong, 3, 0.9) == TIER_MASTERED


def test_marker_floor_never_exceeds_the_skills_own_marker_count():
    """
    Regression: a flat 'needs 2 distinct markers' rule pinned Tailwind at
    'declared' forever, because only one of its two markers appears outside
    a global stylesheet.
    """
    tailwind = ontology.SKILLS["Tailwind CSS"]
    hits = _hits(marker=[("className util classes", 40)], dependency=[("tailwindcss", 1)])
    assert _promote(tailwind, hits, 1, 0.5) in (TIER_USED, TIER_APPLIED)


def test_no_evidence_is_tier_none():
    assert _promote(ontology.SKILLS["AWS"], [], 0, 0.0) == TIER_NONE


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _verdict(**kw) -> SkillVerdict:
    base = dict(skill="React", category="framework", weight=0.9, claimed=True, verifiable=True)
    base.update(kw)
    return SkillVerdict(**base)


def test_verification_is_gated_by_evidence_strength():
    """Volume must never outrank verification."""
    v = _verdict(tier=TIER_AMBIENT, evidence_strength=0.25,
                 complexity=1.0, depth=1.0, recency=1.0, craft=1.0)
    assert compute_verification(v) <= 0.25


def test_boolean_mode_reproduces_the_original_formula():
    used = _verdict(tier=TIER_USED, evidence_strength=0.7, complexity=0.1, depth=0.1)
    declared = _verdict(tier=TIER_DECLARED, evidence_strength=0.45)
    assert compute_verification(used, boolean_mode=True) == 1.0
    assert compute_verification(declared, boolean_mode=True) == 0.0


def test_signal_weights_sum_to_one():
    assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9


def test_config_evidenced_skills_are_renormalised():
    """
    Docker/Git/CI have no source files, so C and D are structurally zero.
    Scoring them on the full five-signal blend would report a fully verified
    Dockerfile as roughly half-proven.
    """
    common = dict(tier=TIER_USED, evidence_strength=0.7, complexity=0.0, depth=0.0,
                  recency=1.0, craft=0.6)
    as_code = compute_verification(_verdict(content_based=True, **common))
    as_config = compute_verification(_verdict(content_based=False, **common))
    assert as_config > as_code
    assert as_config <= 0.7, "still capped by evidence strength"


def test_shrinkage_stops_under_claiming_from_winning():
    """
    Regression from the real cohort: a candidate claiming ONE verifiable skill
    and proving it scored 75.0, ahead of one claiming twelve and proving nine.
    The weighted ratio is correct and the conclusion is absurd, so the ratio is
    shrunk toward a prior when the denominator is tiny.
    """
    from engine.models import ResumeProfile
    from engine.scoring.engine import score_candidate

    def report_for(n_claims: int):
        verdicts = [
            _verdict(skill=f"S{i}", tier=TIER_APPLIED, evidence_strength=0.9,
                     complexity=0.7, depth=0.8, recency=0.9, craft=0.6)
            for i in range(n_claims)
        ]
        resume = ResumeProfile(file_name="x.pdf", status="success")
        return score_candidate("c", resume, None, verdicts)

    one = report_for(1)
    twelve = report_for(12)
    assert one.score < twelve.score, "one proven claim must not outrank twelve"
    assert one.shrinkage < twelve.shrinkage < 0, "shrinkage must shrink, and shrink less with more claims"
    assert abs(twelve.shrinkage) < 6, "shrinkage must be small at a realistic claim count"
    assert any("verifiable technical skill" in w for w in one.warnings)


# ---------------------------------------------------------------------------
# Candidate identity — the CV owns the name, never the filename
# ---------------------------------------------------------------------------

def test_name_is_read_from_the_cv_not_the_filename():
    """
    Drive appends the UPLOADER's name to a shared file, so
    "Anura Perera - Software Engineering Undergraduate CV - Binara Silva.pdf"
    is Anura's CV uploaded by Binara. Taking the name from the filename
    attributes one student's verified skills to another student by name.
    """
    cv = "Anura Perera\nSoftware Engineering Undergraduate\nlinkedin.com/in/anurap"
    assert extract_person_name(cv) == "Anura Perera"


def test_letter_spaced_headings_are_recovered():
    """Canva exports render the name heading with literal spaces between glyphs."""
    assert extract_person_name("J A N I D U\nD E A L W I S\nCONTACT") == "JANIDU DEALWIS"


def test_name_split_across_lines_is_joined():
    assert extract_person_name("KAVI\nRANASINGHE\nSoftware developer") == "KAVI RANASINGHE"


def test_contact_details_on_the_name_line_are_trimmed():
    """Multi-column layouts interleave the phone number onto the heading line."""
    assert extract_person_name(
        "CHAMILA WEERASINGHE +94 70 000 0000\nIT UNDERGRADUATE"
    ) == "CHAMILA WEERASINGHE"


def test_headings_and_prose_are_not_mistaken_for_names():
    for text in ["PERSONAL DETAILS\nName: x",
                 "Education\nAbout Me",
                 "I am currently pursuing a\nBachelor of Technology",
                 "Projects\nProject",
                 "Software Engineer\nColombo"]:
        assert extract_person_name(text) is None, f"{text!r} produced a name"


def test_lowercase_surname_still_counts():
    assert extract_person_name("Nuwan silva\nFULL-STACK DEVELOPER") == "Nuwan silva"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _roster() -> list[RosterEntry]:
    from pathlib import Path as P

    people = [
        ("Anura Perera", "anuraperera", "Binara Silva"),
        ("Kavi Ranasinghe", "Kavi-R30", "uploader account"),
        ("Dilini Fernando", "diliniFernando", "Dilini Fernando"),
        ("Fayaal Paakeer", None, "Fayaal"),
    ]
    return [
        RosterEntry(index=i, path=P(f"data/cvs/{i}.pdf"), name=n, name_source="cv",
                    filename_label=label, github_username=gh, skill_count=5,
                    status="success")
        for i, (n, gh, label) in enumerate(people, start=1)
    ]


def test_select_by_index_range_and_name():
    roster = _roster()
    assert [e.index for e in select(roster, "2")] == [2]
    assert [e.index for e in select(roster, "1,3")] == [1, 3]
    assert [e.index for e in select(roster, "2-4")] == [2, 3, 4]
    assert [e.index for e in select(roster, "1,3-4")] == [1, 3, 4]
    assert [e.index for e in select(roster, "kavi")] == [2]
    assert [e.index for e in select(roster, "dilinifernando")] == [3]
    assert len(select(roster, "all")) == 4
    assert len(select(roster, None)) == 4


def test_selection_preserves_roster_order_and_dedupes():
    roster = _roster()
    assert [e.index for e in select(roster, "3,1,1,2-3")] == [1, 2, 3]


def test_unmatched_selection_raises_rather_than_silently_scoring_nothing():
    """An empty run and a successful run look identical in a log file."""
    roster = _roster()
    for expression in ("99", "nosuchperson", "1,nosuchperson"):
        try:
            select(roster, expression)
        except SelectionError:
            continue
        raise AssertionError(f"{expression!r} should have raised")


def test_handle_override_file_parsing(tmp_path=None):
    """
    handle_overrides.json supplies a GitHub account for a CV that names none.
    A URL or a bare handle both normalise; a "_comment" key is documentation,
    not an entry; a malformed handle is skipped, not fatal.
    """
    import json, tempfile, os
    d = tempfile.mkdtemp()
    (pathlib_Path(d) / "handle_overrides.json").write_text(json.dumps({
        "_comment": "docs only",
        "a.pdf": {"github": "https://github.com/BinaraSilva", "note": "supplied"},
        "b.pdf": "bare-handle",
        "c.pdf": {"github": "not a valid handle at all"},
        "d.pdf": {"note": "no github key"},
    }), encoding="utf-8")
    ov = load_handle_overrides(d)
    assert set(ov) == {"a.pdf", "b.pdf"}, ov
    assert ov["a.pdf"] == {"github": "BinaraSilva", "note": "supplied"}
    assert ov["b.pdf"]["github"] == "bare-handle"


def test_missing_override_file_is_not_an_error():
    import tempfile
    assert load_handle_overrides(tempfile.mkdtemp()) == {}


def test_name_dispute_is_detected():
    roster = _roster()
    assert roster[0].name_disputed, "Anura's CV labelled 'Binara Silva' must be flagged"
    assert not roster[2].name_disputed, "matching names must not be flagged"


# ---------------------------------------------------------------------------
# GitHub mining helpers
# ---------------------------------------------------------------------------

def test_vendored_and_generated_paths_are_excluded():
    for path in [
        "node_modules/react/index.js", "client/dist/bundle.js", "app/build/out.js",
        "vendor/lib.php", "static/js/app.min.js", "package-lock.json",
        "lib/model.g.dart", "__pycache__/x.pyc", ".venv/lib/site.py",
    ]:
        assert EXCLUDE_PATTERNS.search(path), f"{path} should be excluded"

    for path in ["src/App.jsx", "server/routes/auth.js", "engine/scoring/engine.py"]:
        assert not EXCLUDE_PATTERNS.search(path), f"{path} should be kept"


def test_classify_by_extension():
    assert classify("src/App.tsx") == "TypeScript"
    assert classify("main.py") == "Python"
    assert classify("Main.java") == "Java"
    assert classify("README.md") == ""


def test_manifest_parsing():
    pkg = '{"dependencies":{"react":"^18","express":"4"},"devDependencies":{"jest":"29"}}'
    assert parse_manifest("package.json", pkg) == {"react", "express", "jest"}

    reqs = "Flask==3.1.3\n# a comment\npandas>=2.0\n-r other.txt\n"
    assert parse_manifest("requirements.txt", reqs) == {"flask", "pandas"}

    assert "spring-boot-starter-web" in parse_manifest(
        "pom.xml", "<artifactId>spring-boot-starter-web</artifactId>"
    )
    # Malformed input degrades to "no evidence", never to an exception.
    assert parse_manifest("package.json", "{ not json") == set()


# ---------------------------------------------------------------------------
# CV project extraction and repository binding
# ---------------------------------------------------------------------------

def _scan(text):
    """Stand-in for cv_parser.dictionary_scan over a tiny vocabulary."""
    vocab = ("Python", "React", "Node.js", "MongoDB", "Docker", "MySQL", "PHP")
    return {v for v in vocab if v.lower() in (text or "").lower()}


def test_projects_split_on_titles_not_on_every_bullet():
    cv = ("Projects\n"
          "Lanka Mall E-Commerce Platform 2022\n"
          "- Built with React and Node.js\n"
          "- Deployed to production\n"
          "Plant Growth Monitor\n"
          "- Uses Python and Docker\n"
          "Education\nBSc")
    projects = extract_projects(cv, _scan)
    assert [p.title for p in projects] == [
        "Lanka Mall E-Commerce Platform", "Plant Growth Monitor",
    ], [p.title for p in projects]
    assert "React" in projects[0].skills and "Python" in projects[1].skills


def test_year_suffix_is_stripped_without_eating_the_title():
    """
    Regression: the trailing-noise pattern ran case-insensitively, so its month
    rule matched any three letters and "Platform 2022" truncated to "Platf".
    """
    projects = extract_projects(
        "Projects\nLanka Mall E-Commerce Platform 2022\n- Built with React\nEducation\nx",
        _scan,
    )
    assert projects[0].title == "Lanka Mall E-Commerce Platform"


def test_prose_is_not_promoted_to_a_project_title():
    cv = ("Projects\n"
          "Waste Bin Monitoring System\n"
          "Technologies: Python, Docker\n"
          "- Enhanced prediction by analysing historical data and Sri\n"
          "Lankan seasonal trends. Developed an IoT pipeline\n"
          "Education\nBSc")
    titles = [p.title for p in extract_projects(cv, _scan)]
    assert titles == ["Waste Bin Monitoring System"], titles


def test_declared_stack_is_captured_separately_from_prose():
    projects = extract_projects(
        "Projects\nTask Service\nTechnologies: Docker, Python\n"
        "- also mentions React\nEducation\nx",
        _scan,
    )
    assert set(projects[0].declared_stack) == {"Docker", "Python"}
    assert "React" in projects[0].skills          # prose still recorded
    assert "React" not in projects[0].declared_stack


def test_explicit_github_url_is_extracted():
    projects = extract_projects(
        "Projects\nShop App\n- Built with React\n"
        "- GitHub: github.com/someone/shop-app\nEducation\nx",
        _scan,
    )
    assert projects[0].explicit_repo == "someone/shop-app"


def test_volunteering_section_does_not_leak_in_as_projects():
    """A 49-character header slipped past an earlier 45-char guard."""
    cv = ("Projects\nBoarding Finder Website\n- Built with React\n"
          "Experience in Academic / Extra Curricular Projects\n"
          "Students Union Member\n- Organised events\n")
    titles = [p.title for p in extract_projects(cv, _scan)]
    assert titles == ["Boarding Finder Website"], titles


def _repo(name, *, files=1, description="", langs=None):
    from engine.models import RepoEvidence, SourceFile
    repo = RepoEvidence(name=name, full_name="cand/" + name, description=description,
                        languages=langs or {"JavaScript": 10_000})
    repo.fetched_files = [
        SourceFile(repo=name, path="a.js", language="JavaScript", size_bytes=10)
    ] * files
    return repo


def _verdict_for(skill, repos_with_sign):
    verdict = SkillVerdict(skill=skill, category="framework", weight=0.9,
                           claimed=True, verifiable=True)
    verdict.repos = list(repos_with_sign)
    verdict.code_repos = list(repos_with_sign)
    return verdict


def test_explicit_url_binding_beats_fuzzy_matching():
    project = CVProject(title="Totally Unrelated Name", skills=["React"],
                        explicit_repo="cand/shop-app")
    repos = [_repo("shop-app"), _repo("totally-unrelated-name")]
    binding = bind_projects([project], repos, [_verdict_for("React", ["shop-app"])])[0]
    assert binding.method == "explicit_url"
    assert binding.repo == "shop-app"
    assert binding.confidence == 1.0


def test_conflict_reported_when_bound_repo_lacks_the_claim():
    project = CVProject(title="Shop App", declared_stack=["React", "MongoDB"],
                        explicit_repo="cand/shop-app")
    binding = bind_projects([project], [_repo("shop-app")],
                            [_verdict_for("React", ["shop-app"]),
                             _verdict_for("MongoDB", [])])[0]
    assert binding.has_conflict
    assert binding.missing_skills == ["MongoDB"]
    assert binding.evidenced_skills == ["React"]


def test_no_accusation_when_the_bound_repo_was_never_sampled():
    """
    The most damaging failure available to this module: claiming a project's
    repository lacks a technology when the file sampler never opened it. Seen
    for real - a repo was reported as missing MongoDB and Node.js while its own
    server/package.json declared both.
    """
    project = CVProject(title="Shop App", declared_stack=["React", "MongoDB"],
                        explicit_repo="cand/shop-app")
    binding = bind_projects([project], [_repo("shop-app", files=0)],
                            [_verdict_for("React", []), _verdict_for("MongoDB", [])])[0]
    assert binding.repo == "shop-app"
    assert binding.inspected is False
    assert binding.missing_skills == []
    assert not binding.has_conflict
    assert "never inspected" in binding.explanation


def test_conflict_uses_every_evidence_channel_not_just_code():
    """
    A dependency declared in the repo manifest counts as a sign of the
    technology even when no sampled file imports it - the burden for an
    accusation runs the other way from the burden for a score.
    """
    project = CVProject(title="Shop App", declared_stack=["MongoDB"],
                        explicit_repo="cand/shop-app")
    manifest_only = SkillVerdict(skill="MongoDB", category="database", weight=0.9,
                                 claimed=True, verifiable=True)
    manifest_only.repos = ["shop-app"]        # declared in package.json
    manifest_only.code_repos = []             # never imported in a sampled file
    binding = bind_projects([project], [_repo("shop-app")], [manifest_only])[0]
    assert not binding.has_conflict


def test_zero_token_overlap_never_binds():
    """A project called "Fabric Defect Detection" must not bind to "FIVORA"."""
    project = CVProject(title="Fabric Defect Detection System", skills=[])
    binding = bind_projects([project], [_repo("FIVORA")], [])[0]
    assert binding.repo is None
    assert binding.method == "unbound"


def test_unverifiable_skills_are_never_a_project_conflict():
    class _Soft:
        name = "Agile/Scrum"
        verifiable = False

    project = CVProject(title="Shop App", declared_stack=["Agile"],
                        explicit_repo="cand/shop-app")
    binding = bind_projects([project], [_repo("shop-app")], [],
                            ontology_resolver=lambda n: _Soft())[0]
    assert binding.missing_skills == []


# ---------------------------------------------------------------------------
# Commit authorship
# ---------------------------------------------------------------------------

def _commit(login, name, email, date="2026-01-01T00:00:00Z"):
    return {
        "author": {"login": login} if login else None,
        "commit": {"author": {"name": name, "email": email, "date": date}},
    }


def test_authorship_credits_commits_github_itself_linked():
    log = [_commit("candidate", "Some One", "a@b.com")] * 3
    result = classify_authorship(log, "candidate", "Some One")
    assert (result.mine, result.disputed, result.other) == (3, 0, 0)


def test_authorship_flags_a_half_matching_identity_as_disputed():
    """
    Name matches, email does not - the shared-laptop / copied-.gitconfig case.
    It must not be credited, and it must not be silently discarded either.
    """
    log = [_commit(None, "Some One", "someone-else@corp.com")]
    result = classify_authorship(log, "candidate", "Some One")
    assert (result.mine, result.disputed, result.other) == (0, 1, 0)
    assert result.disputed_names


def test_authorship_learns_unregistered_emails_from_linked_commits():
    """
    A candidate commits from a personal address GitHub linked on some commits
    but not others. The learning pass must credit both.
    """
    log = [
        _commit("candidate", "Some One", "personal@mail.com"),
        _commit(None, "Some One", "personal@mail.com"),
    ]
    result = classify_authorship(log, "candidate", "Some One")
    assert result.mine == 2, (result.mine, result.disputed, result.other)


def test_authorship_attributes_collaborators_elsewhere():
    log = [_commit("someone-else", "Other Person", "other@x.com")] * 4
    result = classify_authorship(log, "candidate", "Some One")
    assert (result.mine, result.other) == (0, 4)
    assert result.ownership_ratio == 0.0


def test_ownership_ratio_and_last_mine_ignore_collaborators():
    log = [
        _commit("candidate", "S", "a@b.com", "2026-05-01T00:00:00Z"),
        _commit("other", "O", "o@b.com", "2026-09-01T00:00:00Z"),
    ]
    result = classify_authorship(log, "candidate", "S")
    assert result.ownership_ratio == 0.5
    assert result.last_mine == "2026-05-01T00:00:00Z"   # not the collaborator's


def test_empty_commit_log_is_not_an_error():
    result = classify_authorship([], "candidate", "S")
    assert result.total == 0 and result.ownership_ratio == 0.0


# ---------------------------------------------------------------------------
# API budget
# ---------------------------------------------------------------------------

def test_prerank_orders_repos_without_any_language_data():
    """
    Pre-ranking has to work on the repo-list payload alone - it runs before any
    language call, which is the entire reason it exists.
    """
    from engine.models import RepoEvidence
    repos = [
        RepoEvidence(name="dotfiles", full_name="c/dotfiles", size_kb=5,
                     pushed_at="2019-01-01T00:00:00Z"),
        RepoEvidence(name="react-shop", full_name="c/react-shop", size_kb=4000,
                     pushed_at="2026-08-01T00:00:00Z", description="A React storefront"),
    ]
    assert all(not r.languages for r in repos)
    assert prerank_repos(repos, ["React"])[0].name == "react-shop"


# ---------------------------------------------------------------------------
# Resume parsing
# ---------------------------------------------------------------------------

def test_github_handle_from_link_annotation():
    urls, handle = extract_github("", ["https://github.com/DevHandle", "https://linkedin.com/in/x"])
    assert handle == "DevHandle"


def test_github_reserved_paths_are_not_handles():
    _, handle = extract_github("see github.com/topics/react", [])
    assert handle != "topics"


def test_bare_handle_requires_a_separator_and_rejects_prose():
    """
    Regression from the real dataset: 'GitHub | 2025', 'GitHub projects' and
    'Github Analysis' were all reported as usernames. A wrong handle is worse
    than none — it scores the candidate against a stranger's repositories.
    """
    for text in ["GitHub | 2025", "GitHub projects", "Github Analysis",
                 "GitHub Education benefits", "my GitHub repositories"]:
        _, handle = extract_github(text, [])
        assert handle is None, f"{text!r} produced handle {handle!r}"

    _, good = extract_github("GitHub: janidu-de-alwis", [])
    assert good == "janidu-de-alwis"


def test_skills_section_slicing_stops_at_next_header():
    """cv_parser's own section slicer — the deployed one, not a reimplementation."""
    text = "Skills\nPython, React, SQL\nEducation\nBSc in IT\nMore education text"
    block = team_cv_parser.find_skills_section(text)
    assert "Python" in block
    assert "BSc" not in block


def test_cv_parser_output_maps_onto_the_ontology():
    """
    cv_parser is the authority on claims; this ontology is the authority on
    verification. The crosswalk joins them, and a broken mapping would silently
    drop a real claim out of the score.
    """
    assert ontology.from_cv_parser("OpenCV").name == "Computer Vision"
    assert ontology.from_cv_parser("Android Development").name == "Android (Native)"
    assert ontology.from_cv_parser("scikit-learn").name == "Machine Learning"
    assert ontology.from_cv_parser("GitHub").name == "Git"
    assert ontology.from_cv_parser("Jest").name == "Unit Testing"
    assert ontology.from_cv_parser("MariaDB").name == "MySQL"
    # Exact names pass straight through.
    assert ontology.from_cv_parser("Python").name == "Python"
    assert ontology.from_cv_parser("Tailwind CSS").name == "Tailwind CSS"
    # Recognised but not code-verifiable.
    assert not ontology.from_cv_parser("Jira").verifiable
    # No verification recipe at all -> None; the caller reports it unscored.
    assert ontology.from_cv_parser("Terraform") is None
    assert ontology.from_cv_parser("Microsoft Excel") is None


def test_every_crosswalk_target_exists():
    """A typo in the crosswalk would silently unscore a whole skill."""
    for source, target in ontology.CV_PARSER_CROSSWALK.items():
        assert target in ontology.SKILLS, f"{source} -> {target!r} is not an ontology entry"


def test_crosswalk_covers_the_deployed_dictionary():
    """
    Every cv_parser skill must either map, resolve by name/alias, or be listed
    in CV_PARSER_UNMAPPED_NOTE. Silence is the failure mode: a skill added
    upstream would otherwise vanish from scoring with no signal at all.
    """
    from skills_dictionary import SKILL_DICTIONARY

    unaccounted = [
        name for name in SKILL_DICTIONARY
        if ontology.from_cv_parser(name) is None
        and name not in ontology.CV_PARSER_UNMAPPED_NOTE
    ]
    assert not unaccounted, (
        "cv_parser skills neither mapped nor explicitly noted as unmapped: "
        + ", ".join(sorted(unaccounted))
    )


# ---------------------------------------------------------------------------

def _run_all() -> int:
    failures = 0
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, func in tests:
        try:
            func()
            print(f"  PASS  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ERROR {name}: {exc.__class__.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
