"""
Project extraction — the CV's "Projects" section, entry by entry.

Skill extraction answers "does this CV claim React?" Project extraction answers
the sharper question: "*which project* does the CV say the React was for?"

That distinction matters because the two produce different kinds of finding:

    skill-level    "React: no public evidence"        — we have no proof
    project-level  "Lanka Mall claims React + Node +  — we have proof this
                    MongoDB; its bound repo has         specific claim does not
                    no backend code at all"             match this specific repo

The second is falsifiable in a way the first is not, and it is what
`matching/binding.py` needs.

`cv_parser` does not do this — it scans the whole document and returns one flat
skill set, which is correct for its job (Implementation 01 stores a claimed-skill
list, not a project graph). So this module slices the section itself and then
hands each entry's text back to `cv_parser.dictionary_scan`, so the *vocabulary*
is still entirely the team's. Nothing here re-implements skill detection.

------------------------------------------------------------------------
WHAT REAL CVs LOOK LIKE
------------------------------------------------------------------------
Built against the collected cohort, not against an idea of a CV:

    • SmartLog – Smart Logging & Monitoring System (Final Year Project)
    - Developing a system to manage and monitor logs ...

    Smart Waste Bin Monitoring and Prediction System - Final Year Research
    Technologies: Python • ARIMA • Node.js • ESP32 IoT • Docker
    ▪ Enhanced waste prediction using ARIMA ...

    Lanka Mall E-Commerce Platform 2022
    Full Stack Web Application
    – Frontend built using React.js and Tailwind CSS with backend ...
    – GitHub: github.com/some-user/my-ecommerce-site

Four things fall out of that:

  1. A `Technologies:` / `Tech Stack:` line is the candidate explicitly
     attributing a stack to one project — a stronger attribution than a
     technology merely mentioned in prose.
  2. Some entries carry their own GitHub URL. That is an EXPLICIT binding —
     the candidate pointing at the repo themselves — and beats any amount of
     fuzzy title matching.
  3. Bullet style is consistent and load-bearing: a round bullet opens an
     ENTRY, a dash or square opens a DESCRIPTION under it.
  4. Multi-column PDFs interleave unrelated text into the section. Entries are
     capped and prose is rejected, because a wrong binding is worse than none —
     and a junk title that matches no repository simply never binds, which is
     the safety net behind all of this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

PROJECT_HEADERS = (
    "projects", "project", "academic projects", "personal projects",
    "key projects", "selected projects", "project experience", "notable projects",
    "key projects & achievements", "research projects", "portfolio projects",
    "major projects", "mini projects",
)

# Headers that end the Projects section.
STOP_HEADERS = (
    "education", "experience", "work experience", "professional experience",
    "employment", "certifications", "certification", "achievements", "awards",
    "references", "contact", "summary", "profile", "objective", "career objective",
    "interests", "hobbies", "activities", "publications", "volunteering",
    "extracurricular", "languages", "personal details", "declaration", "skills",
    "technical skills", "soft skills", "areas of expertise",
    "volunteer experience", "volunteer", "leadership", "co-curricular",
    "extra curricular", "extra-curricular", "societies", "workshops",
    "seminars", "training", "internship", "internships",
)

# Bullet discrimination. Across the collected CVs the convention holds: a round
# bullet opens an ENTRY, while dashes and squares open a DESCRIPTION line under
# it. Treating all bullets alike split one project into one-per-bullet and
# destroyed the skill attribution for every entry.
_BULLET = re.compile(r"^[•▪●◦‣⁃*>\-–—]+\s*")
_TITLE_BULLET = re.compile(r"^[•●]\s*")
_DESC_BULLET = re.compile(r"^[▪▫◦‣⁃*>\-–—]\s*")

# A line that is mostly a URL is a link, not a project name.
_URL_LINE = re.compile(
    r"^(github|gitlab|link|url|repo|repository|demo|live|source|website)\s*[:\-–—]"
    r"|^\s*(https?://|www\.)"
    r"|^\s*github\.com/",
    re.IGNORECASE,
)

# "Technologies: Python • Node.js" / "Tech Stack — React, Express"
_TECH_LINE = re.compile(
    r"^(technolog(?:y|ies)|tech\s*stack|stack|tools?|built\s+with|tech)\s*[:\-–—]\s*(.+)$",
    re.IGNORECASE,
)

_GITHUB_IN_TEXT = re.compile(
    r"github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]+)", re.IGNORECASE
)

# Trailing noise on a title line: a month+year, a year range, a bare year, a
# parenthetical.
#
# NOTE: deliberately NOT re.IGNORECASE. An earlier version was, which made
# [A-Z][a-z]{2} match any three letters, so the month rule ate "orm 2022" out of
# "Lanka Mall E-Commerce Platform 2022" and left the title as "Lanka Mall
# E-Commerce Platf". Month names are spelled out instead.
_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
_TITLE_NOISE = re.compile(
    r"\s*(\(?(?:" + _MONTHS + r")[a-z]*\.?\s+\d{4}\)?"
    r"|\b(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|[Pp]resent)\b"
    r"|\b(?:19|20)\d{2}\b"
    r"|\([^)]{0,40}\))\s*$"
)

# Words that open a description line, never a project name.
_CONTINUATION = re.compile(
    r"^(developed|developing|built|building|created|creating|implemented|implementing|"
    r"designed|designing|used|using|worked|working|responsible|collaborat|participat|"
    r"performed|conducted|integrated|deployed|managed|led|added|enhanced|improved|"
    r"focused|contributed|maintained|supported|coordinated|verified|demonstrat|"
    r"independently|successfully|currently|also|additionally|furthermore|"
    r"achiev|deliver|applied|utiliz|handled|assisted|ensured|reduced|increased|"
    r"constructed|constructing|engineered|architected|programmed|wrote|writing|"
    r"produced|established|introduced|refactored|migrated|optimis|optimiz|"
    r"and|with|for|the|a|an|this|it|features?|technolog|experience)\b",
    re.IGNORECASE,
)

MAX_SECTION_LINES = 60
MAX_ENTRY_LINES = 12
MAX_PROJECTS = 12


@dataclass
class CVProject:
    """One entry from the CV's Projects section."""

    title: str
    body: str = ""
    # cv_parser canonical skill names found anywhere in this entry.
    skills: list[str] = field(default_factory=list)
    # Skills the candidate explicitly listed on a "Technologies:" line — a
    # stronger attribution than a name appearing in prose.
    declared_stack: list[str] = field(default_factory=list)
    # "owner/repo" when the entry carries its own GitHub URL.
    explicit_repo: str | None = None

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}".strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_header(line: str, headers: tuple[str, ...]) -> bool:
    stripped = line.strip().lower().strip(":-–— ")
    # 60, not 45: "Experience in Academic / Extra Curricular Projects" is a real
    # section header in this cohort at 49 characters, and missing it let a
    # volunteering section leak in as three phantom projects.
    if not stripped or len(stripped) > 60:
        return False
    return any(stripped == h or stripped.startswith(h + " ") for h in headers)


def _slice_projects_section(text: str) -> list[str]:
    lines = [l.rstrip() for l in text.split("\n")]
    start = None
    for i, line in enumerate(lines):
        if _is_header(line, PROJECT_HEADERS):
            start = i + 1
            break
    if start is None:
        return []

    end = min(len(lines), start + MAX_SECTION_LINES)
    for j in range(start, end):
        if _is_header(lines[j], STOP_HEADERS):
            end = j
            break
    return lines[start:end]


def _has_body_ahead(following: list[str], window: int = 3) -> bool:
    """
    Is there a description bullet or a Technologies: line just below?

    This is the structural signal that separates a real title from a wrapped
    prose line, and the window tolerates the common "title / subtitle / bullets"
    layout where the first bullet is two lines down rather than one.
    """
    seen = 0
    for line in following:
        text = line.strip()
        if not text:
            continue
        seen += 1
        if seen > window:
            break
        if _DESC_BULLET.match(text) or _TECH_LINE.match(_BULLET.sub("", text).strip()):
            return True
    return False


def _looks_like_title(line: str, following: list[str]) -> bool:
    """
    A project title, as opposed to a wrapped description line.

    Getting this wrong in the permissive direction is the expensive failure: a
    description line promoted to a title splits one project in two and wrecks
    the skill attribution for both halves. So an unbulleted candidate has to
    earn it by having a description bullet or a Technologies: line beneath it.
    """
    raw = line.strip()
    if _DESC_BULLET.match(raw):
        return False                      # a dash/square bullet is a description
    if _URL_LINE.search(raw):
        return False                      # "GitHub: github.com/..." is a link

    stripped = _BULLET.sub("", raw).strip()
    if not (4 <= len(stripped) <= 110):
        return False
    if _TECH_LINE.match(stripped) or not stripped[0].isupper():
        return False
    if _CONTINUATION.match(stripped):
        return False

    words = stripped.split()
    # 14, not 10. Real titles in this cohort run long because candidates append
    # the institution: "Smart Waste Bin Monitoring and Prediction System - SLIIT
    # Final Year Research" is 11 words. Capping at 10 rejected it, and a
    # rejected title does not just lose itself — the following entry absorbs its
    # body, so one bad cap corrupted the stack attribution for two projects.
    # Prose is held back by _CONTINUATION and the body-ahead requirement instead.
    if not (2 <= len(words) <= 14):
        return False
    if stripped.endswith((".", ";")) and len(words) > 5:
        return False                      # a sentence, not a name

    if _TITLE_BULLET.match(raw):
        return True                       # round bullet opens an entry outright
    return _has_body_ahead(following)


def _clean_title(line: str) -> str:
    title = _BULLET.sub("", line).strip()
    title = _TITLE_NOISE.sub("", title).strip()
    # "SmartLog – Smart Logging & Monitoring System" keeps both halves, but
    # "X - Final Year Research" is an institution tag, not part of the name.
    title = re.sub(
        r"\s*[-–—|]\s*(final year|research project|research|university|institute|"
        r"academic|individual|group|team|personal)\b.*$",
        "", title, flags=re.IGNORECASE,
    ).strip()
    return re.sub(r"\s{2,}", " ", title).strip(" .,:;-–—|")


def extract_projects(text: str, dictionary_scan) -> list[CVProject]:
    """
    Slice the Projects section into entries.

    `dictionary_scan` is injected — it is `cv_parser.dictionary_scan`, passed in
    rather than imported, so this module never becomes a second place where
    skill vocabulary lives. It returns a set of canonical skill names.
    """
    lines = _slice_projects_section(text)
    if not lines:
        return []

    entries: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_body: list[str] = []

    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if _looks_like_title(line, lines[index + 1:]) and (current_title is None or current_body):
            if current_title is not None:
                entries.append((current_title, current_body))
            current_title = line
            current_body = []
        elif current_title is not None:
            if len(current_body) < MAX_ENTRY_LINES:
                current_body.append(line)
    if current_title is not None:
        entries.append((current_title, current_body))

    projects: list[CVProject] = []
    for raw_title, body_lines in entries[:MAX_PROJECTS]:
        title = _clean_title(raw_title)
        if len(title.split()) < 2:
            continue

        body = "\n".join(body_lines)
        whole = f"{title}\n{body}"

        declared: set[str] = set()
        for line in body_lines:
            match = _TECH_LINE.match(_BULLET.sub("", line).strip())
            if match:
                declared |= set(dictionary_scan(match.group(2)))

        repo_match = _GITHUB_IN_TEXT.search(whole)
        explicit = None
        if repo_match:
            owner, name = repo_match.group(1), repo_match.group(2)
            explicit = f"{owner}/{name.rstrip('.,;)')}"

        projects.append(CVProject(
            title=title,
            body=body,
            skills=sorted(set(dictionary_scan(whole))),
            declared_stack=sorted(declared),
            explicit_repo=explicit,
        ))

    return projects
