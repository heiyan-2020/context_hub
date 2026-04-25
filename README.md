# Context Hub

A middle layer that pulls personal text from silos (Flomo first) into a uniform markdown tree for any agent to read.

The hub is agent-agnostic: its only output is a directory of markdown files with YAML frontmatter. Agents read the directory directly — no server, no API, no database.

See `docs/superpowers/specs/2026-04-25-context-hub-design.md` for the design.

## Install

```
pip install -e .
```

## Usage

```
context-hub import flomo path/to/flomo-export.zip --root ~/context-hub
context-hub import flomo path/to/flomo-export.zip --root ~/context-hub --dry-run
```

After running, `~/context-hub/` contains:

```
2026/
└── 04/
    └── 25/
        └── 0931-<memo_id>.md
```

Each `.md` is one memo with `source: flomo` frontmatter. Re-running with the same or a different export is idempotent and full-mirror — files for memos that no longer exist in the export are deleted.

Files in the hub root that lack `source: flomo` frontmatter are never touched.

## Constraints

- One source: Flomo (HTML export zip)
- Text only: images skipped, audio transcripts preserved as text
- Single user, single machine, no concurrent imports
