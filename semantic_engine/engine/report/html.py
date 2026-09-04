"""
Standalone HTML rendering of a ReadinessReport — the Evidence Gap view.

This is the reference implementation of FR 47–48 (recruiter dashboard,
candidate profile detail) as a single self-contained file: no CDN, no build
step, no framework. The React dashboard in the main repo should render the
same information from the same JSON; having a zero-dependency renderer here
means the scoring engine can be reviewed, demoed and marked without the MERN
stack running at all.

Two presentation decisions carry real weight:

  THE SCORE IS NEVER SHOWN ALONE. It always appears beside its confidence
  and its decomposition (base − integrity + breadth). A single number with
  no provenance is exactly the "gut feeling with a decimal point" the
  project exists to replace.

  UNVERIFIED IS NOT RED-FLAGGED AS DISHONESTY. The label is "no public
  evidence found", and the copy says so. A candidate whose work lives in
  private or company repositories is invisible to this system, and a
  dashboard that renders that as a red X teaches recruiters to read absence
  as deception. That would introduce a new bias while claiming to remove an
  old one.
"""

from __future__ import annotations

import html
import json
import math

from ..models import ReadinessReport

_STATUS_META = {
    "verified": ("verified", "Verified in code"),
    "weakly_verified": ("weak", "Weak evidence"),
    "unverified": ("gap", "No public evidence"),
    "unclaimed_strength": ("bonus", "Shown in code, not on CV"),
    "not_verifiable": ("neutral", "Not code-verifiable"),
}


def _radar(category_scores: dict[str, float], size: int = 300) -> str:
    """Inline SVG radar chart of the per-area sub-scores."""
    items = [(k, v) for k, v in category_scores.items()]
    if len(items) < 3:
        return ""

    cx = cy = size / 2
    radius = size / 2 - 46
    n = len(items)
    rings = [0.25, 0.5, 0.75, 1.0]

    def point(index: int, value: float) -> tuple[float, float]:
        angle = -math.pi / 2 + (2 * math.pi * index / n)
        r = radius * value
        return cx + r * math.cos(angle), cy + r * math.sin(angle)

    parts = [f'<svg viewBox="0 0 {size} {size}" role="img" aria-label="Readiness by area">']

    for ring in rings:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(i, ring) for i in range(n)))
        parts.append(f'<polygon points="{pts}" class="grid"/>')

    for i in range(n):
        x, y = point(i, 1.0)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" class="spoke"/>')

    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(i, v / 100) for i, (_, v) in enumerate(items)))
    parts.append(f'<polygon points="{pts}" class="area"/>')
    for i, (_, value) in enumerate(items):
        x, y = point(i, value / 100)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="dot"/>')

    for i, (label, value) in enumerate(items):
        x, y = point(i, 1.16)
        anchor = "middle"
        if x < cx - 12:
            anchor = "end"
        elif x > cx + 12:
            anchor = "start"
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" class="axis">'
            f"{html.escape(label)}</text>"
        )
        parts.append(
            f'<text x="{x:.1f}" y="{y + 12:.1f}" text-anchor="{anchor}" class="axisval">'
            f"{value:.0f}</text>"
        )

    parts.append("</svg>")
    return "".join(parts)


def _signal_bars(signals: dict[str, float]) -> str:
    labels = {
        "evidence_strength": "Evidence",
        "complexity": "Complexity",
        "depth": "Depth",
        "recency": "Recency",
        "craft": "Craft",
    }
    cells = []
    for key, label in labels.items():
        value = signals.get(key, 0.0)
        cells.append(
            f'<div class="sig"><span class="siglabel">{label}</span>'
            f'<span class="sigtrack"><span class="sigfill" style="width:{value * 100:.0f}%"></span></span>'
            f'<span class="signum">{value:.2f}</span></div>'
        )
    return "".join(cells)


def _verdict_row(v: dict) -> str:
    cls, label = _STATUS_META.get(v["status"], ("neutral", v["status"]))
    repos = ", ".join(v["repos"][:5])
    more = f" +{len(v['repos']) - 5}" if len(v["repos"]) > 5 else ""
    evidence_lines = "".join(
        f'<li><code>{html.escape(h["channel"])}</code> '
        f'<span class="repo">{html.escape(h["repo"])}</span> — {html.escape(h["detail"])}</li>'
        for h in v["evidence"][:12]
    )
    metric_rows = "".join(
        f"<tr><td>{html.escape(m['path'])}</td><td>{m['loc']}</td>"
        f"<td>{m['cyclomatic_per_function']}</td><td>{m['max_nesting']}</td>"
        f"<td>{m['functions']}</td><td class=\"dim\">{html.escape(m['analyzed_with'])}</td></tr>"
        for m in v["metrics"][:8]
    )
    metrics_block = (
        '<table class="metrics"><thead><tr><th>File</th><th>LOC</th>'
        "<th>CC/fn</th><th>Nesting</th><th>Fns</th><th>Analyser</th></tr></thead>"
        f"<tbody>{metric_rows}</tbody></table>"
        if metric_rows else ""
    )

    contributed = (
        '<span class="tier" title="Only lines this candidate added to a '
        'repository someone else owns">contributed only</span>'
        if v.get("contribution_only") else ""
    )
    return f"""
    <details class="verdict {cls}">
      <summary>
        <span class="pill {cls}">{label}</span>
        <span class="skillname">{html.escape(v["skill"])}</span>
        <span class="nums">W {v["weight"]:.2f} &middot; V {v["verification"]:.2f}</span>
        <span class="tier">{html.escape(v["tier"])}</span>
        {contributed}
      </summary>
      <div class="body">
        <p class="explain">{html.escape(v["explanation"])}</p>
        <div class="signals">{_signal_bars(v["signals"])}</div>
        {f'<p class="repos"><strong>Repositories:</strong> {html.escape(repos)}{more} &middot; {v["files_analyzed"]} files &middot; {v["loc_analyzed"]:,} LOC</p>' if v["repos"] else ""}
        {f'<ul class="evidence">{evidence_lines}</ul>' if evidence_lines else ""}
        {metrics_block}
      </div>
    </details>"""


CSS = """
:root{
  --bg:#fbfaf9; --panel:#ffffff; --ink:#1a1a1a; --muted:#6b6b6b; --line:#e5e2de;
  --verified:#1c7c4a; --verified-bg:#e8f5ee;
  --weak:#a8730f; --weak-bg:#fdf3e0;
  --gap:#8c8c8c; --gap-bg:#f1f0ee;
  --bonus:#2a5f9e; --bonus-bg:#e9f0f9;
  --accent:#c15f3c;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#131313; --panel:#1c1c1c; --ink:#eceae7; --muted:#9a9691; --line:#2e2c2a;
    --verified:#5fc98d; --verified-bg:#16301f;
    --weak:#e0ab4d; --weak-bg:#2f2513;
    --gap:#8f8b86; --gap-bg:#232322;
    --bonus:#7fb0e8; --bonus-bg:#152437;
    --accent:#e08b64;
  }
}
:root[data-theme="dark"]{
  --bg:#131313; --panel:#1c1c1c; --ink:#eceae7; --muted:#9a9691; --line:#2e2c2a;
  --verified:#5fc98d; --verified-bg:#16301f;
  --weak:#e0ab4d; --weak-bg:#2f2513;
  --gap:#8f8b86; --gap-bg:#232322;
  --bonus:#7fb0e8; --bonus-bg:#152437;
  --accent:#e08b64;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);
  font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  margin:0;padding:32px 20px 64px}
.wrap{max-width:1040px;margin:0 auto}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);margin:0 0 28px;font-size:14px}
.sub a{color:var(--accent)}
.top{display:grid;grid-template-columns:minmax(280px,1fr) minmax(280px,340px);
  gap:20px;align-items:stretch;margin-bottom:26px}
@media(max-width:760px){.top{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px}
.scoreline{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.score{font-size:52px;font-weight:650;letter-spacing:-.03em;line-height:1}
.band{font-size:15px;color:var(--muted)}
.formula{margin:14px 0 0;font-size:13px;color:var(--muted);
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.confbar{margin-top:16px}
.confbar .track{height:6px;background:var(--line);border-radius:3px;overflow:hidden}
.confbar .fill{height:100%;background:var(--accent)}
.counts{display:flex;gap:18px;margin-top:18px;flex-wrap:wrap;font-size:13px}
.counts b{display:block;font-size:20px;font-weight:600}
svg{width:100%;height:auto;display:block}
.grid{fill:none;stroke:var(--line);stroke-width:1}
.spoke{stroke:var(--line);stroke-width:1}
.area{fill:color-mix(in srgb,var(--accent) 22%,transparent);stroke:var(--accent);stroke-width:2}
.dot{fill:var(--accent)}
.axis{fill:var(--muted);font-size:10px}
.axisval{fill:var(--ink);font-size:10px;font-weight:600}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
  margin:32px 0 12px;font-weight:600}
.verdict{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  margin-bottom:8px;overflow:hidden}
.verdict summary{display:flex;align-items:center;gap:12px;padding:12px 16px;cursor:pointer;
  list-style:none;flex-wrap:wrap}
.verdict summary::-webkit-details-marker{display:none}
.pill{font-size:11px;font-weight:650;letter-spacing:.03em;padding:3px 9px;border-radius:99px;
  white-space:nowrap}
.pill.verified{background:var(--verified-bg);color:var(--verified)}
.pill.weak{background:var(--weak-bg);color:var(--weak)}
.pill.gap{background:var(--gap-bg);color:var(--gap)}
.pill.bonus{background:var(--bonus-bg);color:var(--bonus)}
.pill.neutral{background:var(--gap-bg);color:var(--gap)}
.skillname{font-weight:600;flex:1;min-width:140px}
.nums,.tier{font-size:12px;color:var(--muted);
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.tier{padding:2px 7px;border:1px solid var(--line);border-radius:5px}
.body{padding:0 16px 16px;border-top:1px solid var(--line)}
.explain{margin:14px 0;font-size:14px}
.signals{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 18px;
  margin-bottom:14px}
.sig{display:flex;align-items:center;gap:8px;font-size:12px}
.siglabel{color:var(--muted);width:74px;flex:none}
.sigtrack{flex:1;height:5px;background:var(--line);border-radius:3px;overflow:hidden}
.sigfill{display:block;height:100%;background:var(--accent)}
.signum{font-family:ui-monospace,monospace;color:var(--muted);width:32px;text-align:right}
.repos{font-size:13px;color:var(--muted);margin:0 0 12px}
.evidence{margin:0 0 12px;padding-left:18px;font-size:12.5px;color:var(--muted)}
.evidence code{background:var(--gap-bg);padding:1px 5px;border-radius:4px;font-size:11px}
.evidence .repo{color:var(--ink);font-weight:500}
.metrics{width:100%;border-collapse:collapse;font-size:12px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.metrics th{text-align:left;color:var(--muted);font-weight:600;padding:5px 8px;
  border-bottom:1px solid var(--line)}
.metrics td{padding:5px 8px;border-bottom:1px solid var(--line)}
.metrics td.dim{color:var(--muted)}
.tablewrap{overflow-x:auto}
.notes{background:var(--weak-bg);border:1px solid var(--line);border-radius:10px;
  padding:14px 18px;margin-top:26px;font-size:13.5px}
.notes ul{margin:8px 0 0;padding-left:18px}
footer{margin-top:40px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);
  padding-top:16px}
"""


def _bindings_block(d: dict) -> str:
    """CV projects against the repositories they bind to."""
    bindings = d.get("project_bindings") or []
    auth = d.get("authorship") or {}
    if not bindings and not auth.get("total"):
        return ""

    rows = []
    for b in bindings:
        if b["repo"] and b["has_conflict"]:
            cls, label = "gap", "Mismatch"
        elif b["repo"] and b["inspected"]:
            cls, label = "verified", "Consistent"
        elif b["repo"]:
            cls, label = "neutral", "Not sampled"
        else:
            cls, label = "neutral", "No repository"
        how = b["method"].replace("_", " ")
        if b["method"] == "name_match":
            how += f" &middot; {b['confidence']:.0%}"
        rows.append(
            f"<tr><td><span class=\"pill {cls}\">{label}</span></td>"
            f"<td>{html.escape(b['project_title'])}</td>"
            f"<td class=\"dim\">{html.escape(b['repo'] or '—')}</td>"
            f"<td class=\"dim\">{how}</td>"
            f"<td>{html.escape(b['explanation'])}</td></tr>"
        )

    table = (
        '<div class="tablewrap"><table class="metrics"><thead><tr>'
        "<th></th><th>CV project</th><th>Repository</th><th>Matched by</th>"
        "<th>Finding</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        if rows else ""
    )

    authorship = ""
    if auth.get("total"):
        disputed_note = ""
        if auth.get("disputed"):
            disputed_note = (
                f" {auth['disputed']} commit(s) carry a half-matching identity "
                "(name or email, not both) and are credited to nobody: "
                + html.escape(", ".join(auth.get("disputed_identities", [])[:3]))
                + "."
            )
        authorship = (
            f'<p class="repos"><strong>Commit authorship.</strong> '
            f"{auth['mine']} of {auth['total']} commits in the mined repositories "
            f"({auth['ownership_ratio']:.0%}) are attributable to this candidate; "
            f"{auth['other']} belong to collaborators.{disputed_note} "
            "Reported, not scored — owning a minority of a team repository is "
            "normal, and deflating a score for collaborating would punish the "
            "behaviour the degree asks for.</p>"
        )

    return f"""
  <h2>CV projects &mdash; claimed vs. repository</h2>
  {table}
  {authorship}
  <p class="repos">Project matching is fuzzy unless the CV links a repository
     directly, so these findings are shown for a recruiter to ask about and are
     deliberately <strong>not counted in the score</strong>. A project whose
     repository was never sampled makes no claim either way.</p>"""


def render_report(report: ReadinessReport) -> str:
    d = report.to_dict()
    counts = d["counts"]
    breakdown = d["breakdown"]

    scored_rows = [v for v in d["verdicts"] if v["claimed"] and v["verifiable"] and v["weight"] > 0]
    bonus_rows = [v for v in d["verdicts"] if v["unclaimed_evidence"]]
    context_rows = [
        v for v in d["verdicts"]
        if v["claimed"] and not v["verifiable"]
    ]

    gh = d["github_username"]
    gh_link = (f'<a href="https://github.com/{html.escape(gh)}">github.com/{html.escape(gh)}</a>'
               if gh else "<em>no GitHub profile found in this CV</em>")

    warnings = "".join(f"<li>{html.escape(w)}</li>" for w in d["warnings"])

    return f"""<title>Readiness — {html.escape(d["candidate"])[:48]}</title>
<style>{CSS}</style>
<div class="wrap">
  <h1>{html.escape(d["candidate"])}</h1>
  <p class="sub">{gh_link} &middot; scored {d["generated_at"][:10]} &middot;
     DevScore engine {html.escape(d["engine_version"])}</p>

  <div class="top">
    <div class="card">
      <div class="scoreline">
        <span class="score">{d["score"]:.0f}</span>
        <span class="band">/ 100 &middot; {html.escape(d["band"])}</span>
      </div>
      <p class="formula">{breakdown["raw_ratio"]:.1f} weighted ratio
        {"&minus;" if breakdown["shrinkage"] < 0 else "&plus;"} {abs(breakdown["shrinkage"]):.1f} small-sample
        &minus; {breakdown["integrity_penalty"]:.1f} unevidenced-claim
        &plus; {breakdown["breadth_bonus"]:.1f} breadth</p>
      <div class="confbar">
        <div class="track"><div class="fill" style="width:{d["confidence"] * 100:.0f}%"></div></div>
        <p class="formula" style="margin-top:6px">evidence confidence {d["confidence"]:.0%}
          — how much public code this score rests on</p>
      </div>
      <div class="counts">
        <span><b>{counts["verified"]}</b> verified</span>
        <span><b>{counts["weakly_verified"]}</b> weak</span>
        <span><b>{counts["unverified"]}</b> no evidence</span>
        <span><b>{counts["verifiable_claims"]}</b> verifiable claims</span>
      </div>
    </div>
    <div class="card">{_radar(d["category_scores"]) or "<p class='sub'>Not enough verified areas to chart.</p>"}</div>
  </div>

  {_bindings_block(d)}

  <h2>Evidence gap &mdash; claimed skills</h2>
  {"".join(_verdict_row(v) for v in scored_rows) or "<p class='sub'>No verifiable technical claims were recognised in this CV.</p>"}

  {"<h2>Demonstrated in code, absent from the CV</h2>" if bonus_rows else ""}
  {"".join(_verdict_row(v) for v in bonus_rows)}

  {"<h2>Reported for context (not code-verifiable)</h2>" if context_rows else ""}
  {"".join(_verdict_row(v) for v in context_rows)}

  {f'<div class="notes"><strong>Notes on this score</strong><ul>{warnings}</ul></div>' if warnings else ""}

  <footer>
    A skill marked <strong>no public evidence</strong> is not a claim that the candidate
    lacks it. Only public repositories are analysed; work in private or organisation
    repositories is invisible to this system by design. Read this score as
    <em>evidenced readiness</em>, not as ability.
    <br><br>
    ScriptFusion &middot; AI-Driven Job Readiness Scoring &middot;
    Rajarata University of Sri Lanka.
  </footer>
</div>
"""


def render_json(report: ReadinessReport, include_raw: bool = False) -> str:
    return json.dumps(report.to_dict(include_raw=include_raw), indent=2)
