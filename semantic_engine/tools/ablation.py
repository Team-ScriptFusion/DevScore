#!/usr/bin/env python3
"""
Ablation study — does the continuous scoring model actually beat the
proposal's original boolean formula?

    python tools/ablation.py data/out/reports --experts data/expert_rankings.csv
    python tools/ablation.py data/out/reports          # agreement between variants only

This is research objective 5 made runnable. The proposal defines

    I = ( Σ Wᵢ · Vᵢ ) / ( Σ Wᵢ ) × 100    with Vᵢ ∈ {0, 1}

and the engine extends Vᵢ to a continuous blend of five signals. That
extension is a *claim*, and a claim in a research deliverable has to be
tested rather than asserted. This script recomputes every stored report
under several Vᵢ formulations and ranks them against the industry experts'
manual ordering.

Variants compared:

    boolean         the proposal as written — Vᵢ ∈ {0,1}
    evidence_only   Vᵢ = evidence strength (tiers, no code analysis)
    no_complexity   the full model with the static-analysis signal removed
    no_recency      the full model with time decay removed
    full            the shipped model

`no_complexity` is the important row. It isolates exactly what the AST and
token analysis contribute: if `full` does not beat `no_complexity` against
the expert baseline, then reading the code added nothing and the honest
conclusion is to say so, not to keep the component because it was hard to
build.

Expert CSV format (one row per candidate the experts ranked):

    candidate,expert_score
    Anura Perera,72
    ...

`expert_score` may be a 0–100 rating or an ordinal rank; Spearman only uses
the ordering, so either works. Pearson is reported too but should be read
with care unless the experts gave genuine interval ratings.

Statistics are computed with the standard library — no scipy — so this runs
anywhere the engine runs. Spearman is Pearson on ranks with average ties;
the permutation test avoids assuming a t-distribution on n ≈ 30.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from engine.models import TIER_APPLIED, TIER_MASTERED, TIER_USED  # noqa: E402
from engine.scoring.engine import (  # noqa: E402
    MAX_BREADTH_BONUS, MAX_INTEGRITY_PENALTY, SIGNAL_WEIGHTS,
)

VARIANTS: dict[str, dict[str, float] | None] = {
    "boolean": None,  # special-cased
    "evidence_only": {"evidence_strength": 1.0},
    "no_complexity": {k: v for k, v in SIGNAL_WEIGHTS.items() if k != "complexity"},
    "no_recency": {k: v for k, v in SIGNAL_WEIGHTS.items() if k != "recency"},
    "full": dict(SIGNAL_WEIGHTS),
}


def _rescore(report: dict, variant: str) -> float:
    """Recompute the headline score from a stored report under one variant."""
    weights = VARIANTS[variant]
    scored = [
        v for v in report["verdicts"]
        if v["claimed"] and v["verifiable"] and v["weight"] > 0
    ]
    if not scored:
        return 0.0

    total_weight = sum(v["weight"] for v in scored)
    total = 0.0
    for v in scored:
        if variant == "boolean":
            value = 1.0 if v["tier"] in (TIER_USED, TIER_APPLIED, TIER_MASTERED) else 0.0
        else:
            assert weights is not None
            denominator = sum(weights.values())
            value = sum(weights[k] * v["signals"][k] for k in weights) / denominator
            value = min(value, v["signals"]["evidence_strength"])
        total += v["weight"] * value

    base = total / total_weight * 100.0

    # Adjustments are part of the model under test, so they are reapplied
    # identically for every variant — otherwise the comparison would be
    # measuring the adjustments rather than Vᵢ.
    unverified_weight = sum(v["weight"] for v in scored if v["tier"] == "none")
    penalty = MAX_INTEGRITY_PENALTY * (unverified_weight / total_weight) * report["confidence"]
    bonus = min(MAX_BREADTH_BONUS, report["breakdown"]["breadth_bonus"])
    return max(0.0, min(100.0, base - penalty + bonus))


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _ranks(values: list[float]) -> list[float]:
    """Average ranks, so tied scores do not distort Spearman."""
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


def permutation_p(xs: list[float], ys: list[float], trials: int = 10_000) -> float:
    """
    Two-sided p for Spearman by shuffling one variable.

    With n around 30 candidates, the asymptotic t-approximation is shaky;
    a permutation test makes no distributional assumption at all.
    """
    if len(xs) < 4:
        return 1.0
    observed = abs(spearman(xs, ys))
    shuffled = list(ys)
    rng = random.Random(20260903)
    hits = 0
    for _ in range(trials):
        rng.shuffle(shuffled)
        if abs(spearman(xs, shuffled)) >= observed:
            hits += 1
    return (hits + 1) / (trials + 1)


def mean_absolute_error(xs: list[float], ys: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(xs, ys)) / len(xs) if xs else 0.0


def top_k_overlap(model: list[float], expert: list[float], names: list[str], k: int) -> float:
    """
    Fraction of the experts' top-k that the model also puts in its top-k.

    Arguably the metric that matters most in practice: a recruiter looks at
    a shortlist, not at a correlation coefficient.
    """
    k = min(k, len(names))
    if k == 0:
        return 0.0
    model_top = {n for n, _ in sorted(zip(names, model), key=lambda p: -p[1])[:k]}
    expert_top = {n for n, _ in sorted(zip(names, expert), key=lambda p: -p[1])[:k]}
    return len(model_top & expert_top) / k


# ---------------------------------------------------------------------------

def load_reports(folder: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "verdicts" in data and data.get("candidate"):
            out[data["candidate"]] = data
    return out


def load_experts(path: Path) -> dict[str, float]:
    ratings: dict[str, float] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("candidate") or "").strip()
            raw = (row.get("expert_score") or row.get("rank") or "").strip()
            if not name or not raw:
                continue
            try:
                ratings[name] = float(raw)
            except ValueError:
                continue
    return ratings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reports", help="folder of report JSON files (data/out/reports)")
    parser.add_argument("--experts", help="CSV: candidate,expert_score")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out", help="write results as markdown")
    args = parser.parse_args()

    reports = load_reports(Path(args.reports))
    if not reports:
        print(f"no reports found in {args.reports}")
        return 1

    # Only candidates we could actually verify belong in the comparison; a
    # candidate with no GitHub handle scores 0 under every variant and would
    # inflate every correlation identically without telling us anything.
    usable = {n: r for n, r in reports.items() if r.get("github_username")}
    print(f"{len(reports)} reports, {len(usable)} with a GitHub profile\n")

    names = sorted(usable)
    variant_scores = {
        variant: [_rescore(usable[n], variant) for n in names]
        for variant in VARIANTS
    }

    lines: list[str] = ["# Ablation study", "",
                        f"Candidates with verifiable GitHub profiles: **{len(names)}**", ""]

    if args.experts:
        experts = load_experts(Path(args.experts))
        matched = [n for n in names if n in experts]
        if len(matched) < 4:
            print(f"only {len(matched)} candidates matched the expert file — "
                  "cannot compute a meaningful correlation.")
            print("Check that the 'candidate' column matches the names in scores.csv.")
            return 1

        expert_values = [experts[n] for n in matched]
        lines += [
            f"Expert-rated candidates matched: **{len(matched)}**", "",
            "## Agreement with the expert baseline", "",
            "| Variant | Spearman ρ | p (permutation) | Pearson r | MAE | "
            f"Top-{args.top_k} overlap |",
            "|---|---|---|---|---|---|",
        ]
        print(f"{'variant':<16} {'spearman':>9} {'p':>8} {'pearson':>9} "
              f"{'MAE':>7} {'top-' + str(args.top_k):>8}")
        print("-" * 62)
        for variant in VARIANTS:
            values = [variant_scores[variant][names.index(n)] for n in matched]
            rho = spearman(values, expert_values)
            p = permutation_p(values, expert_values)
            r = pearson(values, expert_values)
            mae = mean_absolute_error(values, expert_values)
            overlap = top_k_overlap(values, expert_values, matched, args.top_k)
            print(f"{variant:<16} {rho:>9.3f} {p:>8.4f} {r:>9.3f} {mae:>7.1f} {overlap:>8.0%}")
            lines.append(f"| `{variant}` | {rho:.3f} | {p:.4f} | {r:.3f} | "
                         f"{mae:.1f} | {overlap:.0%} |")

        full_rho = spearman([variant_scores["full"][names.index(n)] for n in matched],
                            expert_values)
        nc_rho = spearman([variant_scores["no_complexity"][names.index(n)] for n in matched],
                          expert_values)
        bool_rho = spearman([variant_scores["boolean"][names.index(n)] for n in matched],
                            expert_values)
        lines += [
            "",
            "## Reading this table",
            "",
            f"- Continuous vs. the proposal's boolean Vᵢ: ρ {bool_rho:.3f} → {full_rho:.3f} "
            f"(**{full_rho - bool_rho:+.3f}**).",
            f"- Contribution of static code analysis: ρ {nc_rho:.3f} without it → "
            f"{full_rho:.3f} with it (**{full_rho - nc_rho:+.3f}**).",
            "",
            "If the second line is not clearly positive, the static-analysis component "
            "is not earning its place and the write-up should report that rather than "
            "defend it. A negative result about a component you built is still a result.",
        ]
    else:
        lines += ["## Agreement between variants (no expert file supplied)", "",
                  "| Variant | mean | vs `full` (ρ) |", "|---|---|---|"]
        print(f"{'variant':<16} {'mean':>7} {'rho vs full':>12}")
        print("-" * 38)
        full = variant_scores["full"]
        for variant, values in variant_scores.items():
            mean = sum(values) / len(values)
            rho = spearman(values, full)
            print(f"{variant:<16} {mean:>7.1f} {rho:>12.3f}")
            lines.append(f"| `{variant}` | {mean:.1f} | {rho:.3f} |")
        lines += [
            "",
            "These are internal consistency checks only. Supply `--experts` with the "
            "industry panel's rankings to test the model against ground truth — that "
            "comparison is the actual research result.",
        ]

    if args.out:
        Path(args.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
