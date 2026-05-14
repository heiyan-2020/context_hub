# Context Hub

Pull your personal notes out of app silos (Flomo, Obsidian, …) into one
uniform markdown tree, build an **agent-friendly index** over it, and let
**any agent** query it.

Context Hub is a *substrate*, not a service: its whole output is a directory
of markdown files plus a small `_index/` of derived artifacts. No server, no
database, no API. Agents read the directory directly — or through a bundled
skill.

```
notes apps          context-hub                 your agent
┌─────────┐  import  ┌──────────────────┐  skill  ┌──────────────┐
│ Flomo   │ ───────▶ │ <hub>/YYYY/.../  │ ──────▶ │ Claude Code, │
│ Obsidian│          │ <hub>/_index/    │  reads  │ Cursor, …    │
└─────────┘  reindex └──────────────────┘         └──────────────┘
```

## What it does — three capabilities

| Capability | Command / mechanism |
|---|---|
| **Extract** notes from apps into one markdown tree | `context-hub import flomo\|obsidian` |
| **Index** the tree into agent-friendly artifacts | `context-hub reindex` + the `cluster-context-hub` skill |
| **Ask** questions about your notes from an agent | the `context-hub` skill (auto-triggers in Claude Code) |

The package does the *deterministic* work (extract, index, serve). The
*intelligent* work (topic clustering, question answering) is delegated to
whatever agent you run, via two bundled skills.

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

# 2. Index — build the browsable / queryable artifacts
context-hub reindex --root ~/context-hub

# 3. Wire into your agent — copy the skills where Claude Code finds them
context-hub install-skill
export CONTEXT_HUB_ROOT=~/context-hub        # add to ~/.bashrc / ~/.zshrc

# 4. Ask — in a Claude Code session
#    "what did I write about <topic>?"  → the context-hub skill auto-triggers
```

`import` is **idempotent and full-mirror, scoped per source**: re-running it
makes the hub match that source's export exactly (adds / updates / moves /
deletes), and never touches files from other sources or your own files.

## What lives in the hub

```
~/context-hub/
├── 2026/05/14/1402-<id>.md      # one file per note, time-keyed path
│                                # YAML frontmatter: source, id, created_at, tags
└── _index/                      # derived, regenerable — never hand-source-of-truth
    ├── INDEX.md                 # hierarchical page index (human-browsable)
    ├── tree.json                # same tree, machine-readable, with routing scopes
    ├── tags.json                # inverted: tag → [paths]
    ├── recents.json             # newest 100 notes
    ├── scopes.yaml              # description + routing_scope per cluster (editable)
    └── synthetic_tags.yaml      # agent-clustered overlay: path → Auto/<topic>
```

`INDEX.md` carries **two parallel trees**: the tags you wrote yourself, and an
`Auto/` tree produced by the clustering skill. Every note appears in both.

## Sources

### Flomo
Input: the HTML export zip Flomo provides. Each memo → one file with
frontmatter `source: flomo`, `memo_id`, `created_at`, `tags`. Body is the
memo's HTML converted to markdown; audio transcripts are kept as
`[audio transcript]` paragraphs; images are dropped.

### Obsidian
Input: a vault directory. Each `.md` → one hub file with frontmatter
`source: obsidian`, `note_id`, `created_at`, `tags`, `title`, `vault_path`.
The note's own frontmatter is parsed for creation time and tags; inline
`#tags` in the body are also extracted. Hidden dirs (`.obsidian/`, `.trash/`)
are skipped.

Adding a source = adding one importer module — the hub format is stable.

## The two skills

Both ship inside the package and install with `context-hub install-skill`:

- **`context-hub`** — the *query* skill. A single `SKILL.md` that teaches an
  agent the `_index/` layout, when to use the tag tree vs the `Auto/` tree,
  and the contract: `description` is safe to show the user, `routing_scope`
  is agent-only navigation. Auto-triggers when you ask about your past notes.

- **`cluster-context-hub`** — the *clustering* skill. A 5-phase pipeline where
  the agent reads a stratified sample, defines ~14 mutually-exclusive topic
  categories, dispatches one sub-agent per batch to classify every note, then
  recursively sub-clusters anything oversized. The output is
  `_index/synthetic_tags.yaml` + the `Auto/` scopes. This is the
  operationalization of *"the agent itself is the clustering algorithm"* — no
  embeddings, no external model.

```bash
context-hub install-skill                       # installs both
context-hub install-skill --skill context-hub   # just the query skill
context-hub skill-path                          # print the packaged SKILL.md path
```

## CLI reference

```
context-hub import <flomo|obsidian> <path> [--root DIR] [--dry-run] [--no-index]
context-hub reindex [--root DIR]
context-hub install-skill [--skill context-hub|cluster-context-hub|all] [--target DIR] [--force]
context-hub skill-path [context-hub|cluster-context-hub]
```

## Constraints / not done yet

- **Text only** — images and other attachments are skipped (audio transcripts
  kept as text).
- **Single user, single machine** — no concurrent imports against one hub.
- **No semantic search yet** — recall is tag + grep + the `Auto/` tree.
  Embedding-based retrieval is a planned `_index/` artifact, not built.
- **No MCP server yet** — agent integration is via the Claude-Code skill
  format. A `context-hub mcp` server for cross-agent (Cursor, Claude Desktop)
  use is the next planned step.

## Design

See `docs/superpowers/specs/2026-04-25-context-hub-design.md` for the original
MVP design and architectural commitments.

## License

MIT — see [LICENSE](LICENSE).
