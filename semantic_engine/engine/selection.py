"""
Candidate roster and selection.

Scoring a whole cohort is the research workflow. The *working* workflow is
"score these four people" — a recruiter shortlisting, or a developer iterating
on the weights without burning forty minutes and 2,000 API calls per run.

This module builds the roster once (resume parsing only, no GitHub calls, so
it is fast and free) and resolves a selection expression against it:

    "3"              one candidate by index
    "1,4,9"          several
    "5-12"           an inclusive range
    "1,4,7-12"       mixed
    "jayasuriya"     substring match on name, handle or filename
    "all"            everything

Index numbers come from `cli.py scan`, which prints the roster in the same
stable order (sorted by filename) that every other command uses. Matching is
case-insensitive and accent-blind enough for this dataset; an expression that
resolves to nothing is an error rather than a silent empty run, because
"scored 0 candidates" looks identical to "scored everything successfully" in a
log file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .resume.parser import parse_resume

# ---------------------------------------------------------------------------
# Handle overrides
# ---------------------------------------------------------------------------
#
# Some CVs name no GitHub account at all — the candidate simply left the link
# off, or wrote "GitHub" as a skill without a URL. The parser is right to
# return nothing (guessing a handle is the one thing worse than having none:
# it scores someone against a stranger's repositories). But "no handle in the
# CV" is not the same as "no GitHub account", and a recruiter or the research
# team often knows the real one.
#
# `<cv-folder>/handle_overrides.json` supplies them, keyed by the CV's exact
# filename:
#
#     {
#       "Binara Silva - Software Engineer Undergraduate CV (2) - Binara Silva.pdf": {
#         "github": "BinaraSilva",
#         "note": "CV omits the GitHub URL; handle confirmed by the team 2026-09-03"
#       }
#     }
#
# An override is recorded as `handle_source = "override"` and shown in the
# roster, so a score built on a supplied handle is never mistaken for one the
# candidate put on their own CV. An override always wins over a handle found
# in the CV — it is a deliberate correction, and the pre-fix data had at
# least one CV pointing at the wrong person's account.

OVERRIDES_FILENAME = "handle_overrides.json"

_GITHUB_HANDLE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def load_handle_overrides(folder: str | Path) -> dict[str, dict[str, str]]:
    """
    Read `<folder>/handle_overrides.json`. Returns {} when absent.

    A `github` value may be a bare handle or a full github.com URL; both are
    normalised to the bare handle. A malformed entry is skipped with a
    warning rather than aborting — one bad row must not block a cohort run.
    """
    path = Path(folder) / OVERRIDES_FILENAME
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: could not read {path}: {exc}")
        return {}
    if not isinstance(raw, dict):
        print(f"warning: {path} is not a JSON object; ignoring")
        return {}

    cleaned: dict[str, dict[str, str]] = {}
    for filename, spec in raw.items():
        if filename.startswith("_"):
            continue  # "_comment" and friends — documentation, not an entry
        if isinstance(spec, str):
            spec = {"github": spec}
        if not isinstance(spec, dict) or not spec.get("github"):
            print(f"warning: {path}: entry for {filename!r} has no 'github' value; skipped")
            continue
        handle = str(spec["github"]).strip()
        match = re.search(r"github\.com/([A-Za-z0-9-]+)", handle)
        if match:
            handle = match.group(1)
        handle = handle.lstrip("@")
        if not _GITHUB_HANDLE_RE.match(handle):
            print(f"warning: {path}: {handle!r} is not a valid GitHub handle; skipped")
            continue
        cleaned[filename] = {"github": handle, "note": str(spec.get("note", "")).strip()}
    return cleaned


@dataclass
class RosterEntry:
    index: int
    path: Path
    name: str                 # from the CV itself where possible
    name_source: str          # cv | filename
    filename_label: str       # what the Drive filename claims
    github_username: str | None
    skill_count: int
    status: str
    handle_source: str = "cv"       # cv | override | none
    handle_note: str = ""           # why an override was applied

    @property
    def name_disputed(self) -> bool:
        """
        True when the CV's own name and the filename's name share no words.

        In the collected dataset this reliably means someone uploaded a peer's
        CV and Drive appended the uploader's name. Worth surfacing: it is the
        difference between "this is Anura's score" and "this is Binara's score".
        """
        if self.name_source != "cv":
            return False
        a = {w for w in re.split(r"\W+", self.name.lower()) if len(w) > 2}
        b = {w for w in re.split(r"\W+", self.filename_label.lower()) if len(w) > 2}
        return bool(a and b and not (a & b))

    @property
    def scorable(self) -> bool:
        return bool(self.github_username)


def _filename_label(path: Path) -> str:
    mojibake = {"â€”": "—", "â€“": "–", "â€™": "’"}
    stem = path.stem
    for bad, good in mojibake.items():
        stem = stem.replace(bad, good)
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)
    if re.search(r"\s[—–]\s", stem):
        stem = re.split(r"\s[—–]\s", stem)[0]
    elif " - " in stem:
        stem = stem.rsplit(" - ", 1)[-1]
    stem = re.sub(r"\b(cv|resume|curriculum vitae)\b", "", stem, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", stem).strip(" _-.") or path.stem


def build_roster(folder: str | Path) -> list[RosterEntry]:
    """Parse every CV in `folder` (no network) and return the indexed roster."""
    overrides = load_handle_overrides(folder)
    entries: list[RosterEntry] = []
    for index, pdf in enumerate(sorted(Path(folder).glob("*.pdf")), start=1):
        profile = parse_resume(pdf)
        label = _filename_label(pdf)

        handle = profile.github_username
        handle_source = "cv" if handle else "none"
        handle_note = ""
        override = overrides.get(pdf.name)
        if override:
            handle = override["github"]
            handle_source = "override"
            handle_note = override["note"]

        entries.append(RosterEntry(
            index=index,
            path=pdf,
            name=profile.person_name or label,
            name_source=profile.name_source,
            filename_label=label,
            github_username=handle,
            skill_count=sum(1 for c in profile.claimed if c.recognised and c.verifiable),
            status=profile.status,
            handle_source=handle_source,
            handle_note=handle_note,
        ))
    return entries


class SelectionError(ValueError):
    """The expression matched nothing, or could not be parsed."""


def _parse_indices(token: str) -> set[int] | None:
    token = token.strip()
    if re.fullmatch(r"\d+", token):
        return {int(token)}
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            low, high = high, low
        return set(range(low, high + 1))
    return None


def select(roster: list[RosterEntry], expression: str | None) -> list[RosterEntry]:
    """
    Resolve a selection expression against the roster, preserving roster order.

    Index tokens and text tokens can be mixed freely; a text token that looks
    like a number is treated as an index, so `--select 5` never accidentally
    matches a candidate whose filename contains "5".
    """
    if not expression or expression.strip().lower() == "all":
        return list(roster)

    by_index = {entry.index: entry for entry in roster}
    chosen: set[int] = set()
    unmatched: list[str] = []

    for token in (t for t in expression.split(",") if t.strip()):
        indices = _parse_indices(token)
        if indices is not None:
            valid = indices & by_index.keys()
            if not valid:
                unmatched.append(token.strip())
            chosen |= valid
            continue

        needle = token.strip().lower()
        hits = {
            entry.index for entry in roster
            if needle in entry.name.lower()
            or needle in (entry.github_username or "").lower()
            or needle in entry.filename_label.lower()
            or needle in entry.path.name.lower()
        }
        if not hits:
            unmatched.append(token.strip())
        chosen |= hits

    if unmatched:
        raise SelectionError(
            "no candidate matched: " + ", ".join(repr(u) for u in unmatched)
            + f"  (roster has {len(roster)} entries; run `cli.py scan <folder>` to list them)"
        )
    if not chosen:
        raise SelectionError(f"selection {expression!r} resolved to no candidates")

    return [entry for entry in roster if entry.index in chosen]
