---
name: context-hub
description: Query a user's personal context hub — a directory of markdown notes imported from Flomo, Obsidian, and similar apps. Use this skill whenever the user asks about their own past notes, journal entries, prior thinking on a topic, what they wrote about something, when they last considered an idea, or wants to be reminded of related past writing. Also trigger when the user references concepts that are likely in their personal corpus (their projects, research topics, ongoing reflections) rather than general knowledge.
---

# Context Hub Skill

The hub root is a directory the user has imported their personal notes into
(via `context-hub import`). Path comes from `$CONTEXT_HUB_ROOT` if set, or the
user tells you. Typical default: `~/context-hub`.

## What's in the hub

```
<hub_root>/
├── <YYYY>/<MM>/<DD>/<HHMM>-<id>.md   ← the original notes
│                                       YAML frontmatter (source, id, created_at,
│                                       tags) + body. SOURCE OF TRUTH — always
│                                       cite from these.
└── _index/                            ← derived artifacts, regenerable
    ├── tags.json                      ← inverted map: user tag → [paths]
    ├── recents.json                   ← newest 100 notes with preview
    ├── agent_handles.yaml             ← path → [handles] (per-note concept labels)
    ├── community_summaries.yaml       ← L0 communities with title + summary
    ├── community_hierarchy.yaml       ← 2-level tree: 6 super → ~21 L0 → notes
    ├── graph.json                     ← full thought-network (every note as a node)
    └── graph.html                     ← interactive viewer (open in browser)
```

## Three ways to find a note

The hub has three coexisting retrieval indices, each with different recall
and precision profiles. **For any topic query, walk all three and union the
resulting paths** — they overlap heavily but each catches notes the others
miss.

### 1. User-curated tag tree (`tags.json`)

The user's own `#tags` in frontmatter / inline. Hand-written, idiosyncratic.
**High precision** where the user tagged deliberately, but many notes are
untagged or one-off-tagged → **recall is patchy**.

```bash
jq '.tags | keys[]' $HUB/_index/tags.json          # all tags
jq -r '.tags["哲学"][]' $HUB/_index/tags.json       # all paths under one tag
```

### 2. Agent handle index (`agent_handles.yaml`) — *use this most*

Built by the `build-graph` skill. Every note was read by an agent and
tagged with 3-6 **canonical concept handles** drawn from a curated
vocabulary of ~500 strings (e.g. `工具理性`, `第二大脑`, `RAG`,
`完美主义`, `观点演进`, `卡片笔记`). This is the densest, most reliable
topic index in the hub:

- **Recall is high**: every connected note has handles (3.6 avg), so
  most concepts touched in a note are findable, not just the ones the
  user remembered to tag.
- **Precision is high**: the vocabulary was curated to drop vague words
  ("思考", "重要"); each handle is a real distinguishable concept.
- **Granularity is per-note**, not per-community — a note touching
  multiple concepts shows up under each.

Schema: `assignments: {<rel_path>: [<handle>, ...]}`. Two important moves:

```bash
# (a) From concept name → notes: invert and look up
python3 -c "
import yaml; d = yaml.safe_load(open('$HUB/_index/agent_handles.yaml'))
inv = {}
for path, hs in d['assignments'].items():
    for h in hs: inv.setdefault(h, []).append(path)
for p in inv.get('工具理性', []): print(p)
"

# (b) Discover what handles even exist (the controlled vocabulary)
yq '.assignments[] | .[]' $HUB/_index/agent_handles.yaml | sort -u

# (c) For a known note path → its handles
yq --arg p "2024/03/13/0011-..." \
   '.assignments[$p][]?' $HUB/_index/agent_handles.yaml
```

**When to prefer this over user tags**: anytime the topic isn't an
exact match for a `#tag` the user used. Most topics are.

**Caveat**: if a concept isn't in the curated vocabulary (~500 handles
total), it won't appear here — fall back to grep for those.

### 3. Agent-built community hierarchy (`community_hierarchy.yaml`)

Built by the `build-graph` skill from the actual graph structure (notes
connected by shared rare handles → Louvain → 2 levels). Covers
**every connected note exactly once** at each level. Each community has a
**title** and an **agent-written summary** describing the binding theme.

Best for **"what are the main themes?"** type questions and for finding
notes by a **broad topic area** (the L1 super-community summary level).

Structure:
```yaml
levels:
  - level: 1            # top: a small number of super-communities
    nodes:
      - id: L1:C0
        title: <agent-written 4-12 char Chinese title>
        summary: <agent-written 1-2 sentences>
        handles: [<canonical concept>, <canonical concept>, ...]
        children: [C1, C3, C5, ...]
        note_count: 527
  - level: 0            # L0: typically ~15-25 communities
    nodes:
      - id: C1
        title: <agent-written>
        summary: <agent-written>
        handles: [<canonical concept>, <canonical concept>, ...]
        member_notes: [<rel_path>, <rel_path>, ...]
        size: 157
        parent: L1:C0
```

To find notes by **community topic**, walk this tree top-down: find the L1
super whose title/summary best matches the topic → look at its L0 children →
pick the L0 whose title matches → read its `member_notes`.

```bash
# all L1 super-communities with their titles
yq '.levels[0].nodes[] | .id + " «" + .title + "» (" + (.note_count|tostring) + " notes)"' \
   $HUB/_index/community_hierarchy.yaml

# all L0 communities under a given super
yq '.levels[1].nodes[] | select(.parent == "L1:C0") |
    .id + " «" + .title + "» (" + (.size|tostring) + " notes)"' \
   $HUB/_index/community_hierarchy.yaml

# member note paths for a given L0 community
yq '.levels[1].nodes[] | select(.id == "C1") | .member_notes[]' \
   $HUB/_index/community_hierarchy.yaml
```

(`yq` may not be installed; equivalent Python one-liners work too:
`python -c "import yaml,sys; print('\n'.join(...))"`.)

## Decision flow

1. **"What did I write recently?"** →
   ```bash
   jq '.entries[:20]' $HUB/_index/recents.json
   ```

2. **"What did I say about `<topic>`?"** — do **all four** and union:
   - **Agent handles** (the densest index — start here):
     - Look at the vocabulary first: list distinct handles, pick those
       that name the topic. The vocabulary is finite (~500), so a quick
       scan finds the matching concept handles.
     - Invert `agent_handles.yaml` to get `handle → [paths]` and look
       up paths for each matched handle.
     - Handles like `工具理性`, `完美主义`, `第二大脑`, `RAG` are
       canonical — a single handle covers a topic robustly.
   - **User tags**: `jq '.tags | keys[]' $HUB/_index/tags.json`, find every
     tag whose name relates to the topic; collect paths via
     `jq -r '.tags["<tag>"][]'`. Catches deliberate user tagging.
   - **Hierarchy**: walk `community_hierarchy.yaml`. Find L1 supers and L0
     communities whose **title** or **summary** references the topic.
     Collect their `member_notes` (for L0) or recurse into children (for L1).
     Useful when the topic is broad rather than a single concept.
   - **Grep**: the user mixes Chinese and English freely. Try both forms.
     `grep -rlni --include='*.md' --exclude-dir='_index' "<query>" $HUB/`
     Catches anything the curated indices miss (concepts not in the
     handle vocabulary, untagged notes, partial spellings).
   - **Union + dedup** paths from all four, then read the actual `.md`
     files. Each source catches notes the others miss — the union is
     the answer, not whichever ran first.

3. **"Show me my notes from `<date>`"** → walk `$HUB/<YYYY>/<MM>/<DD>/`.

4. **"What are the main themes of my hub?"** → list the L1 super-communities:
   ```bash
   yq '.levels[0].nodes[] |
       .id + " «" + .title + "» — " + .summary' \
      $HUB/_index/community_hierarchy.yaml
   ```

5. **Drilling into a community the user named** ("看看我 `自律` 类的笔记") →
   match by L0 title in `community_hierarchy.yaml` → read `member_notes`.

6. **Before quoting any content**, read the actual `.md` file (not just the
   preview in `recents.json`). Cite by hub-relative path.

## Agent contract — summaries are agent-written, not user-written

`title` and `summary` fields in `community_summaries.yaml` and
`community_hierarchy.yaml` are written by an agent reading a sample of
the community's notes. **They describe what the agent thinks the cluster
is about; they are NOT the user's words.**

You may safely show these summaries to the user as "the hub's auto-built
overview", but when the user asks "what did I think about X", **drill
down to the actual `.md` files and quote from those** — never quote the
summary as the user's voice.

## Useful one-liners

```bash
# top-N recent notes with their content preview
jq '.entries[:10]' $HUB/_index/recents.json

# all canonical handles in the vocabulary (dedup, sorted)
python3 -c "
import yaml
d = yaml.safe_load(open('$HUB/_index/agent_handles.yaml'))
hs = set(h for v in d['assignments'].values() for h in v)
print('\n'.join(sorted(hs)))
"

# invert agent_handles: handle → [paths], lookup one concept
python3 -c "
import yaml
d = yaml.safe_load(open('$HUB/_index/agent_handles.yaml'))
inv = {}
for p, hs in d['assignments'].items():
    for h in hs: inv.setdefault(h, []).append(p)
for p in inv.get('工具理性', []): print(p)
"

# all L1 super-communities
yq '.levels[0].nodes[] | .id + " «" + .title + "»"' \
   $HUB/_index/community_hierarchy.yaml

# every L0 community grouped under its L1 super
yq '.levels[0].nodes[] |
    .id + " «" + .title + "»: " +
    (.children | map(.) | join(", "))' \
   $HUB/_index/community_hierarchy.yaml

# which community is this specific note in?
yq --arg p "<rel_path>" \
   '.levels[1].nodes[] | select(.member_notes[]? == $p) | .id + " " + .title' \
   $HUB/_index/community_hierarchy.yaml

# substring grep across note bodies
grep -rni --include='*.md' --exclude-dir='_index' "完美主义" $HUB/
```

## Refreshing

- **After importing new notes**: `context-hub import flomo|obsidian` runs
  `reindex` automatically — `tags.json` and `recents.json` stay fresh.
- **After accumulating substantial new content**: the user (or you, on
  their request) should invoke the `build-graph` skill to rebuild
  `agent_handles.yaml`, `community_summaries.yaml`,
  `community_hierarchy.yaml`, `graph.json`, and `graph.html`.

The `.md` source files are never modified by either pipeline.

## Anti-patterns

- **Quoting summaries as the user's voice.** Summaries are agent
  inferences over each community. Always drill to the original `.md`
  files for actual quotes.
- **Trusting `recents.json` previews as authoritative.** The 60-80 char
  preview is for navigation only. Read the full `.md` before citing.
- **Stopping after one retrieval path.** Agent handles + user tags +
  community hierarchy + grep cross-cut the corpus; each captures notes
  the others miss. For any topic query, always union the four. In
  particular, **don't skip `agent_handles.yaml`** — it's the densest
  topic index (every connected note has 3-6 canonical handles) and
  typically gives the highest recall for any specific concept.
- **Treating `agent_handles.yaml` as a substring matcher.** Handles are
  exact canonical strings drawn from a finite vocabulary. If your
  topic isn't in the vocabulary you must fall back to grep — the
  inversion lookup does *not* do partial matching for you.
- **Treating the hub as searchable English text.** The user writes in
  Chinese + English mixed; expect both forms when searching.
- **Walking `graph.json` for retrieval.** It's the per-node graph
  (1500+ entries). Use it only for "show me this note's neighbors" or
  "what cluster is X in" — for topic queries, use the hierarchy file.
