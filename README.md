# Context Hub

Pull your personal notes out of app silos (Flomo, Obsidian, …) into one
uniform markdown tree, build an **agent-judged hierarchical graph** over
it, and let **any agent** query it through a bundled skill.

Context Hub is a *substrate*, not a service: its whole output is a
directory of markdown files plus a small `_index/` of derived artifacts.
No server, no database, no API. Agents read the directory directly — or
through the bundled query skill.

```
notes apps          context-hub                 your agent
┌─────────┐  import  ┌──────────────────┐  skill  ┌──────────────┐
│ Flomo   │ ───────▶ │ <hub>/YYYY/.../  │ ──────▶ │ Claude Code, │
│ Obsidian│          │ <hub>/_index/    │  reads  │ Copilot, …   │
└─────────┘  reindex └──────────────────┘         └──────────────┘
                          ▲
                          │  build-graph skill
                          │  (deterministic + agent-judged pipeline)
                          ▼
                 ┌──────────────────┐
                 │ thought-network  │
                 │ + 2-level theme  │
                 │ hierarchy + HTML │
                 └──────────────────┘
```

## What it does — three capabilities

| Capability | Command / mechanism |
|---|---|
| **Extract** notes from apps into one markdown tree | `context-hub import flomo\|obsidian` |
| **Build** a hierarchical thought-network from the notes | `context-hub graph` + the `build-graph` skill |
| **Query** the hub from an agent | the `context-hub` skill (auto-triggers in Claude Code) |

The Python package does the *deterministic* work — note ingestion, the
bigram → IDF → Louvain → layout pipeline, HTML rendering. The
*intelligent* work — curating a concept-handle vocabulary, labeling
every note with handles, summarising communities, building the L1
super-summary — is delegated to subagents orchestrated by the
`build-graph` skill.

## Install

```bash
pip install git+https://github.com/USERNAME/context-hub
```

<sub>(Replace `USERNAME` once the repo is published. Requires Python ≥ 3.10.)</sub>

## Quick start

```bash
# 1. Extract — point at your app's export
context-hub import flomo    ~/Downloads/flomo-export.zip  --root ~/context-hub
context-hub import obsidian ~/vaults/main                 --root ~/context-hub

# 2. Build the graph
#    First a deterministic baseline (bigram handles); the build-graph skill
#    will then upgrade this with agent-judged handles + community summaries.
context-hub graph --root ~/context-hub

# 3. Install the skills where Claude Code finds them
context-hub install-skill                    # installs both bundled skills
export CONTEXT_HUB_ROOT=~/context-hub        # add to ~/.bashrc / ~/.zshrc

# 4. (In a fresh Claude Code session) invoke the build pipeline
#    "build the thought-network for my hub"  → the build-graph skill runs:
#        - one curator agent picks the vocabulary
#        - N parallel labelers tag every note
#        - per-community summarizers
#        - level-1 super-community summarizers
#    Produces _index/graph.{json,html} + community_hierarchy.yaml.

# 5. Query (in the same or any later Claude Code session)
#    "what did I write about <topic>?"  → the context-hub skill auto-triggers
#    Open _index/graph.html in a browser for the interactive viewer.
```

`import` is **idempotent and full-mirror, scoped per source**: re-running
it makes the hub match that source's export exactly (adds / updates /
moves / deletes), and never touches files from other sources or your own
files.

## What lives in the hub

```
~/context-hub/
├── 2026/05/14/1402-<id>.md          # one file per note (time-keyed path)
│                                    # YAML frontmatter: source, id,
│                                    # created_at, tags
└── _index/                          # derived, regenerable
    ├── tags.json                    # inverted: user-#tag → [paths]
    ├── recents.json                 # newest 100 notes with preview
    ├── graph.json                   # full thought-network (every note as node)
    ├── graph.html                   # self-contained interactive viewer
    ├── agent_handles.yaml           # path → [canonical concept handles]
    ├── community_summaries.yaml     # L0 communities with title + summary
    ├── community_hierarchy.yaml     # 2-level tree: ~6 super → ~21 L0 → notes
    └── agent-work/                  # build-graph skill's audit trail
        ├── candidates.md            # Stage 1 input
        ├── vocabulary.yaml          # Stage 1 output (curated by 1 agent)
        ├── batch-XX.md              # Stage 2 input
        ├── result-XX.yaml           # Stage 2 output (N parallel labelers)
        ├── communities/Cx.md|.yaml  # Stage 4/5 per-L0
        ├── communities/L1_Cx.md|.yaml  # Stage 6 per-L1
        └── level1_grouping.yaml     # Stage 6a Louvain on summaries
```

## Sources

### Flomo

Input: the HTML export zip Flomo provides. Each memo → one file with
frontmatter `source: flomo`, `memo_id`, `created_at`, `tags`. Body is the
memo's HTML converted to markdown; audio transcripts are kept as
`[audio transcript]` paragraphs; images are dropped.

### Obsidian

Input: a vault directory. Each `.md` → one hub file with frontmatter
`source: obsidian`, `note_id`, `created_at`, `tags`, `title`,
`vault_path`. The note's own frontmatter is parsed for creation time
and tags; inline `#tags` in the body are also extracted. Hidden dirs
(`.obsidian/`, `.trash/`) are skipped.

Adding a source = adding one importer module — the hub format is stable.

## The two skills

Both ship inside the package and install with `context-hub install-skill`:

- **`context-hub`** — the *query* skill. Auto-triggers when an agent
  notices the user is asking about their own past notes. Teaches the
  agent the `_index/` layout and three retrieval paths:
  `agent_handles.yaml` (densest), `tags.json` (user-curated),
  `community_hierarchy.yaml` (topic-level), plus grep as fallback.
  Always reads the original `.md` for any quote.

- **`build-graph`** — the *pipeline* skill. Orchestrates the 6-stage
  build:

  | Stage | Mechanism | Output |
  |---|---|---|
  | 0. Deterministic graph | `context-hub graph` | `graph.json` (bigram handles) |
  | 1. Curate vocabulary | 1 Opus agent reads candidates | `vocabulary.yaml` (~500 handles) |
  | 2. Label notes | N parallel Sonnet agents | `result-XX.yaml` → `agent_handles.yaml` |
  | 3. Rebuild with agent handles | `context-hub graph` | `graph.json` (agent path, Louvain L0) |
  | 4. Prep per-community inputs | `prepare_communities.py` | `communities/Cx.md` |
  | 5. Summarise each L0 community | N parallel Sonnet agents | `communities/Cx.yaml` → `community_summaries.yaml` |
  | 6a. Build level-1 graph | `build_l1.py` (Louvain on summaries) | `level1_grouping.yaml` |
  | 6b. Summarise super-communities | M parallel Sonnet agents | `communities/L1_Cx.yaml` → `community_hierarchy.yaml` |

  No embeddings, no external retrieval model — the agents do the
  judgment, the package does the math.

```bash
context-hub install-skill                     # installs both
context-hub install-skill --skill context-hub # just the query skill
context-hub skill-path build-graph            # print the packaged SKILL.md path
```

## CLI reference

```
context-hub import <flomo|obsidian> <path> [--root DIR] [--dry-run] [--no-index]
context-hub reindex [--root DIR]
context-hub graph [--root DIR]
context-hub visualize [--root DIR] [--input JSON] [--output HTML]
context-hub install-skill [--skill context-hub|build-graph|all] [--target DIR] [--force]
context-hub skill-path [context-hub|build-graph]
```

## Constraints

- **Text only** — images and other attachments are skipped (audio
  transcripts kept as text).
- **Single user, single machine** — no concurrent imports against one hub.
- **Agentic-CLI only** — agent integration via skill format (Claude Code,
  Copilot CLI, Gemini CLI, Codex). Chat-app integration (Claude Desktop,
  ChatGPT desktop) is not currently in scope.
- **Build pipeline cost** — running the full `build-graph` skill on a
  ~2000-note hub takes ~50 subagent calls (1 Opus + 14 Sonnet labelers +
  ~30 Sonnet summarizers) and ~500-800k tokens.

## License

MIT — see [LICENSE](LICENSE).
