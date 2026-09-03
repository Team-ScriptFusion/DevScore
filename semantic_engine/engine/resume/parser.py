"""
Resume adapter — thin wrapper over the team's `cv_parser` module.

SKILL EXTRACTION IS NOT DONE HERE. It is done by `cv_parser/`, the module
already deployed as Implementation 01 (FR 28–32), vendored from
Team-ScriptFusion/DevScore. That module is the authority on what a CV claims,
for one non-negotiable reason: it is what the live system runs, and what the
backend stores in `resume_skills`. If this engine extracted skills its own way,
a recruiter's dashboard and the score beside it would disagree about the same
candidate — and the disagreement would be invisible, because both numbers would
look reasonable.

An earlier version of this file did reimplement extraction. It produced a
materially different claim set on real CVs (it found "Machine Learning" and
"Computer Vision" as concepts where cv_parser finds "OpenCV" and
"scikit-learn" as tools), which is exactly the divergence described above.
That code is gone; the identity helpers it also contained moved to
`identity.py`.

What this module adds on top of cv_parser — the things Implementation 02 needs
and Implementation 01 never had to answer:

  1. GITHUB HANDLE — no claim can be verified without a repository to check it
     against. Recovered from PDF link annotations, body URLs, and bare handles
     (`identity.extract_github`).

  2. CANDIDATE NAME — read from the CV itself, because Drive appends the
     UPLOADER's name to a shared file (`identity.extract_person_name`).

  3. ONTOLOGY MAPPING — cv_parser's canonical names resolved onto verification
     recipes via `ontology.from_cv_parser`. A skill cv_parser recognises but
     this engine cannot verify is still reported, as a claim with
     verifiable=False and weight 0: visible to the recruiter, excluded from
     the score's denominator.

Keeping `cv_parser/` unmodified means it can be re-synced from the repository
whenever the team extends the dictionary — see `cv_parser/VENDORED.md`.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pdfplumber

# pdfminer logs a WARNING for every glyph whose font descriptor lacks a
# FontBBox. Real CVs exported from design tools trigger this dozens of times
# per file and it says nothing about extraction success, so it is silenced
# here rather than left to drown out warnings that matter.
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# Locate the team's cv_parser package.
#
# Two layouts have to work, because this engine lives in both:
#
#   standalone            in the DevScore repo
#   devscore-engine/      DevScore/
#     cv_parser/            cv_parser/          <- the real one, a sibling
#     engine/...            semantic_engine/
#                             engine/...
#
# So walk up from this file until a directory containing `cv_parser` turns up,
# rather than hard-coding a parent depth that is only right in one of them.
# cv_parser imports `skills_dictionary` as a top-level name, so its own
# directory goes on sys.path — appended, never prepended, so it cannot shadow
# anything in this package.


def _locate_cv_parser() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "cv_parser"
        if (candidate / "cv_parser.py").is_file():
            return candidate
    raise ImportError(
        "cv_parser/ not found in any parent directory of "
        f"{here}. It is the team's deployed skill extractor and this engine "
        "is only an adapter over it — see cv_parser/VENDORED.md."
    )


_CV_PARSER_DIR = _locate_cv_parser()
if str(_CV_PARSER_DIR) not in sys.path:
    sys.path.append(str(_CV_PARSER_DIR))

import cv_parser as team_cv_parser  # noqa: E402  (path set above)

from .. import ontology  # noqa: E402
from ..models import ClaimedSkill, ResumeProfile  # noqa: E402
from .identity import extract_github, extract_person_name  # noqa: E402

# cv_parser categories that describe process or tooling rather than code.
# Used only to label unmapped claims sensibly on the dashboard.
_NON_CODE_CATEGORIES = {"methodology", "design"}


def _annotation_urls(path: str) -> list[str]:
    """
    Every hyperlink target in the PDF's link annotations.

    cv_parser's `extract_text_from_pdf` returns text only, and design-tool
    exports routinely render the GitHub link as an icon with the URL present
    *only* in the annotation — no visible text at all. One extra pdfplumber
    open is the price of not losing those candidates entirely.
    """
    urls: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
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
    except Exception:
        # Annotations are a bonus channel. A malformed PDF must not cost us
        # the skills cv_parser already extracted successfully.
        return []
    return urls


def _to_claimed_skills(extraction: dict) -> list[ClaimedSkill]:
    """
    Map cv_parser's `extract_claimed_skills` output onto ClaimedSkill rows.

    Note the key names: the low-level function returns `by_category` and
    `uncategorized`, which cv_parser's own `parse_resume` renames to `skills`
    and `uncategorized_terms_found` on the way out. This adapter calls the
    low-level function (it needs the cleaned text too), so it must read the
    low-level names.
    """
    source_detail = extraction.get("source_detail") or {}
    claimed: list[ClaimedSkill] = []

    for category, names in (extraction.get("by_category") or {}).items():
        for name in names:
            skill = ontology.from_cv_parser(name)
            sources = source_detail.get(name) or ["dictionary_scan"]
            if skill is not None:
                claimed.append(ClaimedSkill(
                    name=skill.name,
                    category=skill.category,
                    weight=skill.weight,
                    verifiable=skill.verifiable,
                    recognised=True,
                    sources=sorted(sources),
                    raw_terms=[name],
                ))
            else:
                # cv_parser recognises it; this engine has no way to check it.
                # Reported for the recruiter, excluded from the score.
                claimed.append(ClaimedSkill(
                    name=name,
                    category=category,
                    weight=0.0,
                    verifiable=False,
                    recognised=True,
                    sources=sorted(sources),
                    raw_terms=[name],
                ))

    # Terms the candidate listed under "Skills" that cv_parser's dictionary
    # does not know yet. Never dropped — that is cv_parser's own design rule.
    for term in extraction.get("uncategorized") or []:
        claimed.append(ClaimedSkill(
            name=term,
            category="uncategorized",
            weight=0.0,
            verifiable=False,
            recognised=False,
            sources=["skills_section"],
            raw_terms=[term],
        ))

    # One row per skill: a skill can arrive from several cv_parser categories.
    deduped: dict[str, ClaimedSkill] = {}
    for entry in claimed:
        existing = deduped.get(entry.name)
        if existing is None:
            deduped[entry.name] = entry
        else:
            existing.sources = sorted(set(existing.sources) | set(entry.sources))
            existing.raw_terms = sorted(set(existing.raw_terms) | set(entry.raw_terms))
    return sorted(deduped.values(), key=lambda c: (not c.recognised, c.name))


def parse_resume(pdf_path: str | Path) -> ResumeProfile:
    """
    Run the team's cv_parser, then add identity and ontology mapping.

    Returns a ResumeProfile even on failure — a candidate we could not read is
    a finding the cohort study needs to report, not a row to drop.
    """
    path = Path(pdf_path)
    profile = ResumeProfile(file_name=path.name, status="failed")

    if not path.exists():
        profile.reason = "file_not_found"
        return profile

    # -- text, via cv_parser's own extractor (pdfplumber + OCR fallback) -----
    try:
        raw_text = team_cv_parser.extract_text_from_pdf(str(path))
    except Exception as exc:
        profile.reason = f"pdf_parse_error: {exc.__class__.__name__}: {exc}"
        return profile

    text = team_cv_parser.clean_text(raw_text)
    profile.text_chars = len(text)
    annotation_urls = _annotation_urls(str(path))

    if not text.strip():
        profile.reason = (
            "no_extractable_text_even_with_ocr"
            if getattr(team_cv_parser, "_OCR_AVAILABLE", False)
            else "no_text_layer_and_ocr_unavailable (pip install pytesseract + tesseract binary)"
        )
        # A handle may still be recoverable from link annotations alone.
        profile.github_urls, profile.github_username = extract_github("", annotation_urls)
        return profile

    # -- skills, entirely from cv_parser ------------------------------------
    extraction = team_cv_parser.extract_claimed_skills(text)
    profile.skills_section_found = bool(extraction.get("skills_section_found"))
    profile.claimed = _to_claimed_skills(extraction)

    # -- identity, the part cv_parser does not do ---------------------------
    profile.person_name = extract_person_name(text)
    profile.name_source = "cv" if profile.person_name else "filename"
    profile.github_urls, profile.github_username = extract_github(text, annotation_urls)

    scorable = sum(1 for c in profile.claimed if c.recognised and c.verifiable)
    profile.status = "success" if scorable else "success_no_skills_found"
    return profile


if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(parse_resume(sys.argv[1]).to_dict(), indent=2))
