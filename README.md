# Context Hub

A middle layer that pulls personal text from silos (Flomo, Obsidian) into a uniform markdown tree for any agent to read.

The hub is agent-agnostic: its only output is a directory of markdown files with YAML frontmatter. Agents read the directory directly — no server, no API, no database.

See `docs/superpowers/specs/2026-04-25-context-hub-design.md` for the design.

## Install

```
pip install -e .
```

## Usage

```
context-hub import flomo    path/to/flomo-export.zip --root ~/context-hub
context-hub import obsidian path/to/obsidian-vault   --root ~/context-hub
context-hub import flomo    path/to/flomo-export.zip --root ~/context-hub --dry-run
```

After running, `~/context-hub/` contains a time-keyed tree:

```
2026/
└── 04/
    └── 25/
        ├── 0931-<memo_id>.md      # source: flomo
        └── 0932-<note_id>.md      # source: obsidian
```

Each `.md` carries a `source:` frontmatter field. Re-running an import is idempotent and full-mirror **scoped to that source only**: files belonging to the imported source that no longer exist upstream are deleted; files from other sources (or with no recognized source frontmatter) are never touched.

### Sources

#### Flomo
Input: the HTML export zip Flomo provides. Each memo becomes one file with frontmatter `source: flomo`, `memo_id`, `created_at`, `tags`. Body is the memo's HTML converted to markdown; audio transcripts are appended as `[audio transcript]` paragraphs; images are dropped.

#### Obsidian
Input: the path to a vault directory. Each `.md` file becomes one hub file with frontmatter `source: obsidian`, `note_id`, `created_at`, `tags`, `title`, `vault_path`. The note's own frontmatter is parsed for `created_at`/`created`/`date`, and for `tags` (list or comma-separated string); inline `#tags` in the body are also extracted. If no creation time is found in frontmatter, the file's mtime is used. Hidden directories (`.obsidian/`, `.trash/`, anything starting with `.`) are skipped.

`note_id` is derived from the note's vault-relative path, so editing a note shows up as UPDATE while renaming shows up as DELETE + ADD.

## Constraints

- Text only: images and other attachments are skipped (audio transcripts kept as text)
- Single user, single machine, no concurrent imports
