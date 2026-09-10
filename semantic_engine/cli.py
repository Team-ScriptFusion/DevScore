#!/usr/bin/env python3
"""
DevScore Engine command line.

    python cli.py scan  data/cvs                 # indexed roster: who can be scored?
    python cli.py score --from data/cvs --select 4          # score candidate #4
    python cli.py score --from data/cvs --select 1,4,7-12   # score a selection
    python cli.py score --from data/cvs --select jayasuriya # select by name/handle
    python cli.py score resume.pdf --github octocat --html out.html --json out.json
    python cli.py score resume.pdf --boolean     # the proposal's original Vi in {0,1}
    python cli.py parse resume.pdf               # resume side only, no API calls
    python cli.py cohort data/out/reports        # selectable dashboard over a batch run

Set GITHUB_TOKEN before anything that touches the API. Without it you get
60 requests an hour, which is roughly half of one candidate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Windows consoles still default to cp1252, which cannot encode the box and
# block characters this CLI prints. Force UTF-8 rather than degrading the
# output everywhere else.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from engine.github.client import GitHubClient  # noqa: E402
from engine.pipeline import score_resume  # noqa: E402
from engine.resume.parser import parse_resume  # noqa: E402
from engine.selection import SelectionError, build_roster, select  # noqa: E402

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, YELLOW, RED, CYAN = "\033[32m", "\033[33m", "\033[31m", "\033[36m"

STATUS_STYLE = {
    "verified": (GREEN, "VERIFIED"),
    "weakly_verified": (YELLOW, "WEAK"),
    "unverified": (RED, "UNVERIFIED"),
    "not_verifiable": (DIM, "N/A"),
    "unclaimed_strength": (CYAN, "UNCLAIMED"),
}


def _bar(value: float, width: int = 22) -> str:
    filled = int(round(value * width))
    return "█" * filled + "·" * (width - filled)


def print_report(report) -> None:
    d = report.to_dict()
    print()
    print(f"{BOLD}{'═' * 78}{RESET}")
    print(f"{BOLD}  {d['candidate']}{RESET}")
    if d["github_username"]:
        print(f"  github.com/{d['github_username']}")
    print(f"{BOLD}{'═' * 78}{RESET}")

    colour = GREEN if d["score"] >= 65 else YELLOW if d["score"] >= 40 else RED
    print(f"\n  {BOLD}{colour}Job Readiness Score: {d['score']:.1f}/100{RESET}  "
          f"({d['band']})")
    b = d["breakdown"]
    print(f"  {DIM}ratio {b['raw_ratio']:.1f}  {b['shrinkage']:+.1f} small-sample  "
          f"−{b['integrity_penalty']:.1f} integrity  +{b['breadth_bonus']:.1f} breadth  ·  "
          f"confidence {d['confidence']:.0%}{RESET}")

    c = d["counts"]
    print(f"\n  {c['verified']} verified · {c['weakly_verified']} weak · "
          f"{c['unverified']} unverified   (of {c['verifiable_claims']} verifiable claims, "
          f"{c['claimed']} total)")

    if d["category_scores"]:
        print(f"\n  {BOLD}By area{RESET}")
        for area, value in sorted(d["category_scores"].items(), key=lambda kv: -kv[1]):
            print(f"    {area:<22} {_bar(value / 100)} {value:5.1f}")

    print(f"\n  {BOLD}Evidence gap{RESET}")
    rows = [v for v in d["verdicts"] if v["claimed"] and v["verifiable"] and v["weight"] > 0]
    rows += [v for v in d["verdicts"] if v["unclaimed_evidence"]]
    if not rows:
        print(f"    {DIM}no verifiable technical claims found{RESET}")
    for v in rows:
        colour, label = STATUS_STYLE.get(v["status"], ("", v["status"].upper()))
        sig = v["signals"]
        print(f"    {colour}{label:<11}{RESET} {v['skill']:<22} "
              f"W={v['weight']:.2f} V={v['verification']:.2f}  "
              f"{DIM}[{v['tier']}] E{sig['evidence_strength']:.2f} "
              f"C{sig['complexity']:.2f} D{sig['depth']:.2f} "
              f"R{sig['recency']:.2f} Q{sig['craft']:.2f}{RESET}")
        if v["repos"]:
            print(f"      {DIM}↳ {', '.join(v['repos'][:4])}"
                  f"{' …' if len(v['repos']) > 4 else ''} · "
                  f"{v['files_analyzed']} files, {v['loc_analyzed']:,} LOC{RESET}")

    bindings = d.get("project_bindings") or []
    if bindings:
        print(f"\n  {BOLD}CV projects vs. repositories{RESET}")
        for b in bindings:
            if b["repo"] and b["has_conflict"]:
                colour, tag = RED, "MISMATCH"
            elif b["repo"] and b["inspected"]:
                colour, tag = GREEN, "CONSISTENT"
            elif b["repo"]:
                colour, tag = DIM, "NOT SAMPLED"
            else:
                colour, tag = DIM, "NO REPO"
            how = b["method"] + (f" {b['confidence']:.0%}" if b["method"] == "name_match" else "")
            print(f"    {colour}{tag:<12}{RESET} {b['project_title'][:34]:<34} "
                  f"{DIM}-> {b['repo'] or '—'}  [{how}]{RESET}")
            if b["has_conflict"]:
                print(f"      {RED}claims {', '.join(b['missing_skills'])}{RESET}"
                      f"{DIM} — no sign of it in that repository{RESET}")

    if d.get("github_username"):
        auth = d.get("authorship") or {}
        if auth.get("total"):
            print(f"\n  {BOLD}Commit authorship{RESET}  "
                  f"{auth['mine']} theirs · {auth['disputed']} disputed · "
                  f"{auth['other']} others  "
                  f"{DIM}({auth['ownership_ratio']:.0%} of the sampled log){RESET}")

    unrecognised = [v for v in d["verdicts"] if v["category"] == "uncategorized"]
    if unrecognised:
        print(f"\n  {DIM}Listed but not in the ontology: "
              f"{', '.join(v['skill'] for v in unrecognised[:12])}{RESET}")

    if d["warnings"]:
        print(f"\n  {BOLD}Notes{RESET}")
        for warning in d["warnings"]:
            print(f"    {YELLOW}!{RESET} {warning}")
    print()


def cmd_score(args) -> int:
    if args.from_folder:
        return cmd_select_score(args.from_folder, args.select or "all", args)

    client = GitHubClient(
        token=args.token or os.environ.get("GITHUB_TOKEN"),
        cache_dir=args.cache,
        offline=args.offline,
    )
    report = score_resume(
        args.resume,
        args.github,
        client=client,
        boolean_mode=args.boolean,
        max_repos_deep=args.deep_repos,
        files_per_repo=args.files_per_repo,
    )
    if args.json:
        Path(args.json).write_text(
            json.dumps(report.to_dict(include_raw=args.raw), indent=2), encoding="utf-8"
        )
        print(f"wrote {args.json}")
    if args.html:
        from engine.report.html import render_report

        Path(args.html).write_text(render_report(report), encoding="utf-8")
        print(f"wrote {args.html}")
    if not args.quiet:
        print_report(report)
    print(f"{DIM}github api calls: {client.calls}  cache hits: {client.cache_hits}  "
          f"remaining: {client.rate_remaining}{RESET}")
    return 0


def cmd_parse(args) -> int:
    profile = parse_resume(args.resume)
    print(json.dumps(profile.to_dict(), indent=2))
    return 0


def cmd_scan(args) -> int:
    """Indexed roster. The index numbers are what --select consumes."""
    roster = build_roster(args.folder)
    if not roster:
        print(f"no PDFs found in {args.folder}")
        return 1

    scorable = [e for e in roster if e.scorable]
    disputed = [e for e in roster if e.name_disputed]

    name_w = min(32, max(len(e.name) for e in roster))
    print(f"{len(roster)} CVs in {args.folder}\n")
    print(f"  {'#':>3}  {'CANDIDATE (from CV)':<{name_w}}  {'GITHUB':<22} {'SKILLS':>6}  NOTE")
    print(f"  {'-' * 3}  {'-' * name_w}  {'-' * 22} {'-' * 6}  ----")

    overridden = [e for e in roster if e.handle_source == "override"]
    for entry in roster:
        mark = GREEN if entry.scorable else RED
        handle = entry.github_username or "no handle"
        notes = []
        if entry.handle_source == "override":
            notes.append(f"{CYAN}handle from handle_overrides.json{RESET}")
        if entry.name_source != "cv":
            notes.append(f"{YELLOW}name from filename{RESET}")
        if entry.name_disputed:
            notes.append(f"{CYAN}filename says '{entry.filename_label}'{RESET}")
        if not entry.status.startswith("success"):
            notes.append(f"{RED}{entry.status}{RESET}")
        print(f"  {entry.index:>3}  {entry.name[:name_w]:<{name_w}}  "
              f"{mark}{handle[:22]:<22}{RESET} {entry.skill_count:>6}  {' · '.join(notes)}")

    print(f"\n  {len(scorable)}/{len(roster)} have a GitHub handle and can be scored "
          f"({len(scorable) / len(roster):.0%}).")
    if overridden:
        print(f"  {len(overridden)} handle(s) supplied via handle_overrides.json "
              f"(CV named no account).")
    if disputed:
        print(f"  {len(disputed)} CV(s) carry a different name in the filename than in the "
              f"document — Drive appends the UPLOADER's name, so the CV's own name wins.")
    print(f'\n  Score a selection:  py -3 batch.py {args.folder} --select "1,4,7-12"')
    print(f"  Score one:          py -3 cli.py score --from {args.folder} --select 4")
    print(f"  Supply a handle:    add it to {args.folder}/handle_overrides.json")
    return 0


def cmd_select_score(folder: str, expression: str, args) -> int:
    """Score a chosen subset straight from the roster, printing each report."""
    roster = build_roster(folder)
    try:
        picked = select(roster, expression)
    except SelectionError as exc:
        print(f"{RED}{exc}{RESET}")
        return 1

    client = GitHubClient(token=args.token or os.environ.get("GITHUB_TOKEN"),
                          cache_dir=args.cache, offline=args.offline)
    print(f"scoring {len(picked)} of {len(roster)} candidates\n")
    for entry in picked:
        # Precedence: an explicit --github on the command line, then whatever
        # the roster resolved (CV handle, or handle_overrides.json).
        handle = args.github or entry.github_username
        if entry.handle_source == "override" and not args.github:
            print(f"{DIM}  (handle @{handle} from handle_overrides.json"
                  f"{': ' + entry.handle_note if entry.handle_note else ''}){RESET}")
        report = score_resume(
            entry.path, handle, client=client,
            candidate_name=entry.name, boolean_mode=args.boolean,
            max_repos_deep=args.deep_repos, files_per_repo=args.files_per_repo,
        )
        if not args.quiet:
            print_report(report)
        else:
            print(f"  {report.score:5.1f}  {report.candidate}")
        if args.html and len(picked) == 1:
            from engine.report.html import render_report
            Path(args.html).write_text(render_report(report), encoding="utf-8")
            print(f"wrote {args.html}")
    print(f"{DIM}github api calls: {client.calls}  cache hits: {client.cache_hits}{RESET}")
    return 0


def cmd_cohort(args) -> int:
    """Build the selectable cohort dashboard from an existing batch run."""
    from engine.report.cohort import load_cohort, render_cohort

    cohort = load_cohort(args.reports)
    if not cohort:
        print(f"no report JSON files in {args.reports} — run batch.py first")
        return 1
    Path(args.out).write_text(render_cohort(cohort, args.title), encoding="utf-8")
    scorable = sum(1 for c in cohort if c["gh"])
    print(f"wrote {args.out}  ({len(cohort)} candidates, {scorable} scorable)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="devscore", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("score", help="full claim-vs-evidence scoring")
    p.add_argument("resume", nargs="?", help="a CV PDF (omit when using --from)")
    p.add_argument("--from", dest="from_folder", metavar="FOLDER",
                   help="pick candidates out of a CV folder instead of naming a file")
    p.add_argument("--select", metavar="EXPR",
                   help="with --from: \"3\", \"1,4,9\", \"5-12\" or a name/handle substring")
    p.add_argument("--github", help="override the handle found in the CV")
    p.add_argument("--token", help="GitHub token (defaults to $GITHUB_TOKEN)")
    p.add_argument("--cache", default=".cache/github")
    p.add_argument("--offline", action="store_true", help="cache only, no network")
    p.add_argument("--boolean", action="store_true",
                   help="use the proposal's original Vi ∈ {0,1} formulation")
    p.add_argument("--deep-repos", type=int, default=12)
    p.add_argument("--files-per-repo", type=int, default=10)
    p.add_argument("--json", help="write the full report as JSON")
    p.add_argument("--html", help="write a standalone HTML dashboard")
    p.add_argument("--raw", action="store_true", help="include raw resume/github data in JSON")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("parse", help="resume side only — no GitHub calls")
    p.add_argument("resume")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("scan", help="indexed candidate roster for a CV folder")
    p.add_argument("folder")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("cohort", help="selectable dashboard over a finished batch run")
    p.add_argument("reports", nargs="?", default="data/out/reports",
                   help="folder of report JSON files (default: data/out/reports)")
    p.add_argument("--out", default="data/out/cohort.html")
    p.add_argument("--title", default="Candidate cohort")
    p.set_defaults(func=cmd_cohort)

    args = parser.parse_args()
    if getattr(args, "command", None) == "score" and not args.resume and not args.from_folder:
        parser.error("give a resume path, or --from FOLDER [--select EXPR]")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
