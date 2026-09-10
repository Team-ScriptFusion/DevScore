"""
Exact Python analysis via the standard-library `ast` module.

The SDS names this explicitly: "the system walks the Abstract Syntax Tree of
candidate code files to quantify complexity (loops, conditionals, modular
design) and verify seniority, rather than trusting language labels alone."
For Python we can do that literally — no heuristics, no approximation.

Cyclomatic complexity here is McCabe's: one per unit of control flow, plus
one for each decision point. Decision points counted:

    if / elif            each ast.If
    for / while          each loop (plus `orelse` when present)
    except handler       each ast.ExceptHandler
    with                 not counted — it is not a branch
    boolean operator     `and`/`or` add (len(values) - 1) each, because each
                         short-circuits and creates a path
    ternary              ast.IfExp
    comprehension `if`   each filter clause
    match case           each ast.match_case
    assert               a branch that can terminate

`with` is deliberately excluded even though several toy complexity counters
include it: a context manager is not a decision, and counting it rewards
`with open(...)` boilerplate as if it were logic.
"""

from __future__ import annotations

import ast
import re

from ..models import CodeMetrics
from .textprep import loc, strip_noise

_MAGIC_NUMBER = re.compile(r"(?<![\w.])(?!0\b|1\b|2\b|100\b)\d{2,}(?![\w.])")


class _Walker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.decisions = 0
        self.functions = 0
        self.classes = 0
        self.max_nesting = 0
        self.has_try = False
        self.has_raise = False
        self.docstrings = 0
        self.annotated = 0
        self.uses_async = False
        self.function_spans: list[int] = []
        self._depth = 0

    # -- nesting -------------------------------------------------------------

    def _nested(self, node: ast.AST) -> None:
        self._depth += 1
        self.max_nesting = max(self.max_nesting, self._depth)
        self.generic_visit(node)
        self._depth -= 1

    # -- decision points -----------------------------------------------------

    def visit_If(self, node: ast.If) -> None:
        self.decisions += 1
        self._nested(node)

    def visit_For(self, node: ast.For) -> None:
        self.decisions += 1 + (1 if node.orelse else 0)
        self._nested(node)

    visit_AsyncFor = visit_For  # type: ignore[assignment]

    def visit_While(self, node: ast.While) -> None:
        self.decisions += 1 + (1 if node.orelse else 0)
        self._nested(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.has_try = True
        self.decisions += len(node.handlers)
        self._nested(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.has_raise = True
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.decisions += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.decisions += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.decisions += 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.decisions += len(node.ifs)
        self.generic_visit(node)

    if hasattr(ast, "match_case"):  # Python 3.10+
        def visit_match_case(self, node) -> None:  # type: ignore[no-untyped-def]
            self.decisions += 1
            self.generic_visit(node)

    # -- structure -----------------------------------------------------------

    def _function(self, node) -> None:  # type: ignore[no-untyped-def]
        self.functions += 1
        if ast.get_docstring(node):
            self.docstrings += 1
        if node.returns is not None or any(
            a.annotation is not None for a in node.args.args + node.args.kwonlyargs
        ):
            self.annotated += 1
        end = getattr(node, "end_lineno", None) or node.lineno
        self.function_spans.append(max(1, end - node.lineno + 1))
        self._nested(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.uses_async = True
        self._function(node)

    def visit_Await(self, node: ast.Await) -> None:
        self.uses_async = True
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes += 1
        if ast.get_docstring(node):
            self.docstrings += 1
        self._nested(node)


def analyze(path: str, text: str) -> CodeMetrics:
    metrics = CodeMetrics(path=path, language="Python", analyzed_with="python_ast")
    metrics.raw_lines = text.count("\n") + 1
    stripped, comment_lines = strip_noise(text, "Python")
    metrics.comment_lines = comment_lines
    metrics.loc = loc(stripped)
    metrics.longest_line = max((len(l) for l in text.splitlines()), default=0)
    metrics.magic_numbers = len(_MAGIC_NUMBER.findall(stripped))

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError) as exc:
        # Python 2 files, templated .py, or a truncated fetch. Record it and
        # fall back to the brace/keyword heuristic rather than dropping the
        # file — a file we cannot parse is still a file the candidate wrote.
        from .brace import analyze as brace_analyze

        fallback = brace_analyze(path, text, "Python")
        fallback.parse_error = f"{exc.__class__.__name__}: {exc}"
        fallback.analyzed_with = "brace_heuristic (ast parse failed)"
        return fallback

    walker = _Walker()
    walker.visit(tree)

    units = max(1, walker.functions)
    metrics.cyclomatic = walker.decisions + units
    metrics.max_nesting = walker.max_nesting
    metrics.functions = walker.functions
    metrics.classes = walker.classes
    metrics.avg_function_loc = (
        sum(walker.function_spans) / len(walker.function_spans) if walker.function_spans else 0.0
    )
    metrics.max_function_loc = max(walker.function_spans, default=0)
    metrics.has_error_handling = walker.has_try or walker.has_raise
    metrics.has_docstrings = walker.docstrings > 0
    metrics.has_type_annotations = walker.annotated > 0
    metrics.uses_async = walker.uses_async
    return metrics
