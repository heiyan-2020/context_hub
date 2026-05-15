---
name: build-graph
description: Build the hierarchical thought-network for a context hub. Runs a 6-stage pipeline that mixes deterministic Python (handle extraction, edge construction, Louvain community detection, layout) with agent-judged steps (vocabulary curation, per-note labeling, community summarization, level-1 summarization). Output is a 2-level hierarchy under `_index/community_hierarchy.yaml` plus a self-contained HTML viewer at `_index/graph.html`. Use whenever the user wants to (re)build the hierarchical graph over their hub, or after substantial new note ingestion.
---

# build-graph

This skill orchestrates the full pipeline that takes a hub of personal notes
and produces a **hierarchical thought-network**:

```
notes (~2000+)
   ↓  Stage 0: deterministic bigram graph
graph.json (bigram baseline; 2800+ noisy handles)
   ↓  Stage 1: ONE Opus agent curates the vocabulary
vocabulary.yaml (~500 clean concept handles)
   ↓  Stage 2: N Sonnet agents label each note from the fixed vocabulary
agent_handles.yaml (path → [handles])
   ↓  Stage 3: re-run deterministic pipeline using agent handles
graph.json (agent path; cleaner edges; Louvain → L0 communities)
   ↓  Stage 4: prepare per-community input files
   ↓  Stage 5: one Sonnet agent per L0 community → title + summary + handles
community_summaries.yaml
   ↓  Stage 6a: run Louvain on the L0-summary graph
level1_grouping.yaml
   ↓  Stage 6b: one Sonnet agent per L1 super-community → title + summary
community_hierarchy.yaml + graph.html (final)
```

**Cost**: roughly 1 Opus call (curator) + N+M Sonnet calls (labelers +
summarizers). For ~2000 notes typically N=14, M=20-30 (Stage 5), and 5-10
(Stage 6), so ~40-50 Sonnet calls total. Total tokens ~500k-800k.

---

## Inputs you need before starting

1. **`HUB`** — absolute path to the hub root (the dir containing the
   `YYYY/MM/DD/...md` notes and `_index/`).
2. **Approximate corpus size**, to decide batch count for Stage 2.
   Run `find $HUB -name '*.md' -not -path '*/_index/*' | wc -l`. Target
   ~150 notes per batch.

The rest is automatic.

---

## Stage 0 — Deterministic graph (no agent)

Run the bigram pipeline first. This produces `graph.json` with ~2000-3000
candidate handles (noisy but covers the corpus), which feeds Stage 1.

```bash
context-hub graph --root "$HUB"
```

If `_index/agent_handles.yaml` already exists from a previous run, **delete
it first** — otherwise the CLI will pick the agent path and Stage 1 has
nothing fresh to look at:

```bash
rm -f "$HUB/_index/agent_handles.yaml"
context-hub graph --root "$HUB"
```

Confirm the JSON has `"handle_source": "deterministic"`.

---

## Stage 1 — Curate the handle vocabulary (1 Opus agent)

Prepare the candidate list:

```bash
python "$(context-hub skill-path build-graph | xargs dirname)/scripts/prepare_candidates.py" \
   --root "$HUB"
```

This writes `$HUB/_index/agent-work/candidates.md` — every unique handle
from the deterministic graph, grouped by kind (user-tag / english / CJK),
with document frequency.

**Dispatch ONE curator agent (Opus)** with this prompt template — fill in
`$HUB`:

> You are curating a vocabulary of meaningful concept handles from a
> programmatically-extracted candidate pool. The vocabulary will be used by
> parallel labelers to tag each note with handles drawn ONLY from your
> vocabulary, so consistency matters.
>
> Read `$HUB/_index/agent-work/candidates.md`.
>
> Keep handles that are **named concepts, claims, recurring themes,
> thinkers, methods, or domain terms** the user actually thinks about.
> Drop fragments, function-word pairs, vacuous abstractions ("思考",
> "重要", "事情"), operational/chore tags, dates, and one-off names.
>
> Target size **~300 (range 200-500)**. Quality > quantity. For Chinese
> bigrams, be ruthless — most are junk; keep only those that are
> themselves complete words. You can also **reconstruct multi-char
> concepts** from fragment evidence (e.g. if `工具理`, `具理性`, and
> `工具理` all appear, keep `工具理性` as the canonical form even if it
> isn't literally in candidates).
>
> Write `$HUB/_index/agent-work/vocabulary.yaml`:
> ```yaml
> schema_version: 1
> vocabulary:
>   - 工具理性
>   - 价值理性
>   - 完美主义
>   - ...
> ```
> Bare strings, no `#` prefix. Then report total count, breakdown by
> kind, and 5-10 borderline judgment calls.

---

## Stage 2 — Parallel labeling (N Sonnet agents)

Split the in-scope notes into N batches:

```bash
python "$(context-hub skill-path build-graph | xargs dirname)/scripts/prepare_batches.py" \
   --root "$HUB" --batches 14
```

This writes `$HUB/_index/agent-work/batch-XX.md` (paths + previews +
existing user tags). The script applies the same `EXCLUDE_USER_TAGS`
filter the graph pipeline uses, so chore notes aren't even sent to
labelers.

**Dispatch N labeler agents in parallel (Sonnet, model:`sonnet`)** — one
per batch. Each gets this prompt with batch number filled in:

> You are LABELING notes with handles from a fixed vocabulary. Two notes
> that share rare handles will be connected as edges in a thought-network
> graph, so the quality of your labels determines whether the edges are
> meaningful.
>
> 1. Read vocabulary: `$HUB/_index/agent-work/vocabulary.yaml`. Your
>    `vocabulary:` list is the CLOSED set of allowed handle strings.
> 2. Read batch: `$HUB/_index/agent-work/batch-NN.md`.
>
> For each note, pick **3-6 handles from the vocabulary** that describe
> what the note is *about*. Match on meaning, not substring. If no
> vocabulary handle fits (sparse note, leaked chore), emit `[]`.
>
> Write `$HUB/_index/agent-work/result-NN.yaml`:
> ```yaml
> schema_version: 1
> batch: NN
> assignments:
>   "<rel_path>":
>     - <handle from vocabulary>
> ```
> Every path in the batch must appear; strings must EXACTLY match
> `vocabulary.yaml`. Report total notes, average handles/note, and 3
> least-confident labels.

Once all N agents finish, aggregate:

```bash
python "$(context-hub skill-path build-graph | xargs dirname)/scripts/aggregate_handles.py" \
   --root "$HUB"
```

This writes `$HUB/_index/agent_handles.yaml`. Out-of-vocabulary labels are
silently dropped (with a count); a handle is only kept if it appears in
≥2 notes.

---

## Stage 3 — Rebuild the graph using agent handles

```bash
context-hub graph --root "$HUB"
```

Now `graph.json` has `"handle_source": "agent"`, ~500 clean handles, and
visibly tighter edges. Louvain communities (L0) are written into each
node's `community` field.

---

## Stage 4 — Prepare per-community inputs

```bash
python "$(context-hub skill-path build-graph | xargs dirname)/scripts/prepare_communities.py" \
   --root "$HUB" --min-size 5
```

For each L0 community with **≥5 nodes**, this writes
`$HUB/_index/agent-work/communities/Cx.md` (the community's top handles
+ members sorted by degree). Smaller communities are skipped — they
contribute too little signal to summarize.

---

## Stage 5 — Summarize each L0 community (N Sonnet agents)

Look at the directory to see how many `Cx.md` files were produced
(typically 15-25). **Dispatch one Sonnet agent per file in parallel.**

Per-agent prompt template (substitute `Cx`):

> You are summarizing one cluster of personal notes that Louvain
> community detection grouped together — they share rare handles in the
> thought-network graph.
>
> Read `$HUB/_index/agent-work/communities/Cx.md`.
>
> Identify the unifying theme and write
> `$HUB/_index/agent-work/communities/Cx.yaml`:
> ```yaml
> id: Cx
> title: <4-12 Chinese chars — the cluster's identity>
> summary: <1-2 sentences describing what binds these notes>
> handles:
>   - <4-8 canonical handles, picked from the top-handles list, names
>     exactly as shown>
> ```
> Be specific and grounded — don't generalize past what notes discuss.
> The title is the most important — it becomes the cluster's name
> everywhere downstream.

Aggregate when all are done:

```bash
python "$(context-hub skill-path build-graph | xargs dirname)/scripts/aggregate_summaries.py" \
   --root "$HUB"
```

Writes `$HUB/_index/community_summaries.yaml`.

---

## Stage 6a — Build the level-1 graph (programmatic)

```bash
python "$(context-hub skill-path build-graph | xargs dirname)/scripts/build_l1.py" \
   --root "$HUB"
```

Treats each L0 summary as a node, builds edges from shared handles
(re-using `idf`), runs Louvain. Writes
`$HUB/_index/agent-work/level1_grouping.yaml` listing which L0
communities go into each L1 super-community.

**The script also writes one `L1_Cx.md` input file per L1 super-community.**

If the script's output reports **< 10 super-communities**, this is the
top level — Stage 6b will produce the final summaries. If ≥10, the skill
should be extended for a deeper recursion (not implemented in v1).

---

## Stage 6b — Summarize each L1 super-community (M Sonnet agents)

Dispatch one Sonnet agent per `L1_Cx.md`. Singleton supers (only one
child) still get an agent — it should lift the child's content as the
top-level summary.

Per-agent prompt template (substitute `Cx`):

> You are summarizing a LEVEL-1 super-community — a cluster of clusters.
> Its children are L0 communities, each already with title, summary, and
> handles. Find the unifying super-theme.
>
> Read `$HUB/_index/agent-work/communities/L1_Cx.md`.
>
> Write `$HUB/_index/agent-work/communities/L1_Cx.yaml`:
> ```yaml
> id: L1:Cx
> title: <4-12 Chinese chars — the super-cluster's identity>
> summary: <1-2 sentences describing the through-line>
> handles:
>   - <4-8 canonical handles, picked from the recurring-handles list>
> ```
> Be specific. Don't just concatenate child titles — find the underlying
> theme.

Aggregate the final hierarchy + re-render:

```bash
python "$(context-hub skill-path build-graph | xargs dirname)/scripts/aggregate_hierarchy.py" \
   --root "$HUB"
context-hub visualize --root "$HUB"
```

This writes `$HUB/_index/community_hierarchy.yaml` (the canonical
2-level structure) and refreshes `$HUB/_index/graph.html` with the
hierarchy embedded in the legend.

---

## Done

The user can now open `$HUB/_index/graph.html`:

- **顶层** toggle shows ~6 L1 super-communities as a clean colored map.
- **主题层级** toggle shows L1 → L0 in the sidebar; click any row → right
  panel shows that community's title, summary, top handles, and either
  child L0 communities (for L1 rows) or core member notes (for L0 rows).
- Clicking through eventually opens any individual note's detail.

---

## Anti-patterns

- **Don't dispatch the curator and labelers in parallel.** Stage 1 must
  finish before Stage 2 can start (labelers need the vocabulary).
- **Don't skip Stage 0.** Without the deterministic graph, there's no
  candidate handle pool for Stage 1 to curate from.
- **Don't run Stage 5 over tiny communities.** The `--min-size 5` cutoff
  exists to keep summarizer agents from working on degenerate cliques
  (a 1-node "community" can't be meaningfully summarized).
- **Don't drop `agent_handles.yaml` thinking it's a cache.** It's the
  Stage 2 output the entire L0 → L1 pipeline depends on. If you delete
  it and re-run `context-hub graph`, the pipeline silently falls back to
  the bigram path and the downstream summaries become stale.

## Files this skill produces

```
$HUB/_index/
├── graph.json                    # the full graph (every note as a node)
├── graph.html                    # the self-contained viewer
├── agent_handles.yaml            # path → [handles]  (Stage 2 output)
├── community_summaries.yaml      # 21+ L0 communities w/ title+summary
├── community_hierarchy.yaml      # 2-level tree (L1 super → L0 → notes)
└── agent-work/                   # full audit trail (kept for re-runs)
    ├── candidates.md
    ├── vocabulary.yaml
    ├── batch-XX.md
    ├── result-XX.yaml
    ├── communities/
    │   ├── Cx.md      Cx.yaml
    │   ├── L1_Cx.md   L1_Cx.yaml
    │   └── level1_grouping.yaml
```
