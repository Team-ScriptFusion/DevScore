#!/usr/bin/env python3
"""
Join a batch.py cohort run against an expert-score sheet, then split the
matched candidates 70/30 for weight training and holdout validation.

    python tools/split_cohort.py data/out/scores.csv data/ai_simulated_expert_scores.csv \
        --out data/out

IMPORTANT — the expert scores this project currently has on file
(`data/ai_simulated_expert_scores.csv`) are AI-SIMULATED: produced by an LLM
role-playing as an industry hiring expert, not a recruited human panel. Every
output of this script carries that label forward so it cannot be mistaken
for genuine expert data downstream. See the "Methodology & Disclosure" sheet
in the original spreadsheet before using these results in any writeup.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path


def load_scores(path: Path) -> dict[str, dict]:
    by_file: dict[str, dict] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            by_file[row["file"].strip()] = row
    return by_file


def load_expert_sheet(path: Path) -> dict[str, dict]:
    by_file: dict[str, dict] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            fname = (row.get("File Name") or "").strip()
            if not fname:
                continue
            by_file[fname] = row
    return by_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scores", help="batch.py output: data/out/scores.csv")
    parser.add_argument("experts", help="expert-score sheet CSV, keyed by File Name")
    parser.add_argument("--out", default="data/out", help="output directory")
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--seed", type=int, default=20260905)
    args = parser.parse_args()

    scores = load_scores(Path(args.scores))
    experts = load_expert_sheet(Path(args.experts))

    matched: list[dict] = []
    unmatched_no_expert: list[str] = []
    unmatched_not_scored: list[str] = []

    for fname, expert_row in experts.items():
        score_row = scores.get(fname)
        if score_row is None:
            unmatched_not_scored.append(fname)
            continue
        if score_row.get("status") != "success":
            unmatched_not_scored.append(fname)
            continue
        matched.append({
            "candidate": score_row["candidate"],
            "file": fname,
            "github_username": score_row["github_username"],
            "engine_score": score_row["score"],
            "ai_expert_score": expert_row["Overall AI-Expert Score (/100)"],
        })

    scored_files = {r["file"] for r in scores.values() if r.get("status") == "success"}
    for fname in scored_files - set(experts):
        unmatched_no_expert.append(fname)

    print(f"{len(matched)} candidates matched (scored + have an expert-sheet row)")
    if unmatched_not_scored:
        print(f"{len(unmatched_not_scored)} skipped — no successful score: "
              f"{', '.join(unmatched_not_scored)}")
    if unmatched_no_expert:
        print(f"{len(unmatched_no_expert)} skipped — scored but no expert-sheet row: "
              f"{', '.join(unmatched_no_expert)}")

    matched.sort(key=lambda r: r["candidate"])
    rng = random.Random(args.seed)
    shuffled = matched[:]
    rng.shuffle(shuffled)

    n_train = round(len(shuffled) * args.train_fraction)
    train, holdout = shuffled[:n_train], shuffled[n_train:]
    print(f"split: {len(train)} train / {len(holdout)} holdout "
          f"(seed={args.seed}, target fraction={args.train_fraction:.0%})")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = ["candidate", "file", "github_username", "engine_score", "ai_expert_score"]

    for name, rows in (("train_candidates.csv", train), ("holdout_candidates.csv", holdout)):
        with (out_dir / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {out_dir / name}")

    # Also emit an ablation.py-compatible file, clearly labelled as
    # AI-simulated rather than genuine recruited-expert data.
    rankings_path = Path("data/ai_expert_rankings.csv")
    with rankings_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate", "expert_score", "source"])
        for row in matched:
            writer.writerow([row["candidate"], row["ai_expert_score"], "ai_simulated"])
    print(f"wrote {rankings_path} (source column marks every row 'ai_simulated')")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
