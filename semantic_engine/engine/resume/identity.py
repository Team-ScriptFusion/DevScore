"""
Candidate identity: GitHub handle and person name.

Everything here is an ADDITION to the team's `cv_parser` module, not a
replacement for it. `cv_parser` answers "what skills does this CV claim?" —
that is Implementation 01's deliverable and it stays the authority. It does
not answer the two questions the scoring engine also needs:

  WHOSE GitHub is this?   Every claim is unverifiable without a repository to
                          check it against, and the handle hides in three
                          places (link annotations, body URLs, bare handles).

  WHOSE CV is this?       Drive appends the UPLOADER's name to a shared file,
                          so the filename is not a safe source of identity.

Both are extracted from the same cleaned text `cv_parser` already produces,
plus one extra pdfplumber pass for link annotations (which `cv_parser`'s
text extraction discards).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# GitHub handle recovery
# ---------------------------------------------------------------------------

GITHUB_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)"
    r"(?:/([A-Za-z0-9._-]+))?",
    re.IGNORECASE,
)

# Last-resort pattern for "GitHub: janidu" / "GitHub - @janidu" / "Github | x".
#
# An EXPLICIT separator is required. An earlier version allowed a bare space,
# which turned every ordinary sentence into a false handle — real hits from
# this dataset included "GitHub projects", "Github Analysis" and
# "GitHub | 2025" (the last of which was confidently reported as the
# candidate's username). A wrong handle is worse than no handle: it sends the
# miner to a stranger's repositories and scores the candidate against them.
BARE_HANDLE_RE = re.compile(
    r"git\s?hub\b\s*[:@|/\-–—]\s*@?([A-Za-z][A-Za-z0-9-]{2,38})(?![\w.])",
    re.IGNORECASE,
)

# Paths under github.com that are never a username.
GITHUB_RESERVED = {
    "orgs", "settings", "features", "explore", "topics", "collections", "events",
    "marketplace", "sponsors", "about", "pricing", "login", "join", "search",
    "notifications", "pulls", "issues", "codespaces", "apps", "readme", "com",
    "www", "http", "https", "in", "profile", "user", "users", "my", "the",
}

# Resume words that follow "GitHub" often enough to be mistaken for handles.
HANDLE_STOPWORDS = {
    "projects", "project", "profile", "profiles", "repository", "repositories",
    "repo", "repos", "analysis", "account", "link", "links", "page", "portfolio",
    "education", "experience", "skills", "and", "for", "with", "see", "visit",
    "com", "www", "http", "https", "linkedin", "gitlab", "bitbucket", "actions",
    "pages", "copilot", "username", "handle", "code", "contributions",
}


def _annotation_urls(pdf) -> list[str]:
    """
    Pull every hyperlink target out of the PDF's link annotations.

    pdfplumber exposes annotations as dicts whose 'uri' key is populated for
    /Action /URI links. Design-tool exports (Canva, Figma, Illustrator) very
    commonly render social links as an icon with the URL only in the
    annotation — extract_text() returns nothing for them.
    """
    urls: list[str] = []
    for page in pdf.pages:
        for annot in (page.annots or []):
            uri = annot.get("uri") or ""
            if not uri:
                data = annot.get("data") or {}
                action = data.get("A") if isinstance(data, dict) else None
                if isinstance(action, dict):
                    uri = action.get("URI") or ""
            if isinstance(uri, bytes):
                uri = uri.decode("utf-8", "ignore")
            if uri:
                urls.append(str(uri))
    return urls


def extract_github(text: str, annotation_urls: list[str]) -> tuple[list[str], str | None]:
    """
    Returns (all github urls found, best-guess username).

    Annotation URLs are trusted over body text: a clickable link is what the
    candidate actually pointed at, whereas body text can be truncated by the
    PDF's layout ("github.com/janidu-de-alw…").
    """
    urls: list[str] = []
    candidates: list[str] = []

    for source in (annotation_urls, [text]):
        for blob in source:
            for match in GITHUB_URL_RE.finditer(blob or ""):
                user = match.group(1)
                if not user or user.lower() in GITHUB_RESERVED:
                    continue
                urls.append(match.group(0))
                candidates.append(user)

    if not candidates:
        for match in BARE_HANDLE_RE.finditer(text or ""):
            handle = match.group(1)
            lowered = handle.lower()
            if lowered in GITHUB_RESERVED or lowered in HANDLE_STOPWORDS:
                continue
            if handle.isdigit():
                continue
            candidates.append(handle)

    if not candidates:
        return [], None

    # Most frequent handle wins; ties break toward the first annotation hit,
    # which is the most reliable source.
    best = max(set(candidates), key=lambda c: (candidates.count(c), -candidates.index(c)))
    return sorted(set(urls)), best


# ---------------------------------------------------------------------------
# Candidate identity
# ---------------------------------------------------------------------------
#
# The candidate's name MUST come from inside the CV, never from the filename.
#
# The collected dataset makes the reason obvious: Google Drive appends the name
# of whoever *uploaded* the file, which is frequently not whose CV it is.
#     "Anura Perera - Software Engineering Undergraduate CV - Binara Silva.pdf"
# is Anura Perera's CV, uploaded by Binara Silva. Trusting the filename
# attributes one student's verified skills to another student by name — the
# single worst failure mode available to a system whose entire output is a
# judgement about a named person.
#
# (The GitHub handle was never affected: it is read out of the CV's own link
# annotations and body text, so it always belongs to the CV's owner.)

# Words that appear on the line under the name — a role, not a person.
_ROLE_WORDS = {
    "engineer", "engineering", "developer", "undergraduate", "graduate", "student",
    "intern", "internship", "accountant", "manager", "designer", "analyst",
    "consultant", "executive", "officer", "assistant", "specialist", "administrator",
    "programmer", "architect", "scientist", "lecturer", "trainee", "associate",
    "fullstack", "full-stack", "frontend", "backend", "software", "technology",
    "information", "computer", "science", "curriculum", "vitae", "resume", "cv",
    "profile", "summary", "objective", "contact", "about", "portfolio", "skills",
    "education", "experience", "projects", "project", "bsc", "msc", "hons",
    "personal", "details", "detail", "nationality", "gender", "birth", "dob",
    "references", "reference", "interests", "achievements", "certifications",
    "declaration", "languages", "language", "awards", "hobbies", "activities",
}

# Ordinary English words that never appear in a name. Without these, prose that
# happens to start a line ("I am currently pursuing a ...") passes every other
# test — first token capitalised, all tokens alphabetic — and gets returned as
# the candidate's name.
_FUNCTION_WORDS = {
    "i", "a", "an", "the", "am", "is", "are", "was", "were", "be", "been",
    "my", "me", "we", "our", "you", "your", "he", "she", "they", "it",
    "to", "of", "in", "on", "at", "for", "with", "and", "or", "but", "as",
    "currently", "pursuing", "seeking", "passionate", "motivated", "results",
    "hello", "hi", "welcome", "name", "email", "phone", "address", "mobile",
}

_NAME_TOKEN = re.compile(r"^[A-Za-z][A-Za-z'’.\-]*$")


def _collapse_letter_spacing(line: str) -> str:
    """
    "J A N I D U" -> "JANIDU".

    Design-tool exports (Canva especially) render the name heading with tracking
    applied as literal spaces between glyphs, so pdfplumber returns one letter
    per token. Left alone, the name is unrecoverable.
    """
    tokens = line.split()
    if len(tokens) >= 4 and sum(1 for t in tokens if len(t) == 1) / len(tokens) >= 0.7:
        return "".join(tokens)
    return line


def _strip_contact_tail(line: str) -> str:
    """
    "CHAMILA WEERASINGHE +94 70 000 0000" -> "CHAMILA WEERASINGHE".

    Multi-column layouts routinely interleave the name heading with the phone
    number or email from the adjacent column onto one extracted line. Cutting
    at the first digit or "@" recovers the name instead of discarding the line.
    """
    cut = len(line)
    for index, char in enumerate(line):
        if char.isdigit() or char in "@+":
            cut = index
            break
    return line[:cut].strip(" .,|·—–-")


def _looks_like_name(line: str) -> bool:
    stripped = _strip_contact_tail(line.strip(" .,|·—–-"))
    if not (2 <= len(stripped) <= 45) or "/" in stripped:
        return False

    tokens = stripped.split()
    if not (1 <= len(tokens) <= 5):
        return False
    if not all(_NAME_TOKEN.match(t) for t in tokens):
        return False

    lowered = [t.lower().strip(".") for t in tokens]
    if any(t in _ROLE_WORDS or t in _FUNCTION_WORDS for t in lowered):
        return False
    if not tokens[0][0].isupper():
        return False
    # Title Case or ALL CAPS. "Nuwan silva" is a real heading in this
    # dataset, so a fully-capitalised requirement is too strict — half is enough
    # once role words and function words are already excluded.
    capitalised = sum(1 for t in tokens if t[0].isupper())
    return capitalised / len(tokens) >= 0.5


def extract_person_name(text: str) -> str | None:
    """
    Recover the candidate's own name from the top of the CV.

    Scans the first lines only: on every layout in the collected dataset the
    name is the document's heading. Returns None rather than guessing — an
    unknown name is honest, a wrong name is a misattribution.
    """
    lines = [
        _collapse_letter_spacing(l.strip())
        for l in (text or "").split("\n")[:14]
        if l.strip()
    ]

    for index, line in enumerate(lines):
        if not _looks_like_name(line):
            continue
        name = _strip_contact_tail(line.strip(" .,|·—–-"))

        # Names split one word per line ("KAVI" / "RANASINGHE", or a letter-spaced
        # given name above a letter-spaced surname) — join the run.
        if len(name.split()) == 1:
            parts = [name]
            for following in lines[index + 1: index + 3]:
                candidate = _strip_contact_tail(following.strip(" .,|·—–-"))
                if _looks_like_name(candidate) and len(candidate.split()) == 1:
                    parts.append(candidate)
                else:
                    break
            if len(parts) > 1:
                name = " ".join(parts)

        if len(name.split()) == 1:
            # A lone capitalised word is only a name when it is the document's
            # very first line. Anywhere below that it is far more likely to be
            # a city, a section label or the tail of a role — "Software
            # Engineer / Colombo" would otherwise yield "Colombo".
            if index > 0 or len(name) < 4:
                continue
        return " ".join(name.split())

    return None


