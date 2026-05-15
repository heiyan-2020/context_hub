"""Render the graph JSON into a self-contained HTML viewer.

This is the *visualization* step.  It only consumes `_index/graph.json`
(or any payload matching its schema) and emits HTML — no recompute.
Iterating on the look-and-feel doesn't require touching the pipeline.

Public surface:
    render_html(payload: dict) -> str
    render_to_file(input_json: Path, output_html: Path) -> dict

The HTML is fully self-contained (no CDN, no network) — canvas-based
force-graph viewer with pan/zoom, hierarchical sidebar (L1 → L0 → notes),
edge hover tooltips with via-handles, two coloring modes (community / top-
level super-community), and URL-hash deep links for sharing notes.
"""
from __future__ import annotations

import json
from pathlib import Path


def render_html(payload: dict) -> str:
    """Return a self-contained HTML string for the given thought-network payload."""
    data = json.dumps(payload, ensure_ascii=False)
    return _TEMPLATE.replace("__DATA__", data)


def render_to_file(input_json: Path, output_html: Path) -> dict:
    """Read `input_json`, write `output_html`, return a small stats dict.

    Sidecar lookup: if `community_summaries.yaml` and/or
    `community_hierarchy.yaml` live next to the JSON, their titles get
    embedded into the payload so the legend can show "自律与习惯管理"
    instead of bare "C0".
    """
    payload = json.loads(input_json.read_text(encoding="utf-8"))

    summaries_path  = input_json.parent / "community_summaries.yaml"
    hierarchy_path  = input_json.parent / "community_hierarchy.yaml"
    try:
        import yaml
    except Exception:
        yaml = None

    titles: dict[str, str] = {}
    summaries: dict[str, str] = {}
    handles_per: dict[str, list[str]] = {}

    if yaml is not None and summaries_path.is_file():
        try:
            data = yaml.safe_load(summaries_path.read_text(encoding="utf-8")) or {}
            for c in data.get("communities", []) or []:
                cid = c.get("id")
                if not cid:
                    continue
                if c.get("title"):
                    titles[cid] = c["title"]
                if c.get("summary"):
                    summaries[cid] = c["summary"]
                if c.get("handles"):
                    handles_per[cid] = list(c["handles"])
        except Exception:
            pass

    super_groups = []
    super_of: dict[str, str] = {}
    if yaml is not None and hierarchy_path.is_file():
        try:
            h = yaml.safe_load(hierarchy_path.read_text(encoding="utf-8")) or {}
            levels = h.get("levels", [])
            # levels[0] is level 1 (the higher / super), levels[1] is level 0
            for lvl in levels:
                if lvl.get("level") == 1:
                    for n in lvl.get("nodes", []):
                        sid = n.get("id")
                        if not sid:
                            continue
                        if n.get("title"):
                            titles[sid] = n["title"]
                        if n.get("summary"):
                            summaries[sid] = n["summary"]
                        if n.get("handles"):
                            handles_per[sid] = list(n["handles"])
                        super_groups.append({
                            "id": sid,
                            "title": n.get("title") or sid,
                            "count": int(n.get("note_count") or 0),
                            "children": list(n.get("children") or []),
                        })
                elif lvl.get("level") == 0:
                    for n in lvl.get("nodes", []):
                        cid, parent = n.get("id"), n.get("parent")
                        if cid and parent:
                            super_of[cid] = parent
        except Exception:
            pass

    if titles:
        payload["community_titles"] = titles
    if summaries:
        payload["community_summaries"] = summaries
    if handles_per:
        payload["community_handles"] = handles_per
    if super_groups:
        payload["super_groups"] = super_groups
        # stable order: largest super-community first
        payload["super_groups"].sort(key=lambda g: -g["count"])
    if super_of:
        payload["super_of"] = super_of
        # annotate each graph node with its super-community
        for node in payload.get("nodes", []) or []:
            l0 = "C" + str(node.get("community"))
            sup = super_of.get(l0)
            if sup:
                node["super_community"] = sup
        # super_community stats
        sc_counts: dict[str, int] = {}
        for node in payload.get("nodes", []) or []:
            sc = node.get("super_community")
            if sc:
                sc_counts[sc] = sc_counts.get(sc, 0) + 1
        payload.setdefault("stats", {})["super_communities"] = sc_counts

    output_html.write_text(render_html(payload), encoding="utf-8")
    s = payload.get("stats", {})
    return {
        "input": str(input_json),
        "output": str(output_html),
        "nodes": s.get("connected_notes", 0),
        "edges": s.get("edges", 0),
        "handles": s.get("handles", 0),
        "handle_source": s.get("handle_source", "?"),
        "titled_communities": len(payload.get("community_titles") or {}),
    }


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Thought Network · Context Hub</title>
<style>
  :root{--bg:#0d1117;--panel:#161b22;--panel2:#161b22cc;--ink:#c9d1d9;
    --ink-soft:#7d8590;--ink-strong:#e6edf3;--accent:#58a6ff;--rule:#30363d;
    --chip:#21262d}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;overflow:hidden}
  #c{display:block;cursor:grab;position:absolute;inset:0}
  #c:active{cursor:grabbing}

  /* top bar */
  #hud{position:fixed;top:0;left:0;right:0;padding:10px 14px;display:flex;gap:14px;
    align-items:center;background:linear-gradient(var(--bg)ee,var(--bg)aa,transparent);
    pointer-events:none;z-index:10}
  #hud *{pointer-events:auto}
  h1{font-size:14px;font-weight:600;margin:0;color:var(--ink-strong)}
  #stats{font-size:12px;color:var(--ink-soft)}
  .btn{background:var(--panel);border:1px solid var(--rule);color:var(--ink);
    border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer}
  .btn:hover{background:#1f242d}
  .toggle{display:inline-flex;gap:0;border-radius:6px;overflow:hidden}
  .toggle .tg{border-radius:0;border-right-width:0}
  .toggle .tg:first-child{border-top-left-radius:6px;border-bottom-left-radius:6px}
  .toggle .tg:last-child{border-top-right-radius:6px;border-bottom-right-radius:6px;border-right-width:1px}
  .toggle .tg.on{background:var(--accent);color:#0d1117;border-color:var(--accent)}
  #search{background:var(--panel);border:1px solid var(--rule);color:var(--ink);
    border-radius:6px;padding:5px 9px;font-size:12px;width:220px}
  .spacer{flex:1}

  /* left sidebar — clusters + hubs */
  #side{position:fixed;left:0;top:48px;bottom:0;width:240px;background:var(--panel2);
    backdrop-filter:blur(6px);border-right:1px solid var(--rule);overflow-y:auto;
    font-size:12px;line-height:1.5;padding:8px 0;z-index:9}
  #side h2{margin:10px 14px 4px;font-size:11px;color:var(--ink-soft);
    text-transform:uppercase;letter-spacing:.04em;font-weight:600}
  .cl{display:flex;align-items:center;padding:3px 14px;cursor:pointer;
    user-select:none;gap:6px}
  .cl:hover{background:#1f242d}
  .cl.off > span.t, .cl.off > i{opacity:.35}
  .cl i{width:9px;height:9px;border-radius:50%;flex-shrink:0}
  .cl .n{color:var(--ink-soft);font-size:11px;margin-left:auto}
  .cl .t{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .cl.l1{font-weight:600;padding-top:6px;padding-bottom:5px}
  .cl.l1 i{width:11px;height:11px}
  .cl.l0{padding-left:30px;color:#adbac7;font-size:11.5px}
  .cl.l0 i{width:7px;height:7px}
  .eye{font-size:11px;color:var(--ink-soft);padding:0 4px;margin-left:2px;
    cursor:pointer;border-radius:3px}
  .eye:hover{background:#2a2f37;color:var(--ink)}
  .summary-card{background:#1f242d;border:1px solid var(--rule);border-radius:6px;
    padding:8px 10px;margin:8px 14px;font-size:11.5px;line-height:1.45;
    color:var(--ink);position:relative}
  .summary-card .h{font-weight:600;font-size:12.5px;margin-bottom:4px}
  .summary-card .meta{font-size:10.5px;color:var(--ink-soft);margin-bottom:6px}
  .summary-card .close-s{position:absolute;top:4px;right:7px;cursor:pointer;color:var(--ink-soft)}
  .summary-card .close-s:hover{color:var(--ink)}
  .hub{padding:5px 14px;cursor:pointer;border-left:2px solid transparent;
    color:var(--ink);font-size:12px;line-height:1.35}
  .hub:hover{background:#1f242d;border-left-color:var(--accent)}
  .hub .deg{color:var(--ink-soft);font-size:10px;margin-right:4px}
  .hub .cl-tag{font-size:10px;color:var(--ink-soft);margin-top:1px}

  /* right detail panel */
  #panel{position:fixed;right:0;top:48px;bottom:0;width:380px;background:var(--panel2);
    backdrop-filter:blur(6px);border-left:1px solid var(--rule);padding:16px 18px;
    overflow-y:auto;transform:translateX(100%);transition:transform .18s;
    font-size:13px;line-height:1.55;z-index:9}
  #panel.open{transform:none}
  #panel .x{position:absolute;top:10px;right:14px;font-size:18px;cursor:pointer;
    color:var(--ink-soft)}
  #panel .x:hover{color:var(--ink)}
  #panel .path{font-family:ui-monospace,Menlo,monospace;font-size:11px;
    color:var(--ink-soft);word-break:break-all;padding-right:24px}
  #panel .date{color:var(--ink-soft);font-size:11px;margin:4px 0 10px}
  #panel .body{color:var(--ink);margin:10px 0}
  #panel .sec{color:var(--ink-soft);font-size:11px;text-transform:uppercase;
    letter-spacing:.04em;margin:14px 0 5px;font-weight:600}
  .chip{display:inline-block;background:var(--chip);border:1px solid var(--rule);
    border-radius:10px;padding:1px 8px;margin:2px 3px 2px 0;font-size:11px;
    color:#adbac7}
  .nb{margin:7px 0;cursor:pointer;padding:6px 8px;border-radius:5px;
    border:1px solid transparent}
  .nb:hover{background:#1f242d;border-color:var(--rule)}
  .nb .nb-prev{color:var(--accent)}
  .nb .nb-via{font-size:11px;color:var(--ink-soft);margin-top:2px}

  /* tooltips */
  #tip{position:fixed;padding:6px 9px;background:var(--panel);
    border:1px solid var(--rule);border-radius:5px;font-size:11px;
    pointer-events:none;opacity:0;transition:opacity .1s;max-width:320px;z-index:20}
  #tip .tip-via{color:var(--ink-soft);margin-top:3px}

  a{color:var(--accent)}
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="hud">
  <h1>Thought Network</h1>
  <span id="stats"></span>
  <div class="spacer"></div>
  <input id="search" placeholder="搜索笔记 / 概念 / handle…" autocomplete="off">
  <div class="toggle" role="group" aria-label="color mode">
    <button class="btn tg" id="tg-community" data-mode="community">主题层级</button>
    <button class="btn tg" id="tg-super" data-mode="super">顶层</button>
  </div>
  <button class="btn" id="fit-btn" title="重置视图">⤢ 重置</button>
</div>
<aside id="side">
  <h2 id="group-title">聚类 (点击切换显隐)</h2>
  <div id="cluster-list"></div>
  <h2>核心枢纽 (Top 20)</h2>
  <div id="hub-list"></div>
</aside>
<div id="tip"></div>
<aside id="panel"></aside>

<script>
const DATA = __DATA__;
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
const tip = document.getElementById('tip'), panel = document.getElementById('panel');

// ---------- layout & state ----------
let DPR = window.devicePixelRatio || 1, W, H;
function resize(){
  W = cv.width  = innerWidth  * DPR;
  H = cv.height = innerHeight * DPR;
  cv.style.width  = innerWidth  + 'px';
  cv.style.height = innerHeight + 'px';
  draw();
}
addEventListener('resize', resize);

const PALETTE = ['#58a6ff','#3fb950','#f778ba','#d29922','#a371f7','#ff7b72',
  '#39c5cf','#e3b341','#79c0ff','#56d364','#ff9bce','#f0883e','#bc8cff',
  '#ffa198','#76e3ea','#eac54f','#7ee787','#ffab70','#d2a8ff','#a5d6ff'];

// Two coloring modes:
//   community — L0 communities (Louvain on the note graph), shown as a
//               hierarchical sidebar (L1 super → L0 children).
//   super     — top-level L1 super-communities only (6 colors max).
let colorMode = 'community';
const groupKeys = {
  community: Object.keys(DATA.stats.communities       || {}),
  super:     Object.keys(DATA.stats.super_communities || {}),
};
const groupCount = {
  community: DATA.stats.communities       || {},
  super:     DATA.stats.super_communities || {},
};
const colorByMode = { community: {}, super: {} };
groupKeys.community.forEach((c,i)=> colorByMode.community[c] = PALETTE[i % PALETTE.length]);
const SUPER_PALETTE = ['#58a6ff','#3fb950','#f778ba','#f0883e','#a371f7','#39c5cf'];
groupKeys.super.forEach((c,i)=> colorByMode.super[c] = SUPER_PALETTE[i % SUPER_PALETTE.length]);
const hiddenByMode = { community: new Set(), super: new Set() };
const keyOf = n =>
  colorMode === 'super' ? (n.super_community || '') : ('C' + n.community);
const colorOf = n => colorByMode[colorMode][keyOf(n)] || '#444';

// Sidecars: titles + summaries + hierarchy
const TITLES    = DATA.community_titles    || {};
const SUMMARIES = DATA.community_summaries || {};
const C_HANDLES = DATA.community_handles   || {};
const SUPER_GROUPS = DATA.super_groups     || [];   // [{id, title, count, children}]
const SUPER_OF  = DATA.super_of            || {};   // {C0: "L1:C2", ...}
const labelOf = key => TITLES[key] || key;

const nodes = DATA.nodes, edges = DATA.edges;
const byId = {}; nodes.forEach(n => byId[n.id] = n);

// normalise coordinates → 0..1000 viewport-agnostic space
let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
nodes.forEach(n=>{minX=Math.min(minX,n.x);maxX=Math.max(maxX,n.x);
  minY=Math.min(minY,n.y);maxY=Math.max(maxY,n.y);});
const span = Math.max(maxX-minX, maxY-minY) || 1;
nodes.forEach(n=>{ n.vx=(n.x-minX)/span*1000; n.vy=(n.y-minY)/span*1000; });

const wmax = Math.max(...edges.map(e=>e.weight), 1);
const dmax = Math.max(...nodes.map(n=>n.degree), 1);

// adjacency (set of neighbour ids per node)
const nbr = {};
edges.forEach(e=>{
  (nbr[e.source] = nbr[e.source] || new Set()).add(e.target);
  (nbr[e.target] = nbr[e.target] || new Set()).add(e.source);
});

// view transform
let scale=1, ox=0, oy=0, inited=false;
function fit(){
  const pad = 40, topPad = 60;
  const sx = (innerWidth - 240 - 380 - 2*pad) / 1000;
  const sy = (innerHeight - topPad - 2*pad) / 1000;
  scale = Math.min(sx, sy);
  ox = 240 + pad + (innerWidth - 240 - 380 - 2*pad - 1000*scale) / 2;
  oy = topPad + pad + (innerHeight - topPad - 2*pad - 1000*scale) / 2;
  inited = true;
}
function tx(x){ return (x*scale + ox) * DPR; }
function ty(y){ return (y*scale + oy) * DPR; }

function visible(n){ return !hiddenByMode[colorMode].has(keyOf(n)); }

let hot=null, sel=null, hotEdge=null, query='';

function radius(n){ return 2.2 + 4.5 * Math.sqrt(n.degree / dmax); }

// ---------- rendering ----------
function draw(){
  if(!inited) fit();
  ctx.clearRect(0,0,W,H);

  // edges first
  ctx.lineCap = 'round';
  for(const e of edges){
    const a = byId[e.source], b = byId[e.target];
    if(!visible(a) || !visible(b)) continue;
    const litByNode = (hot && (e.source===hot.id || e.target===hot.id))
                   || (sel && (e.source===sel.id || e.target===sel.id));
    const litByEdge = (hotEdge === e);
    const lit = litByNode || litByEdge;
    ctx.strokeStyle = lit ? '#58a6ffaa' : '#ffffff10';
    ctx.lineWidth = (lit ? 1.8 : 0.7) * DPR * (0.5 + e.weight / wmax);
    ctx.beginPath();
    ctx.moveTo(tx(a.vx), ty(a.vy));
    ctx.lineTo(tx(b.vx), ty(b.vy));
    ctx.stroke();
  }

  // nodes
  for(const n of nodes){
    if(!visible(n)) continue;
    const r = radius(n) * DPR * Math.max(.6, Math.min(scale, 2));
    const match = query && nodeMatches(n, query);
    const dim = (query ? !match : (hot && hot !== n && !isNeighbor(hot, n)));
    ctx.globalAlpha = dim ? .15 : 1;
    ctx.beginPath();
    ctx.arc(tx(n.vx), ty(n.vy), r, 0, Math.PI*2);
    ctx.fillStyle = colorOf(n);
    ctx.fill();
    if(n === sel || n === hot){
      ctx.globalAlpha = 1;
      ctx.lineWidth = 1.8 * DPR;
      ctx.strokeStyle = '#e6edf3';
      ctx.stroke();
    }
  }
  ctx.globalAlpha = 1;
}

function isNeighbor(a,b){ return nbr[a.id] && nbr[a.id].has(b.id); }

function nodeMatches(n,q){
  return (n.id + ' ' + n.preview + ' ' + n.handles.join(' ') + ' ' +
          n.tags.join(' ')).toLowerCase().includes(q);
}

// ---------- hit testing (nodes + edges) ----------
function pickNode(mx,my){
  let best=null, bd = 14*DPR;
  for(const n of nodes){
    if(!visible(n)) continue;
    const dx = tx(n.vx) - mx*DPR, dy = ty(n.vy) - my*DPR;
    const d = Math.hypot(dx, dy);
    if(d < bd){ bd = d; best = n; }
  }
  return best;
}
function pickEdge(mx,my){
  // only when not near a node
  const px = mx*DPR, py = my*DPR;
  let best=null, bd = 6*DPR;
  for(const e of edges){
    const a = byId[e.source], b = byId[e.target];
    if(!visible(a) || !visible(b)) continue;
    const x1=tx(a.vx), y1=ty(a.vy), x2=tx(b.vx), y2=ty(b.vy);
    const dx=x2-x1, dy=y2-y1, len2=dx*dx+dy*dy;
    if(len2 < 1) continue;
    const t = Math.max(0, Math.min(1, ((px-x1)*dx + (py-y1)*dy) / len2));
    const cx=x1+dx*t, cy=y1+dy*t;
    const d = Math.hypot(px-cx, py-cy);
    if(d < bd){ bd = d; best = e; }
  }
  return best;
}

// ---------- interaction ----------
let drag=false, lx=0, ly=0, moved=false;
cv.addEventListener('mousedown', e=>{ drag=true; lx=e.clientX; ly=e.clientY; moved=false; });
addEventListener('mouseup', ()=> drag=false);
addEventListener('mousemove', e=>{
  if(drag){
    ox += (e.clientX - lx); oy += (e.clientY - ly);
    lx = e.clientX; ly = e.clientY; moved = true;
    draw(); return;
  }
  const n = pickNode(e.clientX, e.clientY);
  if(n !== hot){ hot = n; hotEdge = null; draw(); }
  if(n){
    tip.style.opacity = 1;
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top  = (e.clientY + 12) + 'px';
    tip.innerHTML = esc(n.preview.slice(0,90)) +
      '<div class="tip-via">' + n.handles.slice(0,4).map(esc).join(' · ') + '</div>';
    return;
  }
  // try edge if no node
  const ed = pickEdge(e.clientX, e.clientY);
  if(ed !== hotEdge){ hotEdge = ed; draw(); }
  if(ed){
    tip.style.opacity = 1;
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top  = (e.clientY + 12) + 'px';
    const A = byId[ed.source].preview.slice(0,40);
    const B = byId[ed.target].preview.slice(0,40);
    tip.innerHTML = '<b>via</b> ' + ed.handles.slice(0,6).map(esc).join(' · ') +
      '<div class="tip-via">' + esc(A) + ' ↔ ' + esc(B) + '</div>';
  } else {
    tip.style.opacity = 0;
  }
});
cv.addEventListener('click', e=>{
  if(moved) return;
  const n = pickNode(e.clientX, e.clientY);
  if(n){ openNode(n); return; }
  // click on edge → highlight & show in tooltip-like info
  const ed = pickEdge(e.clientX, e.clientY);
  if(ed){ hotEdge = ed; draw(); }
  else { sel = null; hotEdge = null; panel.classList.remove('open'); draw();
         if(location.hash) history.replaceState(null,'','#'); }
});
cv.addEventListener('wheel', e=>{
  e.preventDefault();
  const f = e.deltaY < 0 ? 1.12 : 0.89;
  const mx = e.clientX, my = e.clientY;
  ox = mx - (mx - ox) * f;
  oy = my - (my - oy) * f;
  scale *= f;
  draw();
}, {passive:false});

document.getElementById('search').addEventListener('input', e=>{
  query = e.target.value.trim().toLowerCase();
  draw();
});
document.getElementById('fit-btn').addEventListener('click', ()=>{ fit(); draw(); });

// ---------- node detail panel ----------
function openNode(n){
  sel = n; hot = n; draw();
  const neighbours = [...(nbr[n.id]||[])].map(id=>byId[id])
    .sort((a,b)=> b.degree - a.degree).slice(0,15);
  const edgeOf = id => edges.find(e =>
    (e.source===n.id && e.target===id) || (e.target===n.id && e.source===id));
  panel.innerHTML =
    '<span class="x" onclick="closePanel()">×</span>' +
    '<div class="path">' + esc(n.id) + '</div>' +
    '<div class="date">' + esc(n.created_at.slice(0,10)) + ' · ' +
       esc(TITLES['C'+n.community] || ('C'+n.community)) + ' · ' +
       n.degree + ' 连接</div>' +
    (n.title ? '<div><b>' + esc(n.title) + '</b></div>' : '') +
    '<div class="body">' + esc(n.preview) + '</div>' +
    '<div class="sec">handles</div>' +
    n.handles.map(h => '<span class="chip">' + esc(h) + '</span>').join('') +
    '<div class="sec">连接到 (' + neighbours.length + ')</div>' +
    neighbours.map(m => {
      const e = edgeOf(m.id);
      const via = e ? e.handles.slice(0,4).map(esc).join(' · ') : '';
      return '<div class="nb" onclick="SEL(' + JSON.stringify(m.id) + ')">'
        + '<div class="nb-prev">' + esc(m.preview.slice(0,50)) + '</div>'
        + '<div class="nb-via">via ' + via + '</div></div>';
    }).join('');
  panel.classList.add('open');
  history.replaceState(null, '', '#note=' + encodeURIComponent(n.id));
}
function closePanel(){
  sel = null; panel.classList.remove('open'); draw();
  history.replaceState(null, '', '#');
}
window.closePanel = closePanel;
window.SEL = id => {
  const n = byId[id]; if(!n) return;
  sel = n; hot = n;
  ox = innerWidth/2 - n.vx * scale;
  oy = innerHeight/2 - n.vy * scale;
  draw(); openNode(n);
};

function esc(s){
  return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'})[c]);
}

// ---------- sidebar: groups + hubs ----------
const clList = document.getElementById('cluster-list');

function makeRow(key, label, count, color, depth, hidden){
  const row = document.createElement('div');
  row.className = 'cl l' + depth + (hidden ? ' off' : '');
  row.dataset.key = key;
  row.innerHTML =
    '<i style="background:' + color + '"></i>' +
    '<span class="t">' + esc(label) + '</span>' +
    '<span class="n">' + count + '</span>' +
    '<span class="eye" title="切换显隐">' + (hidden ? '◌' : '●') + '</span>';
  // click on the eye → toggle visibility; click on the row → open summary panel
  row.querySelector('.eye').addEventListener('click', (e)=>{
    e.stopPropagation();
    const s = hiddenByMode[colorMode];
    if(s.has(key)) s.delete(key); else s.add(key);
    renderGroupList();
    draw();
  });
  row.addEventListener('click', ()=> openCommunity(key));
  return row;
}

function renderGroupList(){
  const title = (colorMode === 'super' ? '顶层主题' : '主题层级 (L1 → L0)')
              + ' · 点 ● 切换显隐 · 点行看总结';
  document.getElementById('group-title').textContent = title;
  clList.innerHTML = '';
  if(colorMode === 'super'){
    SUPER_GROUPS.forEach(g =>
      clList.appendChild(makeRow(g.id, labelOf(g.id), g.count,
        colorByMode.super[g.id], 1, hiddenByMode.super.has(g.id))));
    return;
  }
  // 'community' mode — show L1 then L0 children indented
  SUPER_GROUPS.forEach(g => {
    clList.appendChild(makeRow(g.id, labelOf(g.id), g.count,
      colorByMode.super[g.id], 1, false));
    g.children.forEach(cid => {
      clList.appendChild(makeRow(cid, labelOf(cid),
        groupCount.community[cid] || 0,
        colorByMode.community[cid] || '#888',
        0, hiddenByMode.community.has(cid)));
    });
  });
  // any L0 communities without a parent (shouldn't normally happen, but defensive)
  const claimed = new Set(SUPER_GROUPS.flatMap(g => g.children));
  groupKeys.community.forEach(cid => {
    if(!claimed.has(cid))
      clList.appendChild(makeRow(cid, labelOf(cid), groupCount.community[cid],
        colorByMode.community[cid], 0, hiddenByMode.community.has(cid)));
  });
}

function setMode(m){
  if(m === colorMode) return;
  colorMode = m;
  document.getElementById('tg-community').classList.toggle('on', m === 'community');
  document.getElementById('tg-super').classList.toggle('on', m === 'super');
  renderGroupList();
  draw();
}
document.getElementById('tg-community').addEventListener('click', ()=> setMode('community'));
document.getElementById('tg-super').addEventListener('click',     ()=> setMode('super'));
document.getElementById('tg-community').classList.add('on');
renderGroupList();

// ---------- community / super-community detail panel ----------
function openCommunity(key){
  const isSuper = key.startsWith('L1:');
  const title = labelOf(key);
  const summary = SUMMARIES[key] || '';
  const handles = C_HANDLES[key] || [];
  const count = isSuper
    ? (groupCount.super[key] || 0)
    : (groupCount.community[key] || 0);
  let bodyHtml = '<span class="x" onclick="closePanel()">×</span>'
    + '<div class="path">' + esc(key) + (isSuper ? ' · 顶层' : ' · L0 社区') + '</div>'
    + '<div class="date">' + count + ' 笔记</div>'
    + '<div><b>' + esc(title) + '</b></div>'
    + (summary ? '<div class="body">' + esc(summary) + '</div>' : '')
    + (handles.length ? '<div class="sec">handles</div>'
        + handles.map(h => '<span class="chip">' + esc(h) + '</span>').join('') : '');
  if(isSuper){
    const g = SUPER_GROUPS.find(x => x.id === key);
    if(g){
      bodyHtml += '<div class="sec">包含的 L0 社区 (' + g.children.length + ')</div>';
      g.children.forEach(cid => {
        const cnt = groupCount.community[cid] || 0;
        const t = labelOf(cid);
        const s = SUMMARIES[cid] || '';
        bodyHtml += '<div class="nb" onclick="openCommunity(' + JSON.stringify(cid) + ')">'
          + '<div class="nb-prev">' + esc(t) + ' (' + cnt + ')</div>'
          + (s ? '<div class="nb-via">' + esc(s.slice(0,80)) + '</div>' : '')
          + '</div>';
      });
    }
  } else {
    // L0 — show top member notes
    const members = nodes.filter(n => 'C' + n.community === key)
                         .sort((a,b)=> b.degree - a.degree).slice(0, 15);
    bodyHtml += '<div class="sec">核心笔记 (' + members.length + ' / 共 ' + count + ')</div>';
    members.forEach(n => {
      bodyHtml += '<div class="nb" onclick="SEL(' + JSON.stringify(n.id) + ')">'
        + '<div class="nb-prev">' + esc(n.preview.slice(0, 60)) + '</div>'
        + '<div class="nb-via">deg=' + n.degree + ' · ' + esc(n.id.slice(0,16)) + '</div>'
        + '</div>';
    });
  }
  panel.innerHTML = bodyHtml;
  panel.classList.add('open');
  // dim everything except this group's members on the canvas
  hot = null; sel = null;
  draw();
}
window.openCommunity = openCommunity;

const hubList = document.getElementById('hub-list');
const hubs = nodes.slice().sort((a,b)=> b.degree - a.degree).slice(0, 20);
hubs.forEach(n => {
  const row = document.createElement('div');
  row.className = 'hub';
  row.innerHTML = '<span class="deg">' + n.degree + '</span>' +
                  esc(n.preview.slice(0, 48)) +
                  '<div class="cl-tag">' + esc(TITLES['C'+n.community] || ('C'+n.community)) + '</div>';
  row.addEventListener('click', ()=> SEL(n.id));
  hubList.appendChild(row);
});

// ---------- header stats ----------
document.getElementById('stats').textContent =
  DATA.stats.connected_notes + ' 节点 · ' + DATA.stats.edges + ' 边 · ' +
  DATA.stats.handles + ' handles · 来源: ' +
  (DATA.stats.handle_source === 'agent' ? 'agent-judged' : 'deterministic') +
  (DATA.stats.excluded_notes ? ' · ' + DATA.stats.excluded_notes + ' 杂务已排除' : '');

// ---------- URL hash deep link ----------
function applyHash(){
  const h = location.hash;
  if(h.startsWith('#note=')){
    const id = decodeURIComponent(h.slice(6));
    if(byId[id]) SEL(id);
  }
}
addEventListener('hashchange', applyHash);

resize();
applyHash();
</script>
</body>
</html>
"""
