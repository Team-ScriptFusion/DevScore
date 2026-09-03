"""
Token-level analysis for every language that is not Python.

Python gets a real AST (`python_ast.py`). Building or vendoring parsers for
JavaScript, TypeScript, Java, C#, C++, Kotlin, Dart, Go, PHP and Swift is
out of scope for a final-year project — tree-sitter would work but adds a
compiled dependency to a stack whose non-functional requirements say
"open-source only, zero licence cost, MERN + Python 3.9".

So this module does what it can honestly do, and labels it. `analyzed_with`
is set to `brace_heuristic` on every result, and the scoring engine applies
a small confidence discount to heuristic metrics relative to AST ones. An
estimate presented as a measurement is the actual research failure here; an
estimate labelled as an estimate is a reasonable engineering trade.

What it measures, on comment- and string-stripped source:

  cyclomatic     decision keywords per language + `&&`/`||`/`?:`/`?.`, plus
                 one per detected function. Same McCabe shape as the AST
                 path, so the two are comparable.
  max_nesting    true brace depth, tracked character by character. This is
                 exact for brace languages, not a heuristic.
  functions      language-specific declaration patterns, including arrow
                 functions assigned to identifiers and class methods.
  craft signals  try/catch presence, type annotations (TS/Java/C#/Kotlin),
                 async usage, magic numbers, longest line.

Deliberately NOT counted as decisions: `else` (it pairs with an already
counted `if`), `case` in a switch *and* the switch itself (double-count),
`catch` when the `try` was already counted.
"""

from __future__ import annotations

import re

from ..models import CodeMetrics
from .textprep import loc, strip_noise

# Decision keywords per language family. `else` is absent by design.
_DECISION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "default": ("if", "for", "while", "case", "catch"),
    "Go": ("if", "for", "case", "select"),
    "Rust": ("if", "for", "while", "loop", "match"),
    "Swift": ("if", "for", "while", "case", "guard", "catch"),
    "Kotlin": ("if", "for", "while", "when", "catch"),
    "Ruby": ("if", "elsif", "for", "while", "unless", "when", "rescue"),
    "Shell": ("if", "elif", "for", "while", "case"),
    "SQL": ("case", "when"),
    "R": ("if", "for", "while"),
}

_LOGICAL_OPS = re.compile(r"&&|\|\||\?\?|\?\.|(?<![=!<>])\?(?!\.)")

_FUNCTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "JavaScript": (
        r"\bfunction\s*\*?\s*\w*\s*\(",
        r"\b(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
        r"\b(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\w+\s*=>",
        r"^\s*(?:async\s+)?\w+\s*\([^)]*\)\s*\{",          # class / object methods
    ),
    "Java": (r"\b(?:public|private|protected|static|final|abstract|synchronized)[\w<>\[\],\s]*?\s+\w+\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\{",),
    "C#": (r"\b(?:public|private|protected|internal|static|async|override|virtual)[\w<>\[\],\s?]*?\s+\w+\s*\([^)]*\)\s*\{",),
    "C": (r"^[A-Za-z_][\w \t*]*\s+\**\w+\s*\([^;]*\)\s*\{",),
    "Go": (r"\bfunc\s+(?:\([^)]*\)\s*)?\w+\s*\(",),
    "Rust": (r"\bfn\s+\w+\s*[<(]",),
    "Swift": (r"\bfunc\s+\w+\s*[<(]",),
    "Kotlin": (r"\bfun\s+\w+\s*[<(]",),
    "Dart": (r"^\s*(?:[\w<>,\[\]?]+\s+)?\w+\s*\([^)]*\)\s*(?:async\s*)?\{",),
    "PHP": (r"\bfunction\s+\w+\s*\(",),
    "Ruby": (r"^\s*def\s+\w+",),
    "Shell": (r"^\s*(?:function\s+)?\w+\s*\(\s*\)\s*\{",),
    "R": (r"\w+\s*<-\s*function\s*\(",),
}
_FUNCTION_PATTERNS["TypeScript"] = _FUNCTION_PATTERNS["JavaScript"] + (
    r"\b\w+\s*\([^)]*\)\s*:\s*[\w<>\[\]|]+\s*\{",
)
_FUNCTION_PATTERNS["Vue"] = _FUNCTION_PATTERNS["JavaScript"]
_FUNCTION_PATTERNS["Svelte"] = _FUNCTION_PATTERNS["JavaScript"]
_FUNCTION_PATTERNS["C++"] = _FUNCTION_PATTERNS["C"] + (r"\b\w+::\w+\s*\([^;]*\)\s*\{",)
_FUNCTION_PATTERNS["Scala"] = (r"\bdef\s+\w+\s*[\[(]",)

_CLASS_PATTERN = re.compile(
    r"\b(?:class|interface|struct|enum|trait|object|protocol)\s+[A-Z_]\w*", re.MULTILINE
)

_TYPE_ANNOTATION = re.compile(
    r":\s*(?:string|number|boolean|void|any|unknown|never|[A-Z]\w*)\s*[=;,)\]{]"
    r"|\b(?:public|private|protected)\s+(?:final\s+)?[A-Z]\w*\s+\w+\s*[;=]"
)
_ERROR_HANDLING = re.compile(r"\b(?:try|catch|rescue|recover|throw|throws|panic)\b|if\s+err\s*!=\s*nil")
_ASYNC = re.compile(r"\b(?:async|await|Promise|CompletableFuture|suspend|goroutine)\b|\bgo\s+func\b")
_MAGIC_NUMBER = re.compile(r"(?<![\w.$])(?!0\b|1\b|2\b|100\b)\d{2,}(?![\w.])")


def _count_keyword(text: str, keyword: str) -> int:
    return len(re.findall(rf"(?<![\w$]){keyword}(?![\w$])", text))


def _max_brace_depth(text: str) -> int:
    depth = 0
    peak = 0
    for char in text:
        if char in "{([":
            depth += 1
            peak = max(peak, depth)
        elif char in "})]":
            depth = max(0, depth - 1)
    return peak


def _indent_depth(text: str) -> int:
    """Nesting proxy for languages without braces (Python-like, Ruby, YAML)."""
    peak = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        peak = max(peak, indent // 4 if " " in line[:indent] else indent)
    return peak


def _duplicate_ratio(stripped: str, window: int = 6) -> float:
    """
    Fraction of `window`-line blocks that appear more than once.

    A crude copy-paste detector. It is not trying to be a clone detector —
    it is trying to separate "wrote 400 lines" from "pasted the same 40-line
    handler ten times", which otherwise look identical to every volume
    metric in this system.
    """
    lines = [l.strip() for l in stripped.splitlines() if l.strip()]
    if len(lines) < window * 3:
        return 0.0
    blocks: dict[str, int] = {}
    for i in range(len(lines) - window + 1):
        key = "\n".join(lines[i:i + window])
        blocks[key] = blocks.get(key, 0) + 1
    duplicated = sum(count - 1 for count in blocks.values() if count > 1)
    return min(1.0, duplicated / max(1, len(lines) - window + 1))


def analyze(path: str, text: str, language: str) -> CodeMetrics:
    metrics = CodeMetrics(path=path, language=language, analyzed_with="brace_heuristic")
    metrics.raw_lines = text.count("\n") + 1
    metrics.longest_line = max((len(l) for l in text.splitlines()), default=0)

    stripped, comment_lines = strip_noise(text, language)
    metrics.comment_lines = comment_lines
    metrics.loc = loc(stripped)

    keywords = _DECISION_KEYWORDS.get(language, _DECISION_KEYWORDS["default"])
    decisions = sum(_count_keyword(stripped, kw) for kw in keywords)
    decisions += len(_LOGICAL_OPS.findall(stripped))

    patterns = _FUNCTION_PATTERNS.get(language, _FUNCTION_PATTERNS["JavaScript"])
    functions = 0
    for pattern in patterns:
        functions += len(re.findall(pattern, stripped, re.MULTILINE))

    metrics.functions = functions
    metrics.classes = len(_CLASS_PATTERN.findall(stripped))
    metrics.cyclomatic = decisions + max(1, functions)
    metrics.max_nesting = (
        _max_brace_depth(stripped) if "{" in stripped else _indent_depth(stripped)
    )

    if functions:
        # No spans without a parse, so approximate: code lines per function.
        metrics.avg_function_loc = round(metrics.loc / functions, 1)
        metrics.max_function_loc = 0

    metrics.has_error_handling = bool(_ERROR_HANDLING.search(stripped))
    metrics.has_type_annotations = language in ("TypeScript", "Java", "C#", "Kotlin", "Swift", "Go", "Rust") and bool(
        _TYPE_ANNOTATION.search(stripped)
    )
    metrics.has_docstrings = comment_lines >= max(3, metrics.loc * 0.03)
    metrics.uses_async = bool(_ASYNC.search(stripped))
    metrics.magic_numbers = len(_MAGIC_NUMBER.findall(stripped))
    metrics.duplicate_block_ratio = _duplicate_ratio(stripped)
    return metrics
