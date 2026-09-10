#!/usr/bin/env python3
"""
Fit category-level skill-importance weights (Wi) by ridge regression against
an expert-score baseline, on the 70% training split, then check agreement
against the 30% holdout — the train/validate design the project's research
objective calls for (objective 5: automated score vs. expert judgement).

    python tools/fit_weights.py --train data/out/train_candidates.csv \
        --holdout data/out/holdout_candidates.csv --reports data/out/reports

Features are each candidate's `category_scores` from their stored report
(Frontend, Backend, Data & ML, Databases, Mobile, DevOps & Cloud,
Core Languages, Engineering Practice — the same breakdown the recruiter
dashboard already shows), each on a 0-1 scale. The target is the expert
score, also 0-1. Ridge regression (closed-form normal equations, stdlib
only — no numpy/sklearn) keeps the fit stable with only ~22 training rows
against 8 features.

IMPORTANT — the expert scores driving this fit are AI-SIMULATED (see
data/ai_simulated_expert_scores.csv and its source spreadsheet's disclosure
sheet), not a recruited human panel. The weights and correlations this
script prints are only as trustworthy as that baseline. Label them as such
in any report.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from engine.ontology import CATEGORY_GROUPS  # noqa: E402

CATEGORIES = list(CATEGORY_GROUPS.keys())


# ---------------------------------------------------------------------------
# Small stdlib linear algebra — Gaussian elimination with partial pivoting.
# ---------------------------------------------------------------------------

def solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            continue
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= factor * m[col][c]
    return [m[i][n] / m[i][i] if abs(m[i][i]) > 1e-12 else 0.0 for i in range(n)]


def ridge_fit(features: list[list[float]], targets: list[float], lam: float) -> list[float]:
    """OLS with L2 regularisation and an intercept term, via normal equations."""
    n_features = len(features[0])
    x = [[1.0] + row for row in features]  # prepend intercept column
    dim = n_features + 1

    xtx = [[sum(x[k][i] * x[k][j] for k in range(len(x))) for j in range(dim)]
           for i in range(dim)]
    for i in range(1, dim):  # don't regularise the intercept
        xtx[i][i] += lam
    xty = [sum(x[k][i] * targets[k] for k in range(len(x))) for i in range(dim)]

    return solve(xtx, xty)


def predict(weights: list[float], row: list[float]) -> float:
    return weights[0] + sum(w * v for w, v in zip(weights[1:], row))


# ---------------------------------------------------------------------------
# Stats (mirrors tools/ablation.py so results are directly comparable)
# ---------------------------------------------------------------------------

def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else 0.0


def spearman(xs: list[float], ys: list[float]) -> float:
    return pearson(_ranks(xs), _ranks(ys))


def mean_absolute_error(xs: list[float], ys: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(xs, ys)) / len(xs) if xs else 0.0


# ---------------------------------------------------------------------------

def load_candidates(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_report(reports_dir: Path, candidate: str) -> dict | None:
    safe = candidate.strip().replace(" ", "_")
    for candidate_path in reports_dir.glob("*.json"):
        try:
            data = json.loads(candidate_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("candidate") == candidate:
            return data
    return None


def feature_row(report: dict) -> list[float]:
    scores = report.get("category_scores", {})
    return [scores.get(cat, 0.0) / 100.0 for cat in CATEGORIES]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train", required=True)
    parser.add_argument("--holdout", required=True)
    parser.add_argument("--reports", default="data/out/reports")
    parser.add_argument("--ridge", type=float, default=1.0, help="L2 regularisation strength")
    parser.add_argument("--out", help="write results as markdown")
    args = parser.parse_args()

    reports_dir = Path(args.reports)
    train_rows = load_candidates(Path(args.train))
    holdout_rows = load_candidates(Path(args.holdout))

    def build(rows: list[dict]) -> tuple[list[list[float]], list[float], list[float], list[str]]:
        feats, target, engine_scores, names = [], [], [], []
        for row in rows:
            report = load_report(reports_dir, row["candidate"])
            if report is None:
                print(f"  warning: no report found for {row['candidate']!r} — skipped")
                continue
            feats.append(feature_row(report))
            target.append(float(row["ai_expert_score"]) / 100.0)
            engine_scores.append(float(row["engine_score"]))
            names.append(row["candidate"])
        return feats, target, engine_scores, names

    print("Loading train set...")
    train_x, train_y, train_engine, train_names = build(train_rows)
    print("Loading holdout set...")
    hold_x, hold_y, hold_engine, hold_names = build(holdout_rows)

    if len(train_x) < len(CATEGORIES) + 2:
        print(f"\nWARNING: only {len(train_x)} training rows for {len(CATEGORIES)} "
              "features + intercept. Ridge keeps this numerically stable, but treat "
              "the fitted weights as illustrative, not a reliable point estimate — "
              "say so explicitly if these numbers go in the dissertation.")

    weights = ridge_fit(train_x, train_y, args.ridge)

    print(f"\nFitted (ridge λ={args.ridge}) on {len(train_x)} training candidates:")
    print(f"  intercept: {weights[0]:.3f}")
    for cat, w in zip(CATEGORIES, weights[1:]):
        print(f"  {cat:<22} Wi = {w:+.3f}")

    train_pred = [predict(weights, row) * 100 for row in train_x]
    hold_pred = [predict(weights, row) * 100 for row in hold_x]
    train_y100 = [y * 100 for y in train_y]
    hold_y100 = [y * 100 for y in hold_y]

    def report_split(label: str, pred: list[float], expert: list[float],
                      engine: list[float], names: list[str]) -> list[str]:
        rho_fit = spearman(pred, expert)
        r_fit = pearson(pred, expert)
        mae_fit = mean_absolute_error(pred, expert)
        rho_base = spearman(engine, expert)
        r_base = pearson(engine, expert)
        mae_base = mean_absolute_error(engine, expert)
        print(f"\n{label} (n={len(names)}):")
        print(f"  learned-weight fit   vs AI-expert:  rho={rho_fit:.3f}  r={r_fit:.3f}  MAE={mae_fit:.1f}")
        print(f"  existing engine score vs AI-expert:  rho={rho_base:.3f}  r={r_base:.3f}  MAE={mae_base:.1f}")
        return [
            f"### {label} (n={len(names)})", "",
            "| Model | Spearman rho | Pearson r | MAE |", "|---|---|---|---|",
            f"| learned category weights | {rho_fit:.3f} | {r_fit:.3f} | {mae_fit:.1f} |",
            f"| existing engine formula | {rho_base:.3f} | {r_base:.3f} | {mae_base:.1f} |",
            "",
        ]

    lines = [
        "# Category-weight regression — AI-simulated expert baseline", "",
        "**Expert scores used here are AI-simulated (LLM-as-industry-expert), "
        "not a recruited human panel.** See `data/ai_simulated_expert_scores.csv` "
        "and its source spreadsheet's disclosure sheet before citing these numbers "
        "as a validation result.", "",
        f"Ridge lambda: {args.ridge}. Features: {', '.join(CATEGORIES)}.", "",
        "## Fitted weights", "",
        "| Category | Wi |", "|---|---|",
        f"| intercept | {weights[0]:.3f} |",
    ]
    for cat, w in zip(CATEGORIES, weights[1:]):
        lines.append(f"| {cat} | {w:+.3f} |")
    lines.append("")
    lines.append("## Agreement with the AI-simulated expert baseline")
    lines.append("")
    lines += report_split("Train (fit on this set — not a validation number)",
                           train_pred, train_y100, train_engine, train_names)
    lines += report_split("Holdout (unseen during fitting — the real check)",
                           hold_pred, hold_y100, hold_engine, hold_names)

    if args.out:
        Path(args.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"\nwrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
