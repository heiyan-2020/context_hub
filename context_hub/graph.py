"""Note-level graph of latent connections.

Nodes are individual notes, edges are latent connections discovered from
shared "handles" — recurring-but-distinctive terms two notes have in
common.  An edge is labeled (which handles) and weighted (how rare those
handles are), so a note can connect across topics.

Two paths produce handles:

A. **Deterministic** (stdlib-only): bigram/tag extraction with DF window,
   PMI cohesion, and collocation collapse.  Runs out-of-the-box.

B. **Agent-judged** (preferred): the `build-graph` skill orchestrates
   agents to (1) curate a handle vocabulary from the deterministic pool,
   then (2) label each note with handles from that vocabulary, writing
   `_index/agent_handles.yaml`.  This module reads that file
   automatically if present.

Either way the downstream pipeline is identical:

  3. project     bipartite projection: notes sharing handles get an
                 edge, weight = Σ shared-handle IDF
  4. cap         prune weak edges, cap per-node degree
  5. community   multi-level weighted Louvain → L0 communities
  6. layout      Fruchterman-Reingold with Barnes-Hut quadtree repulsion
  7. emit        _index/graph.json + _index/graph.html

The `build-graph` skill recursively reuses `louvain()` on the L0
community summaries (produced by Stage 5 agents) to form L1
super-communities, yielding the final `_index/community_hierarchy.yaml`.
"""
from __future__ import annotations

import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .index import INDEX_DIR_NAME, ManagedItem, iter_managed
from .visualize import render_html  # re-export

# ---------- tuning knobs ----------

MIN_DF = 5               # a handle must recur in >= this many notes
MAX_DF_FRAC = 0.06       # ...and appear in <= this fraction of the corpus
TOP_K = 10               # handles kept per note (by IDF)
MIN_EDGE_WEIGHT = 10.0   # prune edges below this summed-IDF weight: a single
                         # shared common tag must NOT be enough for an edge
MAX_DEGREE = 7           # keep at most this many strongest edges per node
COHESION_MIN = 2.6       # min internal PMI for a CJK bigram to be a real "word"
LAYOUT_ITERS = 260
GRAVITY = 0.045          # pull toward centre so density varies (vs. uniform fill)
SCHEMA_VERSION = 1

# Purely-operational tags — these mark chore/log notes, not thinking.
# Two uses, same set:
#   (1) tokens with these leaf names are never emitted as handles
#   (2) a note carrying any such tag is excluded from the graph entirely
#       (both as nodes and from the DF/PMI corpus stats)
EXCLUDE_USER_TAGS = {"日记", "工作时间企划", "日计划", "todo", "打卡",
                    "周计划", "月计划", "购物", "驾考", "健身记录"}
STOP_TAGS = EXCLUDE_USER_TAGS  # alias for handle-side filtering in tokenize()

# ---------- tokenization ----------

_CJK = r"一-鿿㐀-䶿"
_CJK_RUN = re.compile(f"[{_CJK}]+")
_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")
_URL = re.compile(r"https?://\S+")
_TAG_INLINE = re.compile(rf"(?<![\w/])#([\w/\-{_CJK}]+)")
_MD_NOISE = re.compile(r"[`*_>~\[\]()|!]+")

# CJK function characters — a bigram made entirely of these is junk.
_CJK_FUNC = set(
    "的了是我你他她它们这那个不在有和与也就都要会能对把被让给从向到于之其"
    "而且但或如若因为所以及等着过地得很太更最还又再只自己一二三四五六七八九十"
    "时候吗呢吧啊呀么没下上来去做想说看知道觉得这样那样什么怎么可以就是这种"
)
_EN_STOP = {
    "the", "and", "for", "that", "this", "with", "are", "was", "but", "not",
    "you", "have", "can", "all", "from", "one", "his", "her", "they", "what",
    "when", "how", "why", "out", "use", "get", "got", "via", "etc", "com",
    "www", "http", "https", "html", "https", "md", "png", "jpg",
}


def _clean(body: str) -> str:
    s = _URL.sub(" ", body)
    s = _TAG_INLINE.sub(" ", s)         # inline #tags handled separately
    s = _MD_NOISE.sub(" ", s)
    return s


def tokenize(body: str, tags: tuple[str, ...]) -> Counter:
    """Return a Counter of candidate handle tokens for one note.

    Tokens: ASCII words, CJK bigrams + trigrams, and the note's own #tags
    (a tag is a hand-curated multi-char term — a high-quality handle).
    """
    text = _clean(body)
    counts: Counter = Counter()

    for m in _ASCII_WORD.finditer(text):
        w = m.group(0).lower().strip(".#-+")
        if len(w) >= 3 and w not in _EN_STOP and not w.isdigit():
            counts[w] += 1

    # CJK bigrams only: trigrams+ produce sliding-window fragments
    # ("记写作"/"笔记写") that no longer n-gram exists to absorb.  Genuine
    # multi-char concepts come through the user's curated #tags instead.
    for run in _CJK_RUN.findall(text):
        for i in range(len(run) - 1):
            bi = run[i:i + 2]
            if not all(c in _CJK_FUNC for c in bi):
                counts[bi] += 1

    for t in tags:
        # use the leaf of a hierarchical tag (e.g. "知识/哲学" -> "哲学")
        leaf = t.split("/")[-1].strip()
        if leaf and leaf not in STOP_TAGS:
            counts["#" + leaf] += 2   # slight boost: curated signal

    return counts


# ---------- word-quality: PMI cohesion + collocation collapse ----------


def _corpus_char_stats(notes: list[ManagedItem]) -> tuple[Counter, Counter, int]:
    """Char unigram + adjacent-char-bigram counts over CJK runs (for PMI)."""
    uni: Counter = Counter()
    bi: Counter = Counter()
    total = 0
    for it in notes:
        for run in _CJK_RUN.findall(_clean(it.body)):
            total += len(run)
            for c in run:
                uni[c] += 1
            for i in range(len(run) - 1):
                bi[run[i:i + 2]] += 1
    return uni, bi, total


def _min_adjacent_pmi(gram: str, uni: Counter, bi: Counter, total: int) -> float:
    """Minimum PMI over the adjacent char pairs of a CJK n-gram.

    A genuine word/phrase has every junction "sticky" (high PMI); a
    sliding-window fragment of unrelated chars has at least one loose junction.
    """
    worst = math.inf
    for i in range(len(gram) - 1):
        a, b, ab = gram[i], gram[i + 1], gram[i:i + 2]
        ca, cb, cab = uni.get(a, 0), uni.get(b, 0), bi.get(ab, 0)
        if cab == 0 or ca == 0 or cb == 0:
            return -math.inf
        pmi = math.log((cab * total) / (ca * cb))
        worst = min(worst, pmi)
    return worst


def _collapse_subgrams(df: dict[str, int]) -> set[str]:
    """Return the set of CJK n-grams to DROP because a longer n-gram absorbs them.

    A sub-gram `s` is absorbed by superstring `G` when `s` rarely occurs outside
    `G` (df(s) <= df(G) * COLLAPSE_RATIO).  This merges "设计方"/"计方案" into the
    parent "设计方案" while keeping genuinely independent terms (whose df is much
    higher than any superstring's).
    """
    cjk = [g for g in df if g and g[0] not in ('#',) and not g[0].isascii()]
    by_len: dict[int, list[str]] = defaultdict(list)
    for g in cjk:
        by_len[len(g)].append(g)
    drop: set[str] = set()
    longer = sorted((g for g in cjk if len(g) >= 3), key=lambda g: -len(g))
    for G in longer:
        dG = df[G]
        for L in (2, len(G) - 1):
            if L < 2 or L >= len(G):
                continue
            for i in range(len(G) - L + 1):
                s = G[i:i + L]
                if s in df and df[s] <= dG * COLLAPSE_RATIO:
                    drop.add(s)
    return drop


# ---------- handle selection ----------


def select_handles(
    notes: list[ManagedItem],
) -> tuple[dict[str, set[str]], dict[str, float], dict[str, int]]:
    """Pick each note's handles.

    Returns:
      handles_by_note: rel_path -> set of handle strings
      idf:             handle -> idf weight
      df:              handle -> document frequency (for the artifact)
    """
    n = len(notes)
    per_note_counts: dict[str, Counter] = {}
    df: Counter = Counter()
    for it in notes:
        c = tokenize(it.body, it.tags)
        per_note_counts[it.rel_path] = c
        for tok in c:
            df[tok] += 1

    uni, bi, total = _corpus_char_stats(notes)
    max_df = max(MIN_DF, int(n * MAX_DF_FRAC))

    # pass 1: df-window candidates
    candidates = {tok for tok, d in df.items() if MIN_DF <= d <= max_df}

    # pass 2: kill loose CJK n-grams (junk like "间自"); tags + ascii are exempt
    def is_cjk(tok: str) -> bool:
        return bool(tok) and not tok.startswith("#") and not tok[0].isascii()

    def kept_by_cohesion(tok: str) -> bool:
        if not is_cjk(tok):
            return True
        bar = COHESION_MIN if len(tok) == 2 else COHESION_MIN * 0.5
        return _min_adjacent_pmi(tok, uni, bi, total) >= bar

    candidates = {t for t in candidates if kept_by_cohesion(t)}

    # pass 3: collocation collapse — drop fragments absorbed by a longer n-gram
    cand_df = {t: df[t] for t in candidates}
    candidates -= _collapse_subgrams(cand_df)

    # IDF, with a curated-tag boost (the user's own #tags are high-quality)
    handle_idf: dict[str, float] = {}
    for tok in candidates:
        idf = math.log(n / df[tok])
        if tok.startswith("#"):
            idf *= 1.6
        handle_idf[tok] = idf

    handles_by_note: dict[str, set[str]] = {}
    for rel, c in per_note_counts.items():
        scored = []
        for tok, tf in c.items():
            idf = handle_idf.get(tok)
            if idf is None:
                continue
            scored.append((idf * (1.0 + 0.3 * math.log(tf)), tok))
        scored.sort(reverse=True)
        handles_by_note[rel] = {tok for _, tok in scored[:TOP_K]}

    df_kept = {h: df[h] for h in handle_idf}
    return handles_by_note, handle_idf, df_kept


# ---------- bipartite projection ----------


def build_edges(
    handles_by_note: dict[str, set[str]],
    idf: dict[str, float],
) -> dict[tuple[str, str], dict]:
    """Project the note<->handle bipartite graph onto note<->note edges.

    Edge weight = sum of IDF over shared handles.  Returns
    {(a, b): {"weight": float, "handles": [...]}} with a < b.
    """
    # invert: handle -> [notes carrying it]
    by_handle: dict[str, list[str]] = defaultdict(list)
    for rel, hs in handles_by_note.items():
        for h in hs:
            by_handle[h].append(rel)

    raw: dict[tuple[str, str], list[str]] = defaultdict(list)
    for h, members in by_handle.items():
        if len(members) < 2:
            continue
        members = sorted(members)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                raw[(members[i], members[j])].append(h)

    edges: dict[tuple[str, str], dict] = {}
    for pair, shared in raw.items():
        shared = _dedup_substrings(shared)
        w = sum(idf[h] for h in shared)
        if w >= MIN_EDGE_WEIGHT:
            shared_sorted = sorted(shared, key=lambda h: -idf[h])
            edges[pair] = {"weight": round(w, 3), "handles": shared_sorted}
    return edges


def _dedup_substrings(handles: list[str]) -> list[str]:
    """Within one edge, drop a handle that is a substring of another shared
    handle (keeps "设计方案", drops a stray "设计方" that slipped through)."""
    hs = sorted(set(handles), key=len, reverse=True)
    kept: list[str] = []
    for h in hs:
        if any(h != k and h in k for k in kept):
            continue
        kept.append(h)
    return kept


def cap_degree(edges: dict[tuple[str, str], dict]) -> dict[tuple[str, str], dict]:
    """Keep at most MAX_DEGREE strongest edges per node (union-keep:
    an edge survives if it is in the top-MAX_DEGREE of *either* endpoint)."""
    incident: dict[str, list[tuple[float, tuple[str, str]]]] = defaultdict(list)
    for pair, d in edges.items():
        incident[pair[0]].append((d["weight"], pair))
        incident[pair[1]].append((d["weight"], pair))

    keep: set[tuple[str, str]] = set()
    for _, lst in incident.items():
        lst.sort(reverse=True)
        for _, pair in lst[:MAX_DEGREE]:
            keep.add(pair)
    return {p: edges[p] for p in keep}


# ---------- community detection (Louvain) ----------


def louvain(
    node_ids: list[str],
    edges_dict: dict[tuple[str, str], dict],
    seed: int = 42,
    max_inner_rounds: int = 50,
    max_levels: int = 12,
) -> dict[str, int]:
    """Multi-level weighted Louvain modularity optimisation.

    Inputs are the thought-network's node list and weighted edge dict.
    Returns: {node_id: community_id} with community_ids as consecutive ints
    starting at 0.

    The algorithm: at each level, repeatedly try to move each (super-)node
    into the neighbouring community giving the largest modularity gain;
    when no moves help, contract each community into a single super-node
    and recurse.  Stops when a level produces no further merges.

    Pure-Python, no deps.  ~O(L · n) per level for sparse graphs where L
    is the average degree; on 1500 nodes / 4300 edges this runs in
    well under a second.
    """
    if not node_ids:
        return {}
    n0 = len(node_ids)
    idx = {n: i for i, n in enumerate(node_ids)}

    # Level-0 adjacency (symmetric, no self-loops expected from build_edges)
    adj: list[dict[int, float]] = [dict() for _ in range(n0)]
    self_loop = [0.0] * n0
    for (a, b), d in edges_dict.items():
        w = d["weight"]
        ia, ib = idx[a], idx[b]
        if ia == ib:
            self_loop[ia] += w
        else:
            adj[ia][ib] = adj[ia].get(ib, 0.0) + w
            adj[ib][ia] = adj[ib].get(ia, 0.0) + w

    final = list(range(n0))  # original-node index -> current super-node label
    super_adj = adj
    super_self = self_loop

    rng = random.Random(seed)

    for _level in range(max_levels):
        n = len(super_adj)
        # weighted degree (self-loops count twice in degree)
        k = [sum(super_adj[i].values()) + 2.0 * super_self[i] for i in range(n)]
        m = sum(k) / 2.0
        if m < 1e-12:
            break
        two_m = 2.0 * m

        comm = list(range(n))           # each super-node in its own community
        sigma_tot = list(k)              # sum of degrees in each community

        # local-move phase
        for _ in range(max_inner_rounds):
            improved = False
            order = list(range(n))
            rng.shuffle(order)
            for i in order:
                ki = k[i]
                ci = comm[i]
                # weights from i to each neighbouring community
                ki_to: dict[int, float] = {}
                for j, w in super_adj[i].items():
                    cj = comm[j]
                    ki_to[cj] = ki_to.get(cj, 0.0) + w
                # remove i from ci (it'll be re-added below)
                sigma_tot[ci] -= ki
                best_c = ci
                best_gain = 0.0
                # ki_to[ci] (after removal) reflects i's edges to remaining ci members
                ki_in_ci = ki_to.get(ci, 0.0)
                # baseline gain for staying = 0 (we just removed; staying = adding back)
                # gain of joining cj = ki_to[cj] - sigma_tot[cj] * ki / (2m)
                for cj, kic in ki_to.items():
                    gain = kic - sigma_tot[cj] * ki / two_m
                    if gain > best_gain + 1e-12:
                        best_gain = gain
                        best_c = cj
                # also consider going back to ci explicitly:
                ci_gain = ki_in_ci - sigma_tot[ci] * ki / two_m
                if ci_gain > best_gain + 1e-12:
                    best_gain = ci_gain
                    best_c = ci
                comm[i] = best_c
                sigma_tot[best_c] += ki
                if best_c != ci:
                    improved = True
            if not improved:
                break

        # check whether anything merged
        unique = sorted(set(comm))
        if len(unique) == n:
            break

        # relabel comm to consecutive ints
        label = {c: i for i, c in enumerate(unique)}
        comm = [label[c] for c in comm]
        for i in range(n0):
            final[i] = comm[final[i]]

        # aggregate
        new_n = len(unique)
        new_adj: list[dict[int, float]] = [dict() for _ in range(new_n)]
        new_self = [0.0] * new_n
        for i in range(n):
            ci = comm[i]
            new_self[ci] += super_self[i]
            for j, w in super_adj[i].items():
                cj = comm[j]
                if ci == cj:
                    # symmetric adj double-counts intra-community edges
                    new_self[ci] += w / 2.0
                else:
                    new_adj[ci][cj] = new_adj[ci].get(cj, 0.0) + w
        super_adj = new_adj
        super_self = new_self

    # consecutive output labels (assigned in encounter order so the largest
    # community by node count tends to land near 0)
    counts: Counter = Counter(final)
    order_by_size = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    relabel = {old: new for new, (old, _) in enumerate(order_by_size)}
    return {nid: relabel[final[i]] for i, nid in enumerate(node_ids)}


# ---------- force layout ----------


class _QuadNode:
    """A Barnes-Hut quadtree cell: tracks mass + summed position for its
    sub-tree so distant clumps can be approximated by their centre of mass."""
    __slots__ = ("x0", "y0", "size", "mass", "sx", "sy", "body", "kids")

    def __init__(self, x0: float, y0: float, size: float):
        self.x0, self.y0, self.size = x0, y0, size
        self.mass = 0
        self.sx = self.sy = 0.0
        self.body: int | None = None      # leaf: index of the single body
        self.kids: list[_QuadNode] | None = None

    def _quadrant(self, px: float, py: float) -> "_QuadNode":
        h = self.size / 2.0
        i = (1 if px >= self.x0 + h else 0) + (2 if py >= self.y0 + h else 0)
        if self.kids is None:
            self.kids = [
                _QuadNode(self.x0, self.y0, h),
                _QuadNode(self.x0 + h, self.y0, h),
                _QuadNode(self.x0, self.y0 + h, h),
                _QuadNode(self.x0 + h, self.y0 + h, h),
            ]
        return self.kids[i]

    def insert(self, i: int, px: float, py: float, pos: list) -> None:
        self.mass += 1
        self.sx += px
        self.sy += py
        if self.body is None and self.kids is None:
            self.body = i
            return
        if self.kids is None or self.body is not None:
            # leaf with an existing body — push it down, unless cell is tiny
            if self.size < 1.0:
                return  # near-coincident points: stop subdividing
            j = self.body
            self.body = None
            jx, jy = pos[j]
            self._quadrant(jx, jy).insert(j, jx, jy, pos)
        self._quadrant(px, py).insert(i, px, py, pos)

    def repulse(self, i: int, px: float, py: float, k: float,
                theta: float, out: list) -> None:
        if self.mass == 0 or (self.body == i and self.mass == 1):
            return
        cx, cy = self.sx / self.mass, self.sy / self.mass
        dx, dy = px - cx, py - cy
        d2 = dx * dx + dy * dy
        if d2 < 1e-9:
            return
        d = math.sqrt(d2)
        if self.kids is None or self.size / d < theta:
            f = k * k * self.mass / d
            out[0] += dx / d * f
            out[1] += dy / d * f
        else:
            for c in self.kids:
                c.repulse(i, px, py, k, theta, out)


def layout(
    node_ids: list[str],
    edges: dict[tuple[str, str], dict],
    iters: int = LAYOUT_ITERS,
    seed: int = 7,
    theta: float = 0.8,
) -> dict[str, tuple[float, float]]:
    """Fruchterman-Reingold layout with Barnes-Hut repulsion (O(n log n)).

    Barnes-Hut gives *smooth* repulsion from every node (approximated by
    centre-of-mass for distant clumps), so — unlike grid-bucketed repulsion —
    the layout doesn't crystallise into a lattice.
    """
    rng = random.Random(seed)
    n = len(node_ids)
    if n == 0:
        return {}
    idx = {nid: i for i, nid in enumerate(node_ids)}
    W = H = math.sqrt(n) * 80.0
    pos = [[rng.uniform(0, W), rng.uniform(0, H)] for _ in range(n)]
    disp = [[0.0, 0.0] for _ in range(n)]
    k = math.sqrt(W * H / n)

    elist = [(idx[a], idx[b], d["weight"]) for (a, b), d in edges.items()]
    wmax = max((w for _, _, w in elist), default=1.0)

    t = W / 10.0
    cool = t / (iters + 1)

    for _ in range(iters):
        for d in disp:
            d[0] = d[1] = 0.0

        # Barnes-Hut repulsion: build a fresh quadtree, query each node
        lo_x = min(p[0] for p in pos)
        lo_y = min(p[1] for p in pos)
        span = max(max(p[0] for p in pos) - lo_x,
                   max(p[1] for p in pos) - lo_y, 1.0) * 1.01
        qt = _QuadNode(lo_x, lo_y, span)
        for i in range(n):
            qt.insert(i, pos[i][0], pos[i][1], pos)
        for i in range(n):
            out = disp[i]
            qt.repulse(i, pos[i][0], pos[i][1], k, theta, out)

        # attraction along edges (stronger for heavier edges)
        for ia, ib, w in elist:
            dx = pos[ia][0] - pos[ib][0]
            dy = pos[ia][1] - pos[ib][1]
            dist = math.sqrt(dx * dx + dy * dy) or 1e-6
            force = (dist * dist) / k * (0.4 + 0.6 * w / wmax)
            ox = dx / dist * force
            oy = dy / dist * force
            disp[ia][0] -= ox
            disp[ia][1] -= oy
            disp[ib][0] += ox
            disp[ib][1] += oy

        # gravity toward centre — gives the layout a potential well so dense
        # regions contract instead of everything spreading to fill the box
        # (which is what made the graph read as a uniform grid).
        cx, cy = W / 2.0, H / 2.0
        for i in range(n):
            disp[i][0] += (cx - pos[i][0]) * GRAVITY
            disp[i][1] += (cy - pos[i][1]) * GRAVITY

        for i in range(n):
            dl = math.sqrt(disp[i][0] ** 2 + disp[i][1] ** 2) or 1e-6
            pos[i][0] += disp[i][0] / dl * min(dl, t)
            pos[i][1] += disp[i][1] / dl * min(dl, t)
        t -= cool

    return {nid: (round(pos[idx[nid]][0], 2), round(pos[idx[nid]][1], 2))
            for nid in node_ids}


# ---------- assembly ----------


def _preview(body: str, n: int = 120) -> str:
    s = _TAG_INLINE.sub("", body)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _agent_handles(
    notes: list[ManagedItem],
    path: Path,
) -> tuple[dict[str, set[str]], dict[str, float], dict[str, int]]:
    """Load agent-judged handles from `agent_handles.yaml` and compute IDF.

    Schema:
        schema_version: 1
        assignments:
          <rel_path>: ["handle1", "handle2", ...]

    A handle only contributes to edges if it appears in >= 2 notes (axiomatic
    — a handle nobody else has can't connect) and isn't ubiquitous
    (df <= MAX_DF_FRAC*N).
    """
    import yaml as _yaml
    raw = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assignments = raw.get("assignments", raw) if isinstance(raw, dict) else {}

    def norm(h: str) -> str:
        return h.strip().lower() if h.isascii() else h.strip()

    per_note: dict[str, set[str]] = {}
    for it in notes:
        hs = assignments.get(it.rel_path, []) or []
        per_note[it.rel_path] = {norm(h) for h in hs if isinstance(h, str) and h.strip()}

    df: Counter = Counter()
    for hs in per_note.values():
        for h in hs:
            df[h] += 1

    n = len(notes)
    max_df = max(2, int(n * MAX_DF_FRAC))
    # Agent handles are 100% curated (one agent picked the vocabulary, then
    # parallel labelers chose from it).  Treat them like the bigram path's
    # #tag handles: 1.6x IDF boost so MIN_EDGE_WEIGHT calibration carries
    # over without retuning.
    AGENT_IDF_BOOST = 1.6
    kept_idf = {h: math.log(n / d) * AGENT_IDF_BOOST
                for h, d in df.items() if 2 <= d <= max_df}

    handles_by_note = {rel: {h for h in hs if h in kept_idf}
                       for rel, hs in per_note.items()}
    df_kept = {h: df[h] for h in kept_idf}
    return handles_by_note, kept_idf, df_kept


def build_graph(root: Path) -> dict:
    """Run the whole pipeline; return the graph.json payload dict.

    If `<root>/_index/agent_handles.yaml` exists (a path → [handle] mapping
    produced by the build-graph skill's Stage 2), it overrides the
    deterministic bigram/tag extraction.  Otherwise we fall back to the
    stdlib bigram pipeline.

    Note exclusion: any note whose tags include a leaf in `EXCLUDE_USER_TAGS`
    is dropped from the graph (chore/log notes — not thinking).
    """
    all_notes = list(iter_managed(root))
    idx_dir = root / INDEX_DIR_NAME

    def excluded(it: ManagedItem) -> bool:
        for t in it.tags:
            if t.split("/")[-1] in EXCLUDE_USER_TAGS:
                return True
        return False

    notes = [it for it in all_notes if not excluded(it)]
    excluded_count = len(all_notes) - len(notes)

    agent_path = idx_dir / "agent_handles.yaml"
    source = "deterministic"
    if agent_path.is_file():
        handles_by_note, idf, df = _agent_handles(notes, agent_path)
        source = "agent"
    else:
        handles_by_note, idf, df = select_handles(notes)
    edges = cap_degree(build_edges(handles_by_note, idf))

    connected: set[str] = set()
    for a, b in edges:
        connected.add(a)
        connected.add(b)

    note_by_rel = {it.rel_path: it for it in notes}
    node_ids = sorted(connected)
    pos = layout(node_ids, edges)
    community_of = louvain(node_ids, edges)

    communities: Counter = Counter()
    nodes_out = []
    for rel in node_ids:
        it = note_by_rel[rel]
        cm = community_of[rel]
        communities[cm] += 1
        x, y = pos[rel]
        deg = sum(1 for e in edges if rel in e)
        nodes_out.append({
            "id": rel,
            "x": x,
            "y": y,
            "community": cm,
            "degree": deg,
            "created_at": it.created_at.isoformat(),
            "title": it.title or "",
            "tags": list(it.tags),
            "handles": sorted(handles_by_note[rel]),
            "preview": _preview(it.body),
        })

    edges_out = []
    for (a, b), d in sorted(edges.items(), key=lambda kv: -kv[1]["weight"]):
        edges_out.append({
            "source": a,
            "target": b,
            "weight": d["weight"],
            "handles": d["handles"],
        })

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "params": {
            "min_df": MIN_DF,
            "max_df_frac": MAX_DF_FRAC,
            "top_k": TOP_K,
            "min_edge_weight": MIN_EDGE_WEIGHT,
            "max_degree": MAX_DEGREE,
        },
        "stats": {
            "total_notes": len(all_notes),
            "in_scope_notes": len(notes),
            "excluded_notes": excluded_count,
            "connected_notes": len(node_ids),
            "edges": len(edges_out),
            "handles": len(idf),
            "handle_source": source,
            "communities": {f"C{cid}": cnt for cid, cnt in communities.most_common()},
        },
        "nodes": nodes_out,
        "edges": edges_out,
    }


# ---------- artifacts ----------


def render_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


# ---------- orchestrator ----------


def generate_graph(root: Path) -> dict:
    """Build the graph and write both artifacts into <root>/_index/.

    Returns a small stats dict for the CLI summary.
    """
    idx_dir = root / INDEX_DIR_NAME
    idx_dir.mkdir(parents=True, exist_ok=True)
    payload = build_graph(root)
    _atomic_write(idx_dir / "graph.json", render_json(payload))
    _atomic_write(idx_dir / "graph.html", render_html(payload))
    return payload["stats"] | {"generated_at": payload["generated_at"]}


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
