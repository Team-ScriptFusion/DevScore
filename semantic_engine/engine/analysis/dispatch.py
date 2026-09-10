"""
Analyser selection + the normalisation that turns raw metrics into the two
[0,1] signals the scoring engine consumes: `complexity` and `craft`.

The normalisation anchors below are the most opinionated numbers in the
project after the difficulty weights, so they are stated explicitly rather
than buried in a formula.

COMPLEXITY (C) — "is this real engineering or a tutorial follow-along?"

  Cyclomatic complexity per function is the primary axis, and it is scored
  as a *band*, not a monotonic ramp:

      < 1.5   trivial      0.15   getters, config objects, exports
      1.5–3   simple       0.45   straightforward CRUD
      3–8     substantial  1.00   real branching logic — the target band
      8–15    heavy        0.75   works, but complexity is becoming a smell
      > 15    tangled      0.45   likely one god-function

  A band, because "more complex = better" is false and rewarding it would
  make the model prefer unmaintainable code. Peak reward sits where a
  competent engineer's code actually lives. This is also the one place the
  model can say something a keyword matcher never can: it distinguishes a
  400-line React file that is fifteen composed components from a 400-line
  React file that is one component with a fifteen-branch conditional.

  Nesting depth and file size modulate it: depth > 6 or a 2000-line file
  drags the score down, because both are structural failures regardless of
  how clever the logic is.

CRAFT (Q) — "would a reviewer accept this?"

  Six independent boolean-ish signals, each contributing a documented share:
  tests in the repo (0.30 — the strongest single predictor of engineering
  maturity), error handling (0.20), CI (0.15), meaningful comments/docs
  (0.10), type annotations (0.10), non-duplicated code (0.15). No single
  signal can carry the score, and a candidate with no tests anywhere caps
  out at 0.73 (0.70 plus the README nudge) no matter how clever the code is.
"""

from __future__ import annotations

from ..models import CodeMetrics, RepoEvidence, SourceFile
from . import brace, python_ast

# Analysers whose numbers come from a real parse rather than a token scan.
_EXACT_ANALYSERS = {"python_ast"}

# Confidence multiplier applied to heuristic complexity. Not a penalty on the
# candidate — a statement about our own measurement error, and it is why the
# report labels `analyzed_with` on every metric row.
HEURISTIC_CONFIDENCE = 0.92


def analyze_file(file: SourceFile) -> CodeMetrics:
    if file.language == "Python":
        return python_ast.analyze(file.path, file.text)
    return brace.analyze(file.path, file.text, file.language or "JavaScript")


def analyze_files(files: list[SourceFile]) -> list[CodeMetrics]:
    out: list[CodeMetrics] = []
    for file in files:
        if not file.text.strip():
            continue
        try:
            out.append(analyze_file(file))
        except Exception as exc:  # pragma: no cover - defensive
            out.append(CodeMetrics(
                path=file.path,
                language=file.language,
                analyzed_with="failed",
                parse_error=f"{exc.__class__.__name__}: {exc}",
            ))
    return out


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _complexity_band(cyclomatic_per_function: float) -> float:
    cpf = cyclomatic_per_function
    if cpf < 1.5:
        return 0.15
    if cpf < 3.0:
        return 0.45
    if cpf <= 8.0:
        return 1.00
    if cpf <= 15.0:
        return 0.75
    return 0.45


def _structure_modifier(metrics: CodeMetrics) -> float:
    """Multiplicative penalties for structural problems. Range ~[0.55, 1.0]."""
    modifier = 1.0
    if metrics.max_nesting > 6:
        modifier *= 0.85
    if metrics.max_nesting > 9:
        modifier *= 0.85
    if metrics.loc > 1200:
        modifier *= 0.85
    if metrics.max_function_loc > 250:
        modifier *= 0.90
    if metrics.longest_line > 400:
        modifier *= 0.95
    if metrics.duplicate_block_ratio > 0.25:
        modifier *= 0.85
    return modifier


def complexity_score(metrics_list: list[CodeMetrics]) -> float:
    """
    Aggregate complexity across the files that evidence one skill.

    LOC-weighted, so a 500-line service dominates a 20-line helper, but the
    weight is sqrt(loc) rather than loc: without the damping a single huge
    file would decide the score for the whole skill.
    """
    usable = [m for m in metrics_list if m.loc >= 15 and m.analyzed_with != "failed"]
    if not usable:
        return 0.0

    total_weight = 0.0
    total = 0.0
    for metrics in usable:
        band = _complexity_band(metrics.cyclomatic_per_function)
        band *= _structure_modifier(metrics)
        if metrics.analyzed_with not in _EXACT_ANALYSERS:
            band *= HEURISTIC_CONFIDENCE
        weight = metrics.loc ** 0.5
        total += band * weight
        total_weight += weight

    return min(1.0, total / total_weight) if total_weight else 0.0


def craft_score(metrics_list: list[CodeMetrics], repos: list[RepoEvidence]) -> float:
    """Repo-level engineering practice, blended with per-file signals."""
    if not metrics_list and not repos:
        return 0.0

    has_tests = any(r.has_tests for r in repos)
    has_ci = any(r.has_ci for r in repos)
    has_readme = any(r.has_readme for r in repos)

    files = [m for m in metrics_list if m.loc >= 15]
    if files:
        error_handling = sum(1 for m in files if m.has_error_handling) / len(files)
        documented = sum(1 for m in files if m.has_docstrings or m.comment_ratio >= 0.05) / len(files)
        typed = sum(1 for m in files if m.has_type_annotations) / len(files)
        duplication = sum(m.duplicate_block_ratio for m in files) / len(files)
    else:
        error_handling = documented = typed = duplication = 0.0

    score = (
        0.30 * (1.0 if has_tests else 0.0)
        + 0.20 * error_handling
        + 0.15 * (1.0 if has_ci else 0.0)
        + 0.10 * documented
        + 0.10 * typed
        + 0.15 * (1.0 - min(1.0, duplication * 2.0))
    )
    # A README is table stakes, not craft; worth a nudge, not a component.
    if has_readme:
        score = min(1.0, score + 0.03)
    return round(min(1.0, score), 4)


def depth_score(loc_analyzed: int, files: int, repos: int) -> float:
    """
    Volume of real code behind a claim, log-scaled and capped.

    Anchors: ~200 LOC across 2 files in 1 repo ≈ 0.5 (a real feature);
    ~2000 LOC across 8 files in 3 repos ≈ 1.0 (sustained use). Log scaling
    because the difference between 50 and 500 lines is enormous and the
    difference between 5,000 and 50,000 is noise — usually vendored code
    that slipped past the exclusion patterns anyway.
    """
    if loc_analyzed <= 0:
        return 0.0

    import math

    volume = math.log10(1 + loc_analyzed) / math.log10(1 + 2000)      # 2000 LOC -> 1.0
    spread = math.log10(1 + files) / math.log10(1 + 8)                # 8 files   -> 1.0
    reach = math.log10(1 + repos) / math.log10(1 + 3)                 # 3 repos   -> 1.0
    combined = 0.5 * volume + 0.3 * spread + 0.2 * reach
    return round(min(1.0, combined), 4)


def recency_score(months: float, *, half_life: float = 14.0) -> float:
    """
    Exponential decay on the last commit touching this skill.

    Half-life of 14 months is chosen against the population being scored:
    final-year undergraduates, whose most recent work is coursework from the
    last two semesters. A 6-month half-life (common in industry hiring
    models) would zero out a strong second-year project that is genuinely
    representative of what the candidate can do. Skills do not evaporate;
    the score should reflect "when did they last prove it", not punish
    anyone who spent a semester on theory papers.
    """
    if months >= 900:
        return 0.0
    return round(0.5 ** (months / half_life), 4)
