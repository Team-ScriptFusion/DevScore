"""
Batch runner: extracts claimed skills + GitHub username from every PDF in a
folder, runs the full verification pipeline for each candidate that has a
discoverable GitHub username, and writes one JSON report.

Usage (env var):
    GITHUB_TOKEN=ghp_xxx python3 run_batch.py "/path/to/CV with GitHub" out.json

Usage (.env file — easier on Windows/PowerShell, nothing to retype per session):
    Create a file named `.env` next to this script containing one line:
        GITHUB_TOKEN=ghp_xxx
    Then just run:
        python run_batch.py "/path/to/CV with GitHub" out.json
    (.env is gitignored by default in most setups — never commit it; it holds a live token.)
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()  # reads .env in the current directory into os.environ, if present
except ImportError:
    pass  # python-dotenv not installed — fall back to a real env var, see usage above

from cv_extract import extract_cv
from main import verify_student
from semantic_matcher import TfidfEmbeddingProvider


def run(folder: str, out_path: str, token: str):
    folder_path = Path(folder)
    pdfs = sorted(folder_path.glob("*.pdf"))
    provider = TfidfEmbeddingProvider()  # see semantic_matcher.py docstring re: HF network block

    report = {"candidates": [], "summary": {}}
    no_github, errors = 0, 0

    for i, pdf in enumerate(pdfs, start=1):
        print(f"[{i}/{len(pdfs)}] {pdf.name}", file=sys.stderr)
        extraction = extract_cv(pdf)
        entry = {
            "file_name": pdf.name,
            "text_source": extraction.text_source,
            "github_username": extraction.github_username,
            "github_source": extraction.github_source,
            "claimed_skills": extraction.claimed_skills,
            "key_projects": [p["name"] for p in extraction.key_projects],
        }

        if not extraction.github_username:
            entry["status"] = "no_github_found"
            entry["note"] = "No GitHub link in text or PDF link annotations — flag as unverifiable, not unverified."
            no_github += 1
            report["candidates"].append(entry)
            continue

        if not extraction.claimed_skills:
            entry["status"] = "no_skills_extracted"
            report["candidates"].append(entry)
            continue

        try:
            result = verify_student(
                github_username=extraction.github_username,
                github_token=token,
                claimed_skills=extraction.claimed_skills,
                cv_projects=[
                    {"name": p["name"], "claimed_stack": p["claimed_stack"]}
                    for p in extraction.key_projects
                ],
                embedding_provider=provider,
            )
            entry["status"] = "completed"
            entry["pipeline_result"] = result
        except RuntimeError as e:
            entry["status"] = "github_error"
            entry["error"] = str(e)
            errors += 1
        except Exception as e:  # keep the batch going — one bad candidate shouldn't sink 47 others
            entry["status"] = "unexpected_error"
            entry["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc(file=sys.stderr)
            errors += 1

        report["candidates"].append(entry)
        time.sleep(0.5)  # gentle pacing; GraphQL rate budget is checked per-call regardless

    completed = sum(1 for c in report["candidates"] if c["status"] == "completed")
    report["summary"] = {
        "total_cvs": len(pdfs),
        "github_found": len(pdfs) - no_github,
        "no_github_found": no_github,
        "completed": completed,
        "errors": errors,
    }

    Path(out_path).write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    folder_arg = sys.argv[1] if len(sys.argv) > 1 else "CV with GitHub"
    out_arg = sys.argv[2] if len(sys.argv) > 2 else "batch_results.json"
    token_arg = os.environ.get("GITHUB_TOKEN", "")
    if not token_arg:
        print("No GITHUB_TOKEN found. Either set it as an env var, or create a .env file "
              "next to this script containing: GITHUB_TOKEN=your_token_here", file=sys.stderr)
        sys.exit(1)
    run(folder_arg, out_arg, token_arg)
