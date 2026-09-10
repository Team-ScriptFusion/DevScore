"""
Comment and string stripping.

This is small and boring and the entire analysis depends on it being right.

Two independent things break without it:

  EVIDENCE.  The premise of the project is that resume claims are cheap and
  code is not. If we search raw source for the React marker `useState(`, a
  file containing

        // TODO: migrate this to useState() one day
        const config = "useState(";

  counts as proof the candidate writes React. It is proof they typed the
  word. Every marker regex in the ontology is matched against *stripped*
  source for exactly this reason, and it is why a README mentioning fifteen
  technologies contributes nothing to the score.

  COMPLEXITY.  Decision-point counting is keyword counting. A file with a
  long block comment discussing `if`/`else` cases, or a SQL string
  containing `CASE WHEN`, scores as complex code. Strip first, count after.

The stripper is regex-based, not a parser. It handles line comments, block
comments, single/double-quoted strings with escapes, template literals, and
Python triple-quotes. It does not handle every pathological case (regex
literals containing quotes, nested template interpolation) and does not need
to: an occasional mis-strip shifts one file's metrics slightly, whereas not
stripping at all shifts the entire result systematically.
"""

from __future__ import annotations

import re

_HASH_COMMENT_LANGS = {"Python", "Shell", "Ruby", "R", "Perl", "YAML"}
_DASH_COMMENT_LANGS = {"SQL", "Haskell", "Lua"}

# Order matters: block comments before line comments before strings, so a
# "//" inside a block comment is consumed by the block rule.
_C_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_C_LINE = re.compile(r"//[^\n]*")
_HASH_LINE = re.compile(r"#[^\n]*")
_DASH_LINE = re.compile(r"--[^\n]*")
_HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")

_PY_TRIPLE = re.compile(r"('''|\"\"\")[\s\S]*?\1")
_TEMPLATE = re.compile(r"`(?:\\.|[^`\\])*`")
_DQ = re.compile(r'"(?:\\.|[^"\\\n])*"')
_SQ = re.compile(r"'(?:\\.|[^'\\\n])*'")


def _count_comment_lines(original: str, stripped: str) -> int:
    """Lines that lost content to comment removal."""
    count = 0
    for before, after in zip(original.splitlines(), stripped.splitlines()):
        if before.strip() and not after.strip():
            count += 1
    return count


def strip_noise(text: str, language: str) -> tuple[str, int]:
    """
    Return (code with comments and string bodies blanked, comment line count).

    String *literals* are replaced with empty quotes rather than deleted, so
    line and column structure survives and syntax stays roughly intact for
    the brace-depth walker.
    """
    if not text:
        return "", 0

    working = text

    if language in ("HTML", "Vue", "Svelte"):
        working = _HTML_COMMENT.sub("", working)

    if language == "Python":
        working = _PY_TRIPLE.sub('""', working)
        working = _HASH_LINE.sub("", working)
    elif language in _HASH_COMMENT_LANGS:
        working = _HASH_LINE.sub("", working)
    elif language in _DASH_COMMENT_LANGS:
        working = _C_BLOCK.sub("", working)
        working = _DASH_LINE.sub("", working)
    else:
        working = _C_BLOCK.sub("", working)
        working = _C_LINE.sub("", working)

    comment_lines = _count_comment_lines(text, working)

    working = _TEMPLATE.sub("``", working)
    working = _DQ.sub('""', working)
    if language != "Python":
        # Python's ' and " are interchangeable; for C-likes an apostrophe in
        # a stripped comment is gone already, so this is safe here too.
        working = _SQ.sub("''", working)
    else:
        working = _SQ.sub("''", working)

    return working, comment_lines


def loc(text: str) -> int:
    """Non-blank lines of the stripped source."""
    return sum(1 for line in text.splitlines() if line.strip())
