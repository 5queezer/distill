"""Generate a standalone HTML timeline from exported memories."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from distill_mcp.domain.models import Memory


def generate_timeline_html(memories: list[Memory]) -> str:
    """Return a self-contained HTML page with an interactive repo-lane timeline."""
    data = [
        {
            "id": m.id,
            "content": m.content,
            "type": m.type,
            "repos": m.repos,
            "tags": m.tags,
            "created_at": m.created_at.isoformat(),
            "supersedes": m.supersedes,
        }
        for m in memories
    ]
    json_blob = json.dumps(data, indent=None)
    return _TEMPLATE.replace("__DATA__", json_blob)


_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Knowledge Timeline</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,sans-serif;
  background:#0f1117;color:#c9d1d9;overflow-x:hidden}
a{color:#58a6ff;text-decoration:none}

/* Stats bar */
.stats{display:flex;gap:2rem;padding:1rem 1.5rem;background:#161b22;
  border-bottom:1px solid #30363d;flex-wrap:wrap;align-items:center}
.stats h1{font-size:1.1rem;font-weight:600;margin-right:auto}
.stat{font-size:.85rem;color:#8b949e}
.stat b{color:#c9d1d9}

/* Filters */
.filters{display:flex;gap:.5rem;padding:.75rem 1.5rem;background:#161b22;
  border-bottom:1px solid #30363d;flex-wrap:wrap}
.chip{padding:.25rem .6rem;border-radius:12px;font-size:.75rem;cursor:pointer;
  border:1px solid #30363d;background:#21262d;color:#c9d1d9;user-select:none;
  transition:opacity .15s}
.chip.off{opacity:.35}
.chip[data-type="decision"]{border-color:#2dd4bf;color:#2dd4bf}
.chip[data-type="pattern"]{border-color:#60a5fa;color:#60a5fa}
.chip[data-type="failure"]{border-color:#f87171;color:#f87171}
.chip[data-type="dependency"]{border-color:#f472b6;color:#f472b6}
.chip[data-type="context"]{border-color:#fbbf24;color:#fbbf24}
.chip-label{font-size:.7rem;color:#8b949e;margin-right:.25rem;align-self:center}

/* Timeline container */
.timeline-wrap{position:relative;overflow-x:auto;overflow-y:auto;
  padding:1.5rem 1.5rem 2rem}
.timeline{position:relative;min-height:200px}

/* Repo lanes */
.lane{position:relative;min-height:44px;display:flex;align-items:flex-start;
  border-bottom:1px solid #21262d;transition:min-height .2s ease}
.lane-label{position:sticky;left:0;z-index:2;min-width:160px;padding-right:1rem;
  font-size:.8rem;color:#8b949e;background:#0f1117;font-family:monospace;
  padding-top:.65rem}
.lane-track{display:flex;gap:6px;flex-wrap:nowrap;overflow-x:auto;flex:1;
  padding:6px 8px;align-items:flex-start}

/* Segments */
.segment{flex-shrink:0;border-radius:10px;padding:.4rem .65rem;
  transition:background .15s,min-width .2s;cursor:default;
  display:flex;flex-direction:column;gap:4px}
.segment[data-type="decision"]{background:#2dd4bf22;border:1px solid #2dd4bf}
.segment[data-type="pattern"]{background:#60a5fa22;border:1px solid #60a5fa}
.segment[data-type="failure"]{background:#f8717122;border:1px solid #f87171}
.segment[data-type="dependency"]{background:#f472b622;border:1px solid #f472b6}
.segment[data-type="context"]{background:#fbbf2422;border:1px solid #fbbf24}
.seg-header{display:flex;align-items:center;gap:6px;cursor:pointer;
  font-size:.75rem;font-weight:600;text-transform:uppercase;user-select:none;
  white-space:nowrap}
.segment[data-type="decision"] .seg-header{color:#2dd4bf}
.segment[data-type="pattern"] .seg-header{color:#60a5fa}
.segment[data-type="failure"] .seg-header{color:#f87171}
.segment[data-type="dependency"] .seg-header{color:#f472b6}
.segment[data-type="context"] .seg-header{color:#fbbf24}
.seg-count{font-size:.7rem;opacity:.6}
.seg-items{display:none;flex-direction:column;gap:2px;margin-top:2px}
.segment.expanded .seg-items{display:flex}
.seg-item{font-size:.78rem;color:#c9d1d9;padding:.2rem .4rem;border-radius:4px;
  cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  max-width:320px;transition:background .1s}
.seg-item:hover{background:rgba(255,255,255,.07)}
.seg-item .seg-item-date{color:#8b949e;margin-right:.4rem;font-size:.7rem}

/* Tooltip */
.tooltip{position:fixed;padding:.4rem .65rem;background:#30363d;color:#c9d1d9;
  border-radius:6px;font-size:.75rem;pointer-events:none;z-index:10;
  max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  display:none;border:1px solid #484f58}

/* Detail panel */
.panel-overlay{position:fixed;top:0;left:0;width:100%;height:100%;
  background:rgba(0,0,0,.5);z-index:20;display:none}
.panel{position:fixed;top:0;right:0;width:420px;max-width:90vw;height:100%;
  background:#161b22;border-left:1px solid #30363d;z-index:21;display:none;
  overflow-y:auto;padding:1.5rem}
.panel .close{position:absolute;top:1rem;right:1rem;cursor:pointer;
  font-size:1.2rem;color:#8b949e}
.panel .badge{display:inline-block;padding:.15rem .5rem;border-radius:10px;
  font-size:.7rem;font-weight:600;text-transform:uppercase;margin-bottom:.75rem}
.panel .badge[data-type="decision"]{background:#2dd4bf22;color:#2dd4bf;
  border:1px solid #2dd4bf}
.panel .badge[data-type="pattern"]{background:#60a5fa22;color:#60a5fa;
  border:1px solid #60a5fa}
.panel .badge[data-type="failure"]{background:#f8717122;color:#f87171;
  border:1px solid #f87171}
.panel .badge[data-type="dependency"]{background:#f472b622;color:#f472b6;
  border:1px solid #f472b6}
.panel .badge[data-type="context"]{background:#fbbf2422;color:#fbbf24;
  border:1px solid #fbbf24}
.panel h2{font-size:1rem;margin-bottom:1rem;font-weight:600}
.panel .meta{font-size:.8rem;color:#8b949e;margin-bottom:.5rem}
.panel .content{font-size:.9rem;line-height:1.6;margin:1rem 0;
  padding:1rem;background:#0d1117;border-radius:8px;border:1px solid #21262d}
.panel .tag{display:inline-block;padding:.1rem .45rem;margin:.15rem;
  border-radius:8px;font-size:.7rem;background:#21262d;color:#8b949e}
.panel .supersedes-ref{font-size:.8rem;color:#8b949e;margin-top:.5rem;
  border-top:1px solid #21262d;padding-top:.75rem}

/* Empty state */
.empty{text-align:center;padding:4rem 2rem;color:#484f58}
.empty h2{font-size:1.3rem;margin-bottom:.5rem;color:#8b949e}
</style>
</head>
<body>

<div class="stats" id="stats"></div>
<div class="filters" id="filters"></div>
<div class="timeline-wrap">
  <div class="timeline" id="timeline"></div>
</div>
<div class="tooltip" id="tooltip"></div>
<div class="panel-overlay" id="panel-overlay"></div>
<div class="panel" id="panel"></div>

<script>
(function(){
"use strict";
const DATA = __DATA__;

if(!DATA.length){
  document.getElementById("timeline").innerHTML =
    '<div class="empty"><h2>No memories yet</h2><p>Use <code>remember</code> to start building your knowledge base.</p></div>';
  document.getElementById("stats").innerHTML =
    '<h1>Knowledge Timeline</h1><span class="stat">0 memories</span>';
  return;
}

/* --- Build indexes --- */
const byId = Object.create(null);
DATA.forEach(m => { byId[m.id] = m; });

const allRepos = [...new Set(DATA.flatMap(m => m.repos))].sort();
const allTypes = [...new Set(DATA.map(m => m.type))].sort();
const dates = DATA.map(m => new Date(m.created_at).getTime());
const minTs = Math.min(...dates);
const maxTs = Math.max(...dates);

/* filter state */
const activeTypes = new Set(allTypes);
const activeRepos = new Set(allRepos);

/* --- Stats --- */
const earliest = new Date(minTs).toISOString().slice(0,10);
const latest = new Date(maxTs).toISOString().slice(0,10);
document.getElementById("stats").innerHTML =
  `<h1>Knowledge Timeline</h1>
   <span class="stat"><b>${DATA.length}</b> memories</span>
   <span class="stat"><b>${allRepos.length}</b> repos</span>
   <span class="stat">${earliest} &mdash; ${latest}</span>`;

/* --- Filters --- */
function renderFilters(){
  const f = document.getElementById("filters");
  let h = '<span class="chip-label">Type:</span>';
  allTypes.forEach(t => {
    const on = activeTypes.has(t);
    h += `<span class="chip ${on?"":"off"}" data-type="${t}" data-filter="type">${t}</span>`;
  });
  h += '<span class="chip-label" style="margin-left:.75rem">Repo:</span>';
  allRepos.forEach(r => {
    const on = activeRepos.has(r);
    h += `<span class="chip ${on?"":"off"}" data-filter="repo" data-repo="${r}">${r}</span>`;
  });
  f.innerHTML = h;
  f.querySelectorAll(".chip").forEach(el => el.addEventListener("click", onChipClick));
}

function onChipClick(e){
  const el = e.currentTarget;
  if(el.dataset.filter === "type"){
    const t = el.dataset.type;
    activeTypes.has(t) ? activeTypes.delete(t) : activeTypes.add(t);
  } else {
    const r = el.dataset.repo;
    activeRepos.has(r) ? activeRepos.delete(r) : activeRepos.add(r);
  }
  renderFilters();
  renderTimeline();
}

/* --- Segments --- */
const MIN_PILL = 60;      /* px width for a x1 segment */
const PILL_PER_ITEM = 12; /* additional px per item */
let expandedSegId = null;  /* tracks which segment is expanded */
let segIdCounter = 0;

function buildSegments(memories){
  const sorted = memories.slice().sort((a,b) =>
    new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  const segs = [];
  sorted.forEach(m => {
    if(segs.length && segs[segs.length-1].type === m.type){
      segs[segs.length-1].items.push(m);
    } else {
      segs.push({type: m.type, items: [m], id: "seg-" + (segIdCounter++)});
    }
  });
  return segs;
}

/* --- Render --- */
function renderTimeline(){
  const timeline = document.getElementById("timeline");
  const visibleRepos = allRepos.filter(r => activeRepos.has(r));
  const visibleData = DATA.filter(m =>
    activeTypes.has(m.type) && m.repos.some(r => activeRepos.has(r))
  );

  if(!visibleRepos.length || !visibleData.length){
    timeline.innerHTML = '<div class="empty"><h2>No matches</h2><p>Adjust filters to see memories.</p></div>';
    return;
  }

  segIdCounter = 0;
  let lanesHtml = "";
  visibleRepos.forEach(repo => {
    const laneMems = visibleData.filter(m => m.repos.includes(repo));
    const segs = buildSegments(laneMems);
    let trackHtml = "";
    segs.forEach(seg => {
      const count = seg.items.length;
      const w = MIN_PILL + (count - 1) * PILL_PER_ITEM;
      const expanded = expandedSegId === seg.id;
      const cls = "segment" + (expanded ? " expanded" : "");
      const countBadge = count > 1 ? `<span class="seg-count">x${count}</span>` : "";

      /* date range for tooltip */
      const first = seg.items[0].created_at.slice(0,10);
      const last = seg.items[seg.items.length-1].created_at.slice(0,10);
      const dateRange = first === last ? first : first + " — " + last;

      let itemsHtml = "";
      seg.items.forEach(m => {
        const d = m.created_at.slice(0,10);
        const preview = m.content.length > 50 ? m.content.slice(0,47) + "..." : m.content;
        itemsHtml += `<div class="seg-item" data-id="${m.id}"><span class="seg-item-date">${esc(d)}</span>${esc(preview)}</div>`;
      });

      trackHtml += `<div class="${cls}" data-type="${seg.type}" data-seg="${seg.id}" style="min-width:${w}px" title="${esc(dateRange)}">` +
        `<div class="seg-header" data-seg="${seg.id}">${seg.type}${countBadge}</div>` +
        `<div class="seg-items">${itemsHtml}</div></div>`;
    });

    lanesHtml += `<div class="lane"><span class="lane-label">${esc(repo)}</span><div class="lane-track">${trackHtml}</div></div>`;
  });

  timeline.innerHTML = lanesHtml;

  /* bind events */
  timeline.querySelectorAll(".seg-header").forEach(el => {
    el.addEventListener("click", function(){
      const sid = this.dataset.seg;
      expandedSegId = expandedSegId === sid ? null : sid;
      renderTimeline();
    });
  });
  timeline.querySelectorAll(".seg-item").forEach(el => {
    el.addEventListener("click", function(){
      const m = byId[this.dataset.id];
      if(m) openPanel(m);
    });
  });
}

/* --- Tooltip --- */
const tip = document.getElementById("tooltip");
function showTooltip(e, text){
  tip.textContent = text;
  tip.style.display = "block";
  tip.style.left = (e.clientX + 12) + "px";
  tip.style.top = (e.clientY - 30) + "px";
}
function hideTooltip(){ tip.style.display = "none"; }

/* --- Detail panel --- */
const panel = document.getElementById("panel");
const overlay = document.getElementById("panel-overlay");

function openPanel(m){
  const dateStr = new Date(m.created_at).toISOString().slice(0,10);
  const tagsHtml = m.tags.length
    ? m.tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")
    : '<span style="color:#484f58">none</span>';
  const supersedes = m.supersedes && byId[m.supersedes]
    ? `<div class="supersedes-ref">Supersedes: <code>${m.supersedes.slice(0,12)}...</code>
       <br><small>${esc(byId[m.supersedes].content.slice(0,100))}</small></div>`
    : m.supersedes
    ? `<div class="supersedes-ref">Supersedes: <code>${m.supersedes.slice(0,12)}...</code> (deleted)</div>`
    : "";
  const supersededBy = DATA.filter(x => x.supersedes === m.id);
  const supersededByHtml = supersededBy.length
    ? `<div class="supersedes-ref">Superseded by: ${supersededBy.map(x =>
        `<code>${x.id.slice(0,12)}...</code>`).join(", ")}</div>`
    : "";

  panel.innerHTML = `
    <span class="close" id="panel-close">&times;</span>
    <span class="badge" data-type="${m.type}">${m.type}</span>
    <div class="meta">${dateStr}</div>
    <div class="meta">Repos: ${m.repos.map(r => `<b>${esc(r)}</b>`).join(", ")}</div>
    <div class="content">${esc(m.content)}</div>
    <div class="meta">Tags: ${tagsHtml}</div>
    <div class="meta" style="margin-top:.5rem"><code style="font-size:.7rem;color:#484f58">${m.id}</code></div>
    ${supersedes}${supersededByHtml}`;
  panel.style.display = "block";
  overlay.style.display = "block";
  document.getElementById("panel-close").addEventListener("click", closePanel);
  overlay.addEventListener("click", closePanel);
}

function closePanel(){
  panel.style.display = "none";
  overlay.style.display = "none";
}

function esc(s){
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/* --- Init --- */
renderFilters();
renderTimeline();

/* close panel on Escape */
document.addEventListener("keydown", e => { if(e.key === "Escape") closePanel(); });
})();
</script>
</body>
</html>
"""
