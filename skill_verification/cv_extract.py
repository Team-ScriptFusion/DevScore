"""
Lightweight CV extraction, built ONLY as a test harness for this module.

This is explicitly NOT `cv_parser` (Section 0: that's a separate,
already-built Python microservice owned by a teammate — dictionary + regex
matcher, 100+ skill dictionary, punctuation-safe boundaries for tokens like
C++/C#/.NET, OCR fallback via pytesseract). Section 4 of the spec says to
build fake test data when real students aren't available yet; this is that,
scaled up to the 48 real CVs already collected, so the module can be
exercised against real evidence instead of hand-typed fixtures.

Do not wire this into production — swap it for a call to the real
cv_parser service's output once this module is integrated into DevScore.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

# A trimmed skill dictionary in the same spirit as cv_parser's 100+ entries.
# Longer/more specific terms first so "React.js" matches before bare "React"
# gets a chance to eat part of it, mirroring cv_parser's punctuation-safe
# boundary handling for tokens like C++/C#/.NET.
SKILL_DICTIONARY = [
    "React.js", "React Native", "React", "Node.js", "Vue.js", "Vue", "Next.js", "Angular",
    "Express.js", "Express", "Flask", "Django", "FastAPI", "Spring Boot", "Spring",
    "ASP.NET", ".NET", "Laravel", "Tailwind CSS", "Bootstrap", "jQuery", "Vite", "Webpack",
    "TypeScript", "JavaScript", "Python", "Java", "C++", "C#", "PHP", "Kotlin", "Swift",
    "Dart", "Flutter", "Go", "Rust", "Ruby", "SQL", "HTML", "CSS", "R",
    "MongoDB", "MySQL", "PostgreSQL", "Firebase", "Firestore", "Supabase", "SQLite",
    "Redis", "Oracle", "SQL Server", "Azure SQL Database",
    "AWS", "Amazon Web Services", "Microsoft Azure", "Azure", "Google Cloud Platform", "GCP",
    "Firebase Hosting", "Netlify", "Vercel", "Render", "Heroku", "Docker", "Kubernetes",
    "Git", "GitHub", "GitLab", "CI/CD", "Jenkins", "Figma", "Adobe XD", "Photoshop", "Illustrator",
    "Machine Learning", "Deep Learning", "Natural Language Processing", "NLP", "Computer Vision",
    "TensorFlow", "PyTorch", "Scikit-learn", "Pandas", "NumPy", "OpenAI GPT", "OpenCV",
    "REST API", "RESTful API", "GraphQL", "Microservices", "WebSocket",
    "Agile", "Scrum", "Kanban", "Jira", "UI/UX Design", "UX Design", "UI Design",
    "Android Studio", "Xcode", "Unity", "Unreal Engine",
    "Data Structures", "Algorithms", "Object-Oriented Programming", "OOP",
    "Project Management", "Communication", "Teamwork", "Leadership", "Problem Solving",
    "Android", "iOS", "Linux", "Bash", "PowerShell", "Postman", "Selenium", "JUnit", "PyTest",
    "PDFMiner", "OpenAI", "Twilio", "Stripe", "Socket.io", "Sequelize", "Prisma", "Mongoose",
]

_ESCAPED = sorted((re.escape(s) for s in SKILL_DICTIONARY), key=len, reverse=True)
SKILL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(_ESCAPED) + r")(?![A-Za-z0-9])", re.IGNORECASE
)

GITHUB_URL_RE = re.compile(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)", re.IGNORECASE)
SECTION_HEADER_RE = re.compile(
    r"^\s*(KEY\s+PROJECTS|PROJECTS|PERSONAL\s+PROJECTS|ACADEMIC\s+PROJECTS)\s*$", re.IGNORECASE
)
NEXT_SECTION_RE = re.compile(
    r"^\s*(EDUCATION|SKILLS|CORE\s+SKILLS|EXPERIENCE|WORK\s+EXPERIENCE|CERTIFICATIONS?|"
    r"AWARDS?|REFERENCES?|LANGUAGES|INTERESTS|CONTACT|SUMMARY|OBJECTIVE|ACHIEVEMENTS?)\s*$",
    re.IGNORECASE,
)


@dataclass
class CVExtraction:
    file_name: str
    text: str
    text_source: str                       # 'pdftext' | 'ocr' | 'empty'
    claimed_skills: list[str] = field(default_factory=list)
    key_projects: list[dict] = field(default_factory=list)
    github_username: str | None = None
    github_source: str | None = None       # 'body_text' | 'link_annotation' | None


def extract_text(pdf_path: Path) -> tuple[str, str]:
    """Returns (text, source). Falls back to OCR when the text layer is
    empty/near-empty (Section 0's cv_parser design: pytesseract fallback
    for scanned PDFs)."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    text = "\n".join(text_parts)
    if len(text.strip()) >= 50:
        return text, "pdftext"

    ocr_text = _ocr_fallback(pdf_path)
    if len(ocr_text.strip()) >= 20:
        return ocr_text, "ocr"
    return text, "empty"


def _ocr_fallback(pdf_path: Path) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_path
        images = convert_from_path(str(pdf_path), dpi=200)
        return "\n".join(pytesseract.image_to_string(img) for img in images)
    except Exception as e:  # pragma: no cover - environment-dependent
        print(f"[cv_extract] OCR fallback failed for {pdf_path.name}: {e}")
        return ""


def extract_github_username(pdf_path: Path, text: str) -> tuple[str | None, str | None]:
    """Checks visible text FIRST, then PDF link annotations — a hyperlinked
    'GitHub' word with no visible URL string is invisible to a text-only
    regex, and the batch check on this folder found candidates where that
    matters."""
    match = GITHUB_URL_RE.search(text)
    if match:
        username = match.group(1)
        if username.lower() not in ("settings", "features", "about", "topics", "search", "login"):
            return username, "body_text"

    try:
        reader = PdfReader(str(pdf_path))
        for page in reader.pages:
            annots = page.get("/Annots")
            if not annots:
                continue
            for a in annots:
                try:
                    obj = a.get_object()
                    action = obj.get("/A")
                    uri = action.get_object().get("/URI") if action is not None else None
                except Exception:
                    continue
                if uri and "github.com" in str(uri).lower():
                    m = GITHUB_URL_RE.search(str(uri))
                    if m:
                        return m.group(1), "link_annotation"
    except Exception as e:  # pragma: no cover
        print(f"[cv_extract] annotation scan failed for {pdf_path.name}: {e}")

    return None, None


def extract_claimed_skills(text: str) -> list[str]:
    seen, ordered = set(), []
    for m in SKILL_PATTERN.finditer(text):
        canonical = _canonical(m.group(1))
        key = canonical.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(canonical)
    return ordered


def _canonical(matched: str) -> str:
    for skill in SKILL_DICTIONARY:
        if skill.lower() == matched.lower():
            return skill
    return matched


def extract_key_projects(text: str) -> list[dict]:
    """Heuristic section extraction: find a PROJECTS-like header, take lines
    until the next known section header, then split into per-project blocks
    on lines that look like a project title (short, title-cased/uppercase,
    not a bullet). Best-effort — real cv_parser output would replace this."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if SECTION_HEADER_RE.match(line.strip()):
            start = i + 1
            break
    if start is None:
        return []

    end = len(lines)
    for i in range(start, len(lines)):
        if NEXT_SECTION_RE.match(lines[i].strip()):
            end = i
            break
    block = lines[start:end]

    projects = []
    current_name, current_lines = None, []

    def flush():
        if current_name:
            block_text = " ".join(current_lines)
            projects.append({
                "name": current_name.strip(" -–:"),
                "claimed_stack": extract_claimed_skills(block_text),
                "raw_text": block_text[:600],
            })

    for line in block:
        stripped = line.strip()
        if not stripped:
            continue
        looks_like_title = (
            len(stripped) < 70
            and not stripped.startswith(("-", "•", "*", "·"))
            and (stripped.isupper() or stripped[:1].isupper())
            and sum(c.isalpha() for c in stripped) / max(len(stripped), 1) > 0.5
            and stripped.count(" ") < 8
        )
        if looks_like_title and (not current_lines or len(current_lines) > 0):
            # Heuristic: a short, title-like line after we already have body
            # text for the current project starts a NEW project.
            if current_name is None:
                current_name = stripped
                continue
            if len(current_lines) >= 1:
                flush()
                current_name, current_lines = stripped, []
                continue
        current_lines.append(stripped)
    flush()
    return projects


def extract_cv(pdf_path: Path) -> CVExtraction:
    text, source = extract_text(pdf_path)
    username, github_source = extract_github_username(pdf_path, text)
    return CVExtraction(
        file_name=pdf_path.name,
        text=text,
        text_source=source,
        claimed_skills=extract_claimed_skills(text),
        key_projects=extract_key_projects(text),
        github_username=username,
        github_source=github_source,
    )
