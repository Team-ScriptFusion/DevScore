#!/usr/bin/env python3
"""
Cohort runner — score a folder of CVs and emit the tables the validation
study needs.

    python batch.py data/cvs --out data/out                      # everyone
    python batch.py data/cvs --select 1,4,7-12                   # a chosen few
    python batch.py data/cvs --select jayasuriya,kavi           # by name or handle
    python batch.py data/cvs --scorable-only                     # skip CVs with no handle
    python batch.py data/cvs --resume-from data/out/scores.csv   # continue an interrupted run

Run `python cli.py scan data/cvs` first — it prints the indexed roster that
--select consumes, and shows which CVs have a GitHub handle at all.

Produces, in --out:
    scores.csv        one row per candidate: score, breakdown, counts, coverage
    verdicts.csv      one row per (candidate, skill): the claim-vs-evidence matrix
    reports/*.json    the full explainable report per candidate
    summary.md        cohort-level statistics

`scores.csv` is the file that gets joined against the industry experts'
manual rankings (research objective 5). `verdicts.csv` is the one that
answers the more interesting question — *which* claims the model verified,
which is where per-skill precision and recall come from.

Operational notes:

  RESUMABLE. A 100-candidate run against the 5,000/hour rate limit will be
  interrupted. `--resume-from` reads an existing scores.csv and skips
  candidates already present, so a re-run costs only what is left. The disk
  cache makes re-scoring already-seen candidates nearly free anyway.

  FAIL-SOFT PER CANDIDATE. One corrupt PDF or one deleted GitHub account
  must not lose the other ninety-nine results. Every candidate is wrapped;
  failures are recorded as rows with a status column rather than dropped,
  because "we could not score this person" is itself a finding the study
  needs to report.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from engine.github.client import GitHubClient, RateLimitExhausted  # noqa: E402
from engine.pipeline import score_resume  # noqa: E402
from engine.selection import SelectionError, build_roster, select  # noqa: E402

SCORE_FIELDS = [
    # `candidate` is read from inside the CV; `filename_label` is what the Drive
    # filename claims. They disagree whenever someone uploaded a peer's CV, and
    # both are kept so that disagreement is auditable rather than invisible.
    "candidate", "name_source", "filename_label", "file", "status",
    "github_username", "handle_source", "score", "band", "confidence",
    "base_score", "integrity_penalty", "breadth_bonus",
    "claimed", "verifiable_claims", "verified", "weakly_verified", "unverified",
    "repos_mined", "files_analyzed", "api_calls", "notes",
]

VERDICT_FIELDS = [
    "candidate", "skill", "category", "claimed", "status", "tier", "weight",
    "verification", "evidence_strength", "complexity", "depth", "recency", "craft",
    "repos", "files_analyzed", "loc_analyzed", "last_activity",
]


# The collected dataset uses two filename conventions, and they put the
# student's name on opposite sides of the separator:
#     "5652 - Binara Silva.pdf"                   -> name AFTER  " - "
#     "Tharushi Bandara — Internship CV.pdf"      -> name BEFORE the em dash
# Files downloaded over HTTP also arrive with the em dash mojibaked to
# "â€”" (UTF-8 read as cp1252), so that is repaired first — otherwise the
# em-dash rule never fires and the whole filename becomes the candidate name.
_MOJIBAKE = {"â€”": "—", "â€“": "–", "â€™": "’", "Â ": " "}


def filename_label(path: Path) -> str:
    stem = path.stem
    for bad, good in _MOJIBAKE.items():
        stem = stem.replace(bad, good)
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)

    if re.search(r"\s[—–]\s", stem):
        stem = re.split(r"\s[—–]\s", stem)[0]
    elif " - " in stem:
        stem = stem.rsplit(" - ", 1)[-1]

    stem = re.sub(r"\b(cv|resume|curriculum vitae)\b", "", stem, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", stem).strip(" _-.") or path.stem


def already_done(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    try:
        with csv_path.open(encoding="utf-8", newline="") as handle:
            return {row["file"] for row in csv.DictReader(handle) if row.get("file")}
    except (OSError, csv.Error, KeyError):
        return set()


def run(args) -> int:
    folder = Path(args.folder)
    out = Path(args.out)
    (out / "reports").mkdir(parents=True, exist_ok=True)

    # Roster first: parsing every CV is cheap (no network) and it is what turns
    # "--select 1,4,7-12" into actual files. It also means a mistyped selection
    # fails before a single GitHub call is spent.
    roster = build_roster(folder)
    if not roster:
        print(f"no PDFs found in {folder}")
        return 1
    try:
        picked = select(roster, args.select)
    except SelectionError as exc:
        print(exc)
        return 1

    if args.scorable_only:
        picked = [e for e in picked if e.scorable]
    if args.limit:
        picked = picked[: args.limit]

    pdfs = [entry.path for entry in picked]
    names = {entry.path: entry.name for entry in picked}
    # Handles resolved by the roster — CV-derived OR supplied via
    # handle_overrides.json. Passed explicitly so score_resume does not
    # re-parse and lose an override for a CV that names no account itself.
    handles = {entry.path: entry.github_username for entry in picked}
    handle_source = {entry.path: entry.handle_source for entry in picked}
    if len(picked) != len(roster):
        print(f"selection: {len(picked)} of {len(roster)} candidates\n")
    overridden = [e for e in picked if e.handle_source == "override"]
    if overridden:
        print(f"applying {len(overridden)} handle override(s) from handle_overrides.json:")
        for e in overridden:
            print(f"  {e.name}  →  @{e.github_username}"
                  + (f"  ({e.handle_note})" if e.handle_note else ""))
        print()

    skip = already_done(Path(args.resume_from)) if args.resume_from else set()
    if skip:
        print(f"resuming: skipping {len(skip)} already-scored CVs")

    scores_path = out / "scores.csv"
    verdicts_path = out / "verdicts.csv"
    append = bool(skip) and scores_path.exists()

    client = GitHubClient(cache_dir=args.cache, offline=args.offline)

    # Derive a fair per-candidate allowance from what is actually left, so the
    # last candidate in the run is scored on the same evidence budget as the
    # first. Without this the ordering of the folder silently becomes a scoring
    # factor.
    call_budget = args.budget_per_candidate or None
    if call_budget is None and not args.offline and picked:
        try:
            limits = client.get("/rate_limit")
            remaining = int(limits["resources"]["core"]["remaining"])
            call_budget = max(25, int((remaining * 0.9) / max(1, len(picked))))
            print(f"rate limit: {remaining} calls left -> budgeting "
                  f"{call_budget} per candidate across {len(picked)}\n")
        except Exception:
            call_budget = None

    if not client.token and not args.offline:
        print("WARNING: no GitHub token (GITHUB_TOKEN or `gh auth login`). "
              "60 requests/hour will not get you through a cohort.\n")

    score_file = scores_path.open("a" if append else "w", encoding="utf-8", newline="")
    verdict_file = verdicts_path.open("a" if append else "w", encoding="utf-8", newline="")
    score_writer = csv.DictWriter(score_file, fieldnames=SCORE_FIELDS)
    verdict_writer = csv.DictWriter(verdict_file, fieldnames=VERDICT_FIELDS)
    if not append:
        score_writer.writeheader()
        verdict_writer.writeheader()

    collected: list[dict] = []
    try:
        for index, pdf in enumerate(pdfs, start=1):
            if pdf.name in skip:
                continue
            label = filename_label(pdf)
            roster_name = names.get(pdf)
            print(f"[{index}/{len(pdfs)}] {label} ... ", end="", flush=True)

            calls_before = client.calls
            try:
                report = score_resume(
                    pdf,
                    github_username=handles.get(pdf),
                    client=client,
                    candidate_name=roster_name,
                    max_repos_deep=args.deep_repos,
                    files_per_repo=args.files_per_repo,
                    max_files_total=args.max_files,
                    call_budget=call_budget,
                )
            except RateLimitExhausted as exc:
                print(f"RATE LIMITED — stopping cleanly.\n  {exc}")
                print(f"  re-run with --resume-from {scores_path} once the limit resets.")
                break
            except Exception as exc:  # noqa: BLE001 - one bad CV must not end the run
                print(f"FAILED ({exc.__class__.__name__})")
                if args.verbose:
                    traceback.print_exc()
                score_writer.writerow({
                    "candidate": label, "file": pdf.name, "status": "error",
                    "notes": f"{exc.__class__.__name__}: {exc}",
                })
                score_file.flush()
                continue

            d = report.to_dict()
            gh = report.github
            name = d["candidate"]
            row = {
                "candidate": name,
                "name_source": report.resume.name_source if report.resume else "unknown",
                "filename_label": label,
                "file": pdf.name,
                "status": report.resume.status if report.resume else "unknown",
                "github_username": d["github_username"] or "",
                "handle_source": handle_source.get(pdf, "cv"),
                "score": round(d["score"], 2),
                "band": d["band"],
                "confidence": round(d["confidence"], 3),
                "base_score": d["breakdown"]["base_score"],
                "integrity_penalty": d["breakdown"]["integrity_penalty"],
                "breadth_bonus": d["breakdown"]["breadth_bonus"],
                "claimed": d["counts"]["claimed"],
                "verifiable_claims": d["counts"]["verifiable_claims"],
                "verified": d["counts"]["verified"],
                "weakly_verified": d["counts"]["weakly_verified"],
                "unverified": d["counts"]["unverified"],
                "repos_mined": len([r for r in gh.repos if r.languages]) if gh else 0,
                "files_analyzed": sum(len(r.fetched_files) for r in gh.repos) if gh else 0,
                "api_calls": client.calls - calls_before,
                "notes": " | ".join(d["warnings"])[:400],
            }
            score_writer.writerow(row)
            collected.append(row)

            for v in d["verdicts"]:
                verdict_writer.writerow({
                    "candidate": name,
                    "skill": v["skill"],
                    "category": v["category"],
                    "claimed": int(v["claimed"]),
                    "status": v["status"],
                    "tier": v["tier"],
                    "weight": v["weight"],
                    "verification": v["verification"],
                    "evidence_strength": v["signals"]["evidence_strength"],
                    "complexity": v["signals"]["complexity"],
                    "depth": v["signals"]["depth"],
                    "recency": v["signals"]["recency"],
                    "craft": v["signals"]["craft"],
                    "repos": ";".join(v["repos"]),
                    "files_analyzed": v["files_analyzed"],
                    "loc_analyzed": v["loc_analyzed"],
                    "last_activity": v["last_activity"],
                })

            # Provenance the report itself does not carry: where the name and
            # the GitHub handle came from. The cohort dashboard surfaces both.
            d["identity"] = {
                "name_source": row["name_source"],
                "filename_label": label,
                "handle_source": handle_source.get(pdf, "cv"),
                "handle_note": next(
                    (e.handle_note for e in picked if e.path == pdf), ""
                ),
            }
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name)[:60] or "candidate"
            (out / "reports" / f"{safe}.json").write_text(
                json.dumps(d, indent=2), encoding="utf-8"
            )

            score_file.flush()
            verdict_file.flush()
            print(f"{d['score']:5.1f}  ({d['counts']['verified']}v/"
                  f"{d['counts']['unverified']}u, conf {d['confidence']:.0%})")
    finally:
        score_file.close()
        verdict_file.close()

    _summarise(collected, out, client)
    return 0


def _summarise(rows: list[dict], out: Path, client: GitHubClient) -> None:
    if not rows:
        print("\nnothing scored.")
        return

    scored = [r for r in rows if r["status"] != "error" and r["github_username"]]
    values = [r["score"] for r in scored]
    no_handle = [r for r in rows if not r["github_username"]]
    failed = [r for r in rows if r["status"] == "error" or r["status"] == "failed"]

    lines = [
        "# Cohort scoring summary",
        "",
        f"- CVs processed: **{len(rows)}**",
        f"- Scored against a GitHub profile: **{len(scored)}** "
        f"({len(scored) / len(rows):.0%})",
        f"- No GitHub handle discoverable in the CV: **{len(no_handle)}** "
        "(these cannot be verified at all — a coverage limit of the method, "
        "not a property of the candidates)",
        f"- Resume parsing failures: **{len(failed)}**",
        "",
    ]
    if values:
        lines += [
            "## Score distribution (candidates with a GitHub profile)",
            "",
            f"- mean **{statistics.mean(values):.1f}**, "
            f"median **{statistics.median(values):.1f}**",
            f"- range **{min(values):.1f} – {max(values):.1f}**",
            f"- stdev **{statistics.pstdev(values):.1f}**" if len(values) > 1 else "",
            "",
            "| Band | Candidates |",
            "|---|---|",
        ]
        bands: dict[str, int] = {}
        for r in scored:
            bands[r["band"]] = bands.get(r["band"], 0) + 1
        for band, count in sorted(bands.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {band} | {count} |")

        claims = sum(r["verifiable_claims"] for r in scored)
        verified = sum(r["verified"] for r in scored)
        weak = sum(r["weakly_verified"] for r in scored)
        lines += [
            "",
            "## Claim verification across the cohort",
            "",
            f"- verifiable claims examined: **{claims}**",
            f"- verified in code: **{verified}** ({verified / max(1, claims):.0%})",
            f"- weakly evidenced: **{weak}** ({weak / max(1, claims):.0%})",
            f"- no public evidence: **{claims - verified - weak}** "
            f"({(claims - verified - weak) / max(1, claims):.0%})",
            "",
            f"GitHub API calls this run: {client.calls} (cache hits {client.cache_hits}).",
        ]

    text = "\n".join(l for l in lines if l is not None)
    (out / "summary.md").write_text(text, encoding="utf-8")

    # Pre-filled template for the industry panel. Handing experts a sheet with
    # the candidate names already in it — in the exact spelling tools/ablation.py
    # joins on — removes the single most likely way the validation study loses
    # rows: a name typed slightly differently in the expert spreadsheet.
    template = out / "expert_rankings_template.csv"
    if not template.exists():
        with template.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["candidate", "expert_score", "expert_name", "notes"])
            for row in sorted(scored, key=lambda r: r["candidate"]):
                writer.writerow([row["candidate"], "", "", ""])
        print(f"\nwrote {template} — one row per scorable candidate, "
              "ready for the expert panel")

    print("\n" + text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", help="folder of CV PDFs")
    parser.add_argument("--out", default="data/out")
    parser.add_argument("--cache", default=".cache/github")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--select", metavar="EXPR",
                        help='which candidates to score: "3", "1,4,9", "5-12", '
                             'a name/handle substring, or "all" (default). '
                             'Index numbers come from `cli.py scan <folder>`.')
    parser.add_argument("--scorable-only", action="store_true",
                        help="skip CVs with no discoverable GitHub handle")
    parser.add_argument("--deep-repos", type=int, default=8)
    parser.add_argument("--files-per-repo", type=int, default=6)
    parser.add_argument("--max-files", type=int, default=45)
    parser.add_argument("--budget-per-candidate", type=int, default=0,
                        help="cap GitHub calls per candidate so a cohort run fits a "
                             "fresh rate-limit budget. 0 (default) derives it from the "
                             "remaining quota and the number of candidates selected.")
    parser.add_argument("--offline", action="store_true", help="cache only, no network")
    parser.add_argument("--resume-from", help="existing scores.csv to skip already-done CVs")
    parser.add_argument("--verbose", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
