#!/usr/bin/env python3
"""
Re-derive the `scarcity` axis of every difficulty weight from real data.

    python tools/calibrate_weights.py --jobs data/job_descriptions.jsonl \
                                      --verdicts data/out/verdicts.csv \
                                      --out data/out/weights.md

Why this exists
---------------
`Wᵢ = 0.55·depth + 0.45·scarcity`. The `depth` axis is a property of the
technology and does not drift — C++ will not become conceptually easier next
year. The `scarcity` axis is *market data* and drifts constantly, which is
exactly why the two were separated: this tool can rewrite half of every
weight without anyone re-litigating the other half.

The definition used here
------------------------
Scarcity is not demand. A skill every posting asks for and every graduate has
is not scarce — it is table stakes, and weighting it highly would reward the
crowd. Scarcity is the *ratio*:

    scarcity_rawᵢ  =  demand_shareᵢ / (supply_shareᵢ + ε)

  demand_share  fraction of job postings that ask for skill i
                (from the scraped corpus the research design specifies)
  supply_share  fraction of scored candidates who VERIFIED skill i in code
                (from verdicts.csv — not from what they claimed)

Using verified supply rather than claimed supply is the point. Claims are the
thing this whole project exists not to trust, and a skill everyone lists but
nobody can prove is scarce in the only sense a recruiter cares about.

Raw ratios are then mapped to 1–5 by quintile rather than by absolute
threshold, so the axis stays on its defined scale no matter how large or
small the corpus is.

Output
------
A markdown table of old vs. new weights and the patch to apply to
`engine/ontology.py`. Nothing is written to the ontology automatically:
weights decide scores, and a score in a research deliverable does not get to
change because a script ran unattended. A human applies the diff, and the
git history records who and when.

Input formats
-------------
  --jobs      JSONL, one posting per line, any of these keys used as text:
              {"description": "..."} / {"text": ...} / {"title","requirements"}
              A plain .txt file with one posting per line also works.
  --verdicts  verdicts.csv from batch.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from engine import ontology  # noqa: E402

EPSILON = 0.02  # keeps a never-verified skill from dividing by zero


def load_postings(path: Path) -> list[str]:
    postings: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = " ".join(
                str(data.get(key, ""))
                for key in ("title", "description", "text", "requirements", "skills")
            )
        else:
            text = line
        if text.strip():
            postings.append(text)
    return postings


def demand_counts(postings: list[str]) -> Counter[str]:
    """One count per posting per skill — a posting saying "React" nine times
    is still one employer asking for React."""
    counts: Counter[str] = Counter()
    for posting in postings:
        seen: set[str] = set()
        for pattern, canonical in ontology.ALIAS_PATTERNS:
            if canonical not in seen and pattern.search(posting):
                seen.add(canonical)
        counts.update(seen)
    return counts


def verified_supply(path: Path) -> tuple[Counter[str], int]:
    """Candidates who reached `used` or better for each skill."""
    counts: Counter[str] = Counter()
    candidates: set[str] = set()
    strong = {"used", "applied", "mastered"}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            candidate = row.get("candidate") or ""
            if not candidate:
                continue
            candidates.add(candidate)
            if (row.get("tier") or "") in strong:
                counts[row["skill"]] += 1
    return counts, len(candidates)


def quintile_map(values: dict[str, float]) -> dict[str, int]:
    """Rank skills by raw scarcity, then split into five equal bands."""
    ordered = sorted(values, key=lambda name: values[name])
    n = len(ordered)
    out: dict[str, int] = {}
    for index, name in enumerate(ordered):
        out[name] = min(5, int(index / max(1, n) * 5) + 1)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", required=True, help="JSONL/TXT corpus of job postings")
    parser.add_argument("--verdicts", help="verdicts.csv from batch.py (verified supply)")
    parser.add_argument("--out", help="write the report as markdown")
    parser.add_argument("--min-postings", type=int, default=30)
    args = parser.parse_args()

    postings = load_postings(Path(args.jobs))
    if len(postings) < args.min_postings:
        print(f"only {len(postings)} postings — too few to recalibrate a market axis.")
        print(f"Collect at least {args.min_postings}, or pass --min-postings to override.")
        return 1

    demand = demand_counts(postings)
    supply: Counter[str] = Counter()
    cohort = 0
    if args.verdicts:
        supply, cohort = verified_supply(Path(args.verdicts))

    verifiable = [s for s in ontology.SKILLS.values() if s.verifiable]

    raw: dict[str, float] = {}
    for skill in verifiable:
        demand_share = demand.get(skill.name, 0) / len(postings)
        if cohort:
            supply_share = supply.get(skill.name, 0) / cohort
            raw[skill.name] = demand_share / (supply_share + EPSILON)
        else:
            # No cohort data — fall back to pure demand, and say so.
            raw[skill.name] = demand_share

    new_scarcity = quintile_map(raw)

    rows = []
    for skill in sorted(verifiable, key=lambda s: -raw[s.name]):
        old_weight = skill.weight
        new_weight = ontology.derive_weight(skill.depth, new_scarcity[skill.name])
        rows.append((skill, new_scarcity[skill.name], old_weight, new_weight,
                     demand.get(skill.name, 0), supply.get(skill.name, 0), raw[skill.name]))

    basis = ("demand ÷ verified supply" if cohort else "demand only (no --verdicts supplied)")
    lines = [
        "# Difficulty-weight recalibration",
        "",
        f"- Job postings analysed: **{len(postings)}**",
        f"- Cohort candidates for supply: **{cohort or 'n/a'}**",
        f"- Scarcity basis: **{basis}**",
        "",
        "`depth` is unchanged by design — it is a property of the technology, not "
        "of the market. Only `scarcity` is re-derived here.",
        "",
        "| Skill | depth | scarcity old→new | W old→new | Δ | postings | verified |",
        "|---|---|---|---|---|---|---|",
    ]

    changed = 0
    for skill, scarcity, old_w, new_w, demand_n, supply_n, _ in rows:
        delta = new_w - old_w
        if skill.scarcity != scarcity:
            changed += 1
        flag = "" if abs(delta) < 0.005 else f"**{delta:+.2f}**"
        lines.append(
            f"| {skill.name} | {skill.depth} | {skill.scarcity} → {scarcity} | "
            f"{old_w:.2f} → {new_w:.2f} | {flag} | {demand_n} | {supply_n} |"
        )

    lines += [
        "",
        f"**{changed} of {len(rows)} skills change scarcity band.**",
        "",
        "## Applying this",
        "",
        "Nothing is written to `engine/ontology.py` automatically. Weights decide "
        "scores, and a score in a research deliverable does not get to change "
        "because a script ran unattended — apply the values below by hand so the "
        "git history records who changed them and when, then re-run "
        "`tools/ablation.py` to confirm the recalibration actually improved "
        "agreement with the expert baseline rather than just moving numbers.",
        "",
        "```python",
    ]
    for skill, scarcity, _, _, _, _, _ in rows:
        if skill.scarcity != scarcity:
            lines.append(f'# {skill.name}: scarcity {skill.scarcity} -> {scarcity}')
    lines.append("```")

    text = "\n".join(lines)
    print(text if not args.out else f"{changed} scarcity bands change; see {args.out}")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
