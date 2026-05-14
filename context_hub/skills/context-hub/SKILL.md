---
name: context-hub
description: Query a user's personal context hub — a directory of markdown notes
  imported from Flomo, Obsidian, and similar apps. Use this skill whenever the
  user asks about their own past notes, journal entries, prior thinking on a
  topic, what they wrote about something, when they last considered an idea,
  or wants to be reminded of related past writing. Also trigger when the user
  references concepts that are likely in their personal corpus (their projects,
  research topics, ongoing reflections) rather than general knowledge.
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
    ├── INDEX.md                       ← hierarchical page index (human-readable)
    ├── tree.json                      ← same tree as machine-readable JSON,
    │                                    with description + routing_scope per node
    ├── tags.json                      ← inverted map: tag → [paths]
    ├── recents.json                   ← newest 100 notes with frontmatter + preview
    ├── scopes.yaml                    ← source of description / routing_scope
    └── synthetic_tags.yaml            ← agent-clustered overlay: path → Auto/<top>[/<sub>]
```

## Two parallel trees in INDEX.md

The hub has **two coexisting hierarchies**, each note appears in BOTH:

1. **User-curated tag tree** (top of INDEX.md) — built from the user's own
   frontmatter and inline `#tags`. Hand-written, idiosyncratic, ~290 distinct
   tags. Top examples: `思考` (~360), `长线记录/观点演进` (~184),
   `反思` (~280), `科研/读博心态` (~70), `引用` (~210), etc.

2. **Agent-clustered tree** (`Auto/<top>[/<sub>]`, bottom of INDEX.md) — built
   by Claude reading representative samples and assigning every note to one
   path. 18 top-level + ~36 sub-level clusters, every cluster ≤ 5% of corpus.
   Examples: `Auto/自我反思与内省/摆烂沉迷拖延`, `Auto/科研·读博·导师/读博心态·Quit`,
   `Auto/学习方法与工作流/笔记工具与第二大脑`.

Use the user-tag tree when the user uses **their own vocabulary** (`#引用`,
`#长线记录`). Use the Auto tree when the user asks by **topic** (e.g.,
"我以前关于完美主义的想法") and the topic doesn't map cleanly to a hand tag.

## Agent contract — load-bearing

Each node in `tree.json` has two text fields with **different contracts**:

| field | safe to display to user? | use for |
|---|---|---|
| `description` | YES | tell the user what a bucket is broadly about |
| `routing_scope` | **NO — agent-only** | decide which paths to read; never quote to user |

`routing_scope` may contain phrases like "用户倾向 X" or "用户认为 Y". **These
are inferences from the shape of the bucket, not the user's words.** You MUST
NOT quote `routing_scope` text back to the user as if it were their views.

When the user asks "what did I think about X?", use `routing_scope` to navigate
to the right paths, **then read the original `.md` files** and quote from those.

## Decision flow

1. **"What did I write recently?"** → `jq '.entries[:20]' <hub>/_index/recents.json`.

2. **"What did I say about <topic>?"** — try in order:
   - Direct tag match: `jq '.tags | keys[]' <hub>/_index/tags.json` then look
     for a tag containing the topic. If hit, `jq -r '.tags["<tag>"][]' <hub>/_index/tags.json`.
   - Auto-cluster match: walk `tree.json` Auto subtree; each node has
     `description` + `routing_scope` + `direct_paths`. Find the closest
     cluster name or descriptor. Drill into `direct_paths`.
   - Grep fallback: the user mixes Chinese and English freely; try both forms.
     `grep -rni --include='*.md' --exclude-dir='_index' "<query>" <hub>/`

3. **"Show me my notes from <date>"** → walk `<hub>/<YYYY>/<MM>/<DD>/`.

4. **Drilling into a cluster the user mentioned by name** ("看看我 `自律命令`
   类的笔记") → walk `tree.json` to find the matching node, then read its
   `direct_paths`. For Auto sub-clusters, the node lives at depth 3 in
   `tree.json` (Auto → top → sub).

5. **Before quoting any content**, read the actual file (not just preview).
   Cite by hub-relative path.

## Useful recipes

```bash
# Top-N recent entries (full frontmatter + preview)
jq '.entries[:10]' $HUB/_index/recents.json

# All notes under a specific user tag
jq -r '.tags["科研/读博心态"][]' $HUB/_index/tags.json

# All notes under an Auto cluster (works for top + sub)
jq -r --arg cat "Auto/自我反思与内省/完美主义瘫痪" \
   '.assignments | to_entries[] | select(.value == $cat) | .key' \
   $HUB/_index/synthetic_tags.yaml | python -c "import sys,yaml; \
       print('\n'.join(yaml.safe_load(open('/dev/stdin')).get('assignments',{}).keys()))"
# (simpler form using yq if installed: yq '.assignments | to_entries[] | select(.value == "Auto/..." )')

# Browse all top-level Auto clusters with descriptions
jq -r '.tree.children[] | select(.name == "Auto") | .children[] |
       "\(.name) (\(.count)) — \(.description // "")"' $HUB/_index/tree.json

# Browse Auto sub-clusters of a particular top
jq -r '.. | objects | select(.path == "Auto/自我反思与内省") | .children[] |
       "  \(.name) (\(.count)) — \(.description // "")"' $HUB/_index/tree.json

# Substring grep across all note bodies
grep -rni --include='*.md' --exclude-dir='_index' "完美主义" $HUB/
```

## Refreshing the index

If the user wants to refresh derived artifacts after editing notes or
`synthetic_tags.yaml`:

```bash
context-hub reindex --root <hub_root>
```

The `.md` source files are never touched.

## Re-clustering with the cluster-context-hub skill

If the user wants a fresh agent-driven re-clustering (different category
choices, new sub-splits, etc.), the companion skill `cluster-context-hub` runs
the full 5-phase pipeline. This is the SOURCE of `synthetic_tags.yaml` and
the `Auto/*` scopes — the **query** skill (this file) just reads what that
skill produced.

## Anti-patterns

- **Quoting `routing_scope` to the user as if it's their words.** It's not.
  It's the agent's inference about the bucket. Always drill to original `.md`
  files for actual quotes.
- **Trusting INDEX.md previews as authoritative.** The 60-80 char preview is
  for navigation only. Read the full file before citing.
- **Skipping the user-tag tree.** If the user uses a specific tag, that tag
  is usually a sharper filter than any Auto cluster.
- **Treating the hub as searchable English text.** The user writes in Chinese
  + English mixed; expect both forms when searching.
