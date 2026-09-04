"""
Cohort dashboard — the recruiter's view of a whole scored group.

`html.py` renders one candidate. This renders the list you work from: every
scored candidate in one sortable, filterable table, with checkboxes to pick a
shortlist and a skill matrix that compares the picked candidates side by side.

It is a single self-contained file — data embedded as JSON, no CDN, no build
step — so it can be opened from disk, emailed to a supervisor, or handed in
with the dissertation and still work in five years.

Three decisions carried over from the single-candidate report, because they
matter more here, not less:

  RANK BY SCORE, SHOW CONFIDENCE NEXT TO IT. A sorted list invites the reader
  to treat position as truth. Every row carries its evidence confidence, and
  rows resting on thin evidence are visibly marked, because the difference
  between "scored 45" and "scored 45 having seen four files" is the whole
  point of the confidence signal.

  CANDIDATES WITH NO GITHUB ARE LISTED, NOT HIDDEN. They sort to their own
  section rather than to the bottom of the ranking, where a 0.0 would read as
  "worst candidate" instead of "not assessable by this method". Dropping them
  entirely would be worse still: it would hide a third of the cohort and make
  the method look like it has full coverage.

  THE SKILL MATRIX SHOWS TIERS, NOT TICKS. `declared` and `applied` are both
  "has React" to a keyword matcher; the comparison view is where that
  distinction earns its keep, so the cells carry the tier.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def load_cohort(reports_dir: str | Path) -> list[dict[str, Any]]:
    """Read every report JSON and trim it to what the dashboard needs."""
    out: list[dict[str, Any]] = []
    for path in sorted(Path(reports_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not data.get("candidate") or "verdicts" not in data:
            continue

        verdicts = [
            {
                "s": v["skill"],
                "c": v["category"],
                "t": v["tier"],
                "v": round(v["verification"], 2),
                "w": v["weight"],
                "st": v["status"],
                "cl": 1 if v["claimed"] else 0,
                "contrib": 1 if v.get("contribution_only") else 0,
                "r": v.get("code_repos") or v.get("repos") or [],
                "loc": v.get("loc_analyzed", 0),
            }
            for v in data["verdicts"]
            if v["weight"] > 0 and (v["claimed"] or v.get("unclaimed_evidence"))
        ]
        identity = data.get("identity") or {}
        auth = data.get("authorship") or {}
        bindings = [
            {
                "t": b["project_title"],
                "r": b["repo"] or "",
                "m": b["method"],
                "c": b["confidence"],
                "insp": b["inspected"],
                "miss": b["missing_skills"],
                "conf": b["has_conflict"],
                "tent": b["tentative"],
            }
            for b in (data.get("project_bindings") or [])
        ]
        out.append({
            "name": data["candidate"],
            "gh": data.get("github_username") or "",
            "ghsrc": identity.get("handle_source", "cv"),
            "ghnote": identity.get("handle_note", ""),
            "fname": identity.get("filename_label", ""),
            "namesrc": identity.get("name_source", "cv"),
            "score": round(data["score"], 1),
            "band": data["band"],
            "conf": round(data["confidence"], 2),
            "counts": data["counts"],
            "cats": {k: round(v) for k, v in (data.get("category_scores") or {}).items()},
            "warn": data.get("warnings", [])[:4],
            "verdicts": verdicts,
            "bind": bindings,
            "own": auth.get("ownership_ratio", 0.0),
            "cmine": auth.get("mine", 0),
            "cdisp": auth.get("disputed", 0),
            "cother": auth.get("other", 0),
            "forks": (data.get("forks") or {}).get("seen", 0),
            "forksc": (data.get("forks") or {}).get("contributed_to", 0),
            "forklines": (data.get("forks") or {}).get("contributed_lines", 0),
        })
    return out


CSS = """
:root{
  --bg:#fbfaf9; --panel:#fff; --ink:#1a1a1a; --muted:#6b6b6b; --line:#e5e2de;
  --verified:#1c7c4a; --verified-bg:#e8f5ee; --weak:#a8730f; --weak-bg:#fdf3e0;
  --gap:#8c8c8c; --gap-bg:#f1f0ee; --bonus:#2a5f9e; --bonus-bg:#e9f0f9;
  --accent:#c15f3c; --sel:#fdf1ec;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#131313; --panel:#1c1c1c; --ink:#eceae7; --muted:#9a9691; --line:#2e2c2a;
  --verified:#5fc98d; --verified-bg:#16301f; --weak:#e0ab4d; --weak-bg:#2f2513;
  --gap:#8f8b86; --gap-bg:#232322; --bonus:#7fb0e8; --bonus-bg:#152437;
  --accent:#e08b64; --sel:#2a1c16;
}}
:root[data-theme="dark"]{
  --bg:#131313; --panel:#1c1c1c; --ink:#eceae7; --muted:#9a9691; --line:#2e2c2a;
  --verified:#5fc98d; --verified-bg:#16301f; --weak:#e0ab4d; --weak-bg:#2f2513;
  --gap:#8f8b86; --gap-bg:#232322; --bonus:#7fb0e8; --bonus-bg:#152437;
  --accent:#e08b64; --sel:#2a1c16;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);margin:0;padding:28px 20px 80px;
  font:15px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:24px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:14px;margin:0 0 22px}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:22px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:12px 16px;min-width:112px}
.stat b{display:block;font-size:22px;font-weight:650;letter-spacing:-.02em}
.stat span{color:var(--muted);font-size:12px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
input[type=search],select{background:var(--panel);color:var(--ink);
  border:1px solid var(--line);border-radius:8px;padding:8px 11px;font:inherit;font-size:14px}
input[type=search]{flex:1;min-width:200px}
button{background:var(--panel);color:var(--ink);border:1px solid var(--line);
  border-radius:8px;padding:8px 13px;font:inherit;font-size:13px;cursor:pointer}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:14px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--muted);font-weight:600;padding:11px 12px;border-bottom:1px solid var(--line);
  cursor:pointer;white-space:nowrap;user-select:none}
th.nosort{cursor:default}
th[data-dir]:after{content:" ▾";opacity:.7}
th[data-dir="asc"]:after{content:" ▴"}
td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:middle}
tr.row{cursor:pointer}
tr.row:hover td{background:var(--gap-bg)}
tr.row.picked td{background:var(--sel)}
tr.detail td{padding:0;background:var(--bg)}
tr.detail .inner{padding:14px 18px 20px;border-bottom:2px solid var(--accent)}
.who{font-weight:600}
.gh{color:var(--muted);font-size:12px;font-family:ui-monospace,Menlo,monospace}
.score{font-weight:650;font-size:16px;font-variant-numeric:tabular-nums}
.meter{width:76px;height:5px;background:var(--line);border-radius:3px;overflow:hidden;display:inline-block;
  vertical-align:middle;margin-left:8px}
.meter i{display:block;height:100%;background:var(--accent)}
.pill{font-size:10.5px;font-weight:650;padding:2px 8px;border-radius:99px;white-space:nowrap}
.v{background:var(--verified-bg);color:var(--verified)}
.w{background:var(--weak-bg);color:var(--weak)}
.g{background:var(--gap-bg);color:var(--gap)}
.b{background:var(--bonus-bg);color:var(--bonus)}
.counts{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.counts b{color:var(--ink);font-weight:600}
.thin{color:var(--weak);font-size:11px}
.chips{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}
.chip{font-size:11.5px;padding:3px 9px;border-radius:6px;border:1px solid var(--line)}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
  margin:26px 0 10px;font-weight:600}
h3{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  margin:18px 0 6px;font-weight:600}
.note{background:var(--weak-bg);border:1px solid var(--line);border-radius:10px;
  padding:11px 15px;font-size:13px;margin:14px 0}
.cmp{margin-top:12px;border:1px solid var(--line);border-radius:12px;background:var(--panel);
  overflow:hidden}
.cmp .hd{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;
  justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.cmp table{font-size:13px}
.cmp td.sk{font-weight:500;white-space:nowrap}
.cmp td.cell{text-align:center}
.empty{padding:26px 18px;color:var(--muted);font-size:14px;text-align:center}
footer{margin-top:38px;padding-top:16px;border-top:1px solid var(--line);
  color:var(--muted);font-size:12px}
"""

JS = r"""
const $ = (s, r=document) => r.querySelector(s);
const el = (t, c, txt) => { const n = document.createElement(t);
  if (c) n.className = c; if (txt !== undefined) n.textContent = txt; return n; };

const TIER_CLASS = { mastered:'v', applied:'v', used:'v', declared:'w', ambient:'w', none:'g' };
const TIER_SHORT = { mastered:'mastered', applied:'applied', used:'used',
                     declared:'declared', ambient:'ambient', none:'—' };

let sortKey = 'score', sortDir = 'desc', query = '', onlyScorable = false;
const picked = new Set();

function visible() {
  let rows = DATA.filter(c => {
    if (onlyScorable && !c.gh) return false;
    if (!query) return true;
    const q = query.toLowerCase();
    return c.name.toLowerCase().includes(q)
        || c.gh.toLowerCase().includes(q)
        || c.verdicts.some(v => v.s.toLowerCase().includes(q) && v.t !== 'none');
  });
  const dir = sortDir === 'asc' ? 1 : -1;
  rows.sort((a, b) => {
    let x, y;
    if (sortKey === 'name') { x = a.name.toLowerCase(); y = b.name.toLowerCase(); }
    else if (sortKey === 'verified') { x = a.counts.verified; y = b.counts.verified; }
    else if (sortKey === 'claims') { x = a.counts.verifiable_claims; y = b.counts.verifiable_claims; }
    else if (sortKey === 'conf') { x = a.conf; y = b.conf; }
    else { x = a.score; y = b.score; }
    if (x < y) return -1 * dir;
    if (x > y) return 1 * dir;
    return a.name.localeCompare(b.name);
  });
  return rows;
}

function detailFor(c) {
  const box = el('div', 'inner');
  if (Object.keys(c.cats).length) {
    const chips = el('div', 'chips');
    Object.entries(c.cats).sort((a,b) => b[1]-a[1]).forEach(([k, v]) => {
      const chip = el('span', 'chip', `${k} ${v}`); chips.appendChild(chip);
    });
    box.appendChild(chips);
  }
  const t = el('table');
  t.innerHTML = '<thead><tr><th class="nosort">Skill</th><th class="nosort">Status</th>' +
    '<th class="nosort">Tier</th><th class="nosort">W</th><th class="nosort">V</th>' +
    '<th class="nosort">Evidence</th></tr></thead>';
  const tb = el('tbody');
  c.verdicts.forEach(v => {
    const tr = el('tr');
    const label = v.cl ? v.st.replace(/_/g, ' ') : 'in code, not on CV';
    const cls = v.st === 'verified' ? 'v' : v.st === 'weakly_verified' ? 'w'
              : v.cl ? 'g' : 'b';
    tr.innerHTML = `<td>${esc(v.s)}</td>` +
      `<td><span class="pill ${cls}">${esc(label)}</span></td>` +
      `<td class="gh">${esc(TIER_SHORT[v.t] || v.t)}</td>` +
      `<td class="gh">${v.w.toFixed(2)}</td><td class="gh">${v.v.toFixed(2)}</td>` +
      `<td class="gh">${v.r.length ? esc(v.r.slice(0,3).join(', ')) : '—'}` +
      `${v.loc ? ' · ' + v.loc.toLocaleString() + ' LOC' : ''}</td>`;
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  box.appendChild(t);

  if ((c.bind || []).length) {
    box.appendChild(el('h3', null, 'CV projects vs. repositories'));
    const bt = el('table');
    bt.innerHTML = '<thead><tr><th class="nosort"></th><th class="nosort">Project</th>' +
      '<th class="nosort">Repository</th><th class="nosort">Matched by</th>' +
      '<th class="nosort">Finding</th></tr></thead>';
    const btb = el('tbody');
    c.bind.forEach(b => {
      let cls = 'g', label = 'No repository';
      if (b.r && b.conf) { cls = 'gap'; label = 'Mismatch'; }
      else if (b.r && b.insp) { cls = 'v'; label = 'Consistent'; }
      else if (b.r) { cls = 'g'; label = 'Not sampled'; }
      const how = b.m.replace(/_/g, ' ') +
        (b.m === 'name_match' ? ' \u00b7 ' + Math.round(b.c * 100) + '%' : '');
      const finding = b.conf
        ? 'claims ' + esc(b.miss.join(', ')) + ' \u2014 no sign of it there'
        : (b.r && b.insp ? 'attributed stack is present'
                         : (b.r ? 'repository not sampled \u2014 no conclusion'
                                : 'no matching repository'));
      const tr = el('tr');
      tr.innerHTML = '<td><span class="pill ' + cls + '">' + label + '</span></td>' +
        '<td>' + esc(b.t) + '</td><td class="gh">' + esc(b.r || '\u2014') + '</td>' +
        '<td class="gh">' + esc(how) + '</td><td class="gh">' + finding + '</td>';
      btb.appendChild(tr);
    });
    bt.appendChild(btb);
    box.appendChild(bt);
    box.appendChild(el('div', 'note',
      'Project matching is fuzzy unless the CV links a repository directly, so these ' +
      'are shown for a recruiter to ask about and are never counted in the score. A ' +
      'repository that was never sampled makes no claim either way.'));
  }

  if ((c.cmine + c.cother + c.cdisp) > 0) {
    box.appendChild(el('div', 'note',
      'Commit authorship: ' + c.cmine + ' of ' + (c.cmine + c.cdisp + c.cother) +
      ' commits (' + Math.round(c.own * 100) + '%) are attributable to this candidate; ' +
      c.cother + ' belong to collaborators' +
      (c.cdisp ? ', and ' + c.cdisp + ' carry a half-matching identity and are credited to nobody' : '') +
      '. Reported, not scored \u2014 owning a minority of a team repository is normal.'));
  }

  (c.warn || []).forEach(w => box.appendChild(el('div', 'note', w)));
  return box;
}

function esc(s) { return String(s).replace(/[&<>"]/g, m =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m])); }

function render() {
  const tbody = $('#rows'); tbody.textContent = '';
  const rows = visible();
  if (!rows.length) {
    const tr = el('tr'); const td = el('td', 'empty', 'No candidate matches that filter.');
    td.colSpan = 7; tr.appendChild(td); tbody.appendChild(tr);
  }
  rows.forEach(c => {
    const tr = el('tr', 'row' + (picked.has(c.name) ? ' picked' : ''));
    const cb = el('input'); cb.type = 'checkbox'; cb.checked = picked.has(c.name);
    cb.addEventListener('click', e => {
      e.stopPropagation();
      picked.has(c.name) ? picked.delete(c.name) : picked.add(c.name);
      render(); compare();
    });
    const tdc = el('td'); tdc.appendChild(cb); tr.appendChild(tdc);

    const who = el('td');
    who.appendChild(el('div', 'who', c.name));
    const ghline = el('div', 'gh');
    if (c.gh) {
      ghline.textContent = '@' + c.gh;
      if (c.ghsrc === 'override') {
        const b = el('span', 'pill b', 'handle supplied');
        b.title = c.ghnote || 'GitHub handle supplied via handle_overrides.json — the CV named no account';
        b.style.marginLeft = '6px'; ghline.appendChild(b);
      }
    } else {
      ghline.textContent = 'no GitHub handle in CV';
    }
    who.appendChild(ghline);
    if (c.namesrc !== 'cv' && c.fname) {
      const nb = el('div', 'thin', 'name from filename (CV unreadable)');
      who.appendChild(nb);
    }
    const conflicts = (c.bind || []).filter(b => b.conf);
    if (conflicts.length) {
      const cb = el('div');
      const pill = el('span', 'pill gap',
        conflicts.length + ' project mismatch' + (conflicts.length > 1 ? 'es' : ''));
      pill.title = conflicts.map(b => b.t + ': ' + b.miss.join(', ')).join(' | ');
      cb.appendChild(pill);
      who.appendChild(cb);
    }
    tr.appendChild(who);

    const sc = el('td');
    if (c.gh) {
      sc.innerHTML = `<span class="score">${c.score.toFixed(1)}</span>` +
        `<span class="meter"><i style="width:${c.score}%"></i></span>`;
    } else { sc.innerHTML = '<span class="gh">not assessable</span>'; }
    tr.appendChild(sc);

    tr.appendChild(el('td')).innerHTML =
      `<span class="pill ${c.score>=65?'v':c.score>=45?'w':'g'}">${esc(c.band)}</span>`;

    const ct = el('td', 'counts');
    ct.innerHTML = `<b>${c.counts.verified}</b> ✓ &nbsp;${c.counts.weakly_verified} ~ &nbsp;` +
      `${c.counts.unverified} ✗ <span class="gh">of ${c.counts.verifiable_claims}</span>`;
    tr.appendChild(ct);

    const cf = el('td', 'counts');
    cf.innerHTML = `${Math.round(c.conf*100)}%` +
      (c.conf < 0.35 && c.gh ? '<div class="thin">thin evidence base</div>' : '');
    tr.appendChild(cf);

    tr.appendChild(el('td', 'gh', '▸'));
    tr.addEventListener('click', () => {
      const next = tr.nextElementSibling;
      if (next && next.classList.contains('detail')) { next.remove(); return; }
      document.querySelectorAll('tr.detail').forEach(n => n.remove());
      const d = el('tr', 'detail'); const td = el('td'); td.colSpan = 7;
      td.appendChild(detailFor(c)); d.appendChild(td); tr.after(d);
    });
    tbody.appendChild(tr);
  });
  $('#count').textContent = `${rows.length} shown · ${picked.size} selected`;
}

function compare() {
  const box = $('#compare');
  const chosen = DATA.filter(c => picked.has(c.name));
  box.textContent = '';
  if (chosen.length < 1) { box.hidden = true; return; }
  box.hidden = false;

  const hd = el('div', 'hd');
  hd.appendChild(el('strong', null,
    chosen.length === 1 ? `${chosen[0].name}` : `Comparing ${chosen.length} candidates`));
  const clear = el('button', null, 'Clear selection');
  clear.addEventListener('click', () => { picked.clear(); render(); compare(); });
  hd.appendChild(clear);
  box.appendChild(hd);

  // Union of every skill any selected candidate has evidence for or claims,
  // ordered by difficulty weight so the decisive rows sit at the top.
  const skills = new Map();
  chosen.forEach(c => c.verdicts.forEach(v => {
    if (!skills.has(v.s) || skills.get(v.s) < v.w) skills.set(v.s, v.w);
  }));
  const ordered = [...skills.entries()].sort((a, b) => b[1] - a[1]);

  const t = el('table');
  t.innerHTML = '<thead><tr><th class="nosort">Skill</th><th class="nosort">W</th>' +
    chosen.map(c => `<th class="nosort">${esc(c.name.split(' ')[0])}</th>`).join('') +
    '</tr></thead>';
  const tb = el('tbody');
  ordered.forEach(([skill, w]) => {
    const tr = el('tr');
    tr.innerHTML = `<td class="sk">${esc(skill)}</td><td class="gh">${w.toFixed(2)}</td>` +
      chosen.map(c => {
        const v = c.verdicts.find(x => x.s === skill);
        if (!v) return '<td class="cell gh">·</td>';
        const cls = v.cl ? (TIER_CLASS[v.t] || 'g') : 'b';
        const txt = v.cl ? TIER_SHORT[v.t] : TIER_SHORT[v.t] + '*';
        return `<td class="cell"><span class="pill ${cls}" title="V=${v.v}">${esc(txt)}</span></td>`;
      }).join('');
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  box.appendChild(t);
  const foot = el('div', 'note',
    '* demonstrated in code but not claimed on that CV — shown for context, never counted in the score.');
  box.appendChild(foot);
}

document.addEventListener('DOMContentLoaded', () => {
  $('#q').addEventListener('input', e => { query = e.target.value; render(); });
  $('#scorable').addEventListener('change', e => { onlyScorable = e.target.checked; render(); });
  $('#selectAll').addEventListener('click', () => {
    visible().forEach(c => picked.add(c.name)); render(); compare();
  });
  document.querySelectorAll('th[data-key]').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      sortDir = (sortKey === key && sortDir === 'desc') ? 'asc' : 'desc';
      sortKey = key;
      document.querySelectorAll('th[data-key]').forEach(o => o.removeAttribute('data-dir'));
      th.setAttribute('data-dir', sortDir);
      render();
    });
  });
  render(); compare();
});
"""


def render_cohort(cohort: list[dict[str, Any]], title: str = "Candidate cohort") -> str:
    scorable = [c for c in cohort if c["gh"]]
    scores = [c["score"] for c in scorable]
    claims = sum(c["counts"]["verifiable_claims"] for c in scorable)
    verified = sum(c["counts"]["verified"] for c in scorable)
    mean = sum(scores) / len(scores) if scores else 0.0
    conflicts = sum(1 for c in cohort for b in c.get("bind", []) if b["conf"])

    payload = json.dumps(cohort, separators=(",", ":")).replace("</", "<\\/")

    return f"""<title>{html.escape(title)}</title>
<style>{CSS}</style>
<div class="wrap">
  <h1>{html.escape(title)}</h1>
  <p class="sub">Select candidates to compare their evidence side by side.
     Click any row to open its full claim-vs-evidence breakdown.</p>

  <div class="stats">
    <div class="stat"><b>{len(cohort)}</b><span>CVs processed</span></div>
    <div class="stat"><b>{len(scorable)}</b><span>with a GitHub handle</span></div>
    <div class="stat"><b>{mean:.1f}</b><span>mean score</span></div>
    <div class="stat"><b>{verified}</b><span>claims verified in code</span></div>
    <div class="stat"><b>{claims - verified}</b><span>claims without proof</span></div>
    <div class="stat"><b>{conflicts}</b><span>project mismatches</span></div>
  </div>

  <div class="bar">
    <input type="search" id="q" placeholder="Filter by name, GitHub handle, or a skill they can prove…">
    <label style="font-size:13px;color:var(--muted)">
      <input type="checkbox" id="scorable"> only scorable
    </label>
    <button id="selectAll">Select all shown</button>
    <span class="gh" id="count"></span>
  </div>

  <div class="tablewrap">
    <table>
      <thead><tr>
        <th class="nosort"></th>
        <th data-key="name">Candidate</th>
        <th data-key="score" data-dir="desc">Score</th>
        <th class="nosort">Band</th>
        <th data-key="verified">Verified / weak / none</th>
        <th data-key="conf">Confidence</th>
        <th class="nosort"></th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>

  <h2>Selection</h2>
  <div class="cmp" id="compare" hidden></div>

  <footer>
    A candidate marked <strong>not assessable</strong> gave no GitHub handle on their CV.
    That is a limit of this method, not a judgement about them — and a skill with
    <strong>no public evidence</strong> is unevidenced, not disproved: private and
    organisation repositories are out of scope by design.
    <br><br>
    ScriptFusion &middot; AI-Driven Job Readiness Scoring &middot; Rajarata University of Sri Lanka.
  </footer>
</div>
<script>const DATA={payload};</script>
<script>{JS}</script>
"""
