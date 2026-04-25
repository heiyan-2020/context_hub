# Context Hub — MVP Design

**Status**: draft
**Date**: 2026-04-25
**Scope**: Single-source MVP (Flomo only), CLI tool, manual import.

---

## 1. Vision & Scope

### Vision

Personal agents need personal context — text the user writes about themselves: notes, journals, fleeting thoughts. Today this content is scattered across Notion, Flomo, Obsidian, etc., and any single agent has to integrate with each silo separately.

**Context Hub is a middle layer** that pulls personal text from those silos, organizes it into a uniform on-disk structure, and exposes it to any number of agents through the simplest possible contract: a directory tree of markdown files. The hub itself knows nothing about agents — it is a substrate.

### Architectural commitments (decided during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Layering | Hub is agent-agnostic substrate | Agents own their use cases; hub owns ingest + organize |
| Read interface | **Filesystem only** | Markdown tree on disk, no server, no API, no DB |
| Output organization | Time-based primary structure + rich frontmatter | Time is the most natural axis for personal data; frontmatter lets agents reslice without depending on directory shape |
| File granularity | One file per memo | Atomic, traceable, editable independently |
| First source | **Flomo** (only, for MVP) | Simple short-form data; user's primary recording tool |
| Sync model | Manual CLI import of Flomo's full export zip | Hub is a script, not a service; user controls when to sync |
| Re-import semantics | **Full mirror** (idempotent overwrite + delete) | After import, hub matches the export zip's state exactly |
| State storage | Stateless — output tree is source of truth | No sidecar DB; diff is computed by walking the tree |
| Source extensibility | **Single-source coupled MVP** | Defer plugin abstraction until source #2; MVP is a learning vehicle |
| Language | Python | Best fit for personal data scripting; user environment |

### Out of scope for this MVP

- Sources other than Flomo (Notion, Obsidian, etc.) — will be added in a later spec, requiring a refactor
- Real-time / webhook ingestion — manual zip import only
- Search, semantic indexing, vector store — agents do this themselves on top of the file tree
- MCP server, REST API, any kind of query layer
- Concurrency / locking — single-user, single-machine, run one import at a time
- Cross-source dedup or entity resolution — single source means non-issue

---

## 2. Architecture

```
   ┌───────────────────┐         ┌──────────────┐         ┌──────────────────┐
   │ Flomo export zip  │  ──▶    │ context-hub  │  ──▶    │ Hub root dir     │
   │ (manual download) │  CLI    │     CLI      │  write  │ ~/context-hub/   │
   └───────────────────┘         └──────────────┘         └──────────────────┘
                                                                   │
                                                                   ▼
                                                          Any agent / tool
                                                          reads as plain files
```

### Core invariants

1. **The output directory is the source of truth.** Hub maintains no sidecar state.
2. **`import` is idempotent and full-mirror.** After a successful run, hub-managed files in the output tree exactly reflect the input zip (additions, updates, moves, deletions all applied).
3. **Hub never touches files it does not own.** Ownership is determined by frontmatter `source: flomo`. Files without that marker are ignored by both scan and apply.
4. **Agents do not need to know hub exists.** They are given the root path and read directly.

### Single CLI command

```
context-hub import flomo <path-to-zip> [--root ~/context-hub] [--dry-run]
```

Steps executed:

1. Unzip the export to a temp directory.
2. Parse all memos into in-memory `Memo` records.
3. Render each memo to `(relative_path, file_content_str)` — the **desired** state.
4. Walk the output root, parsing frontmatter, indexing files where `source: flomo` — the **current** state.
5. Compute the diff plan (`adds`, `updates`, `moves`, `deletes`).
6. If `--dry-run`, print the plan and exit. Otherwise apply, then clean up empty directories.
7. Print a one-line summary.

---

## 3. Project structure & components

```
context_hub/
├── pyproject.toml
├── README.md
├── context_hub/
│   ├── __init__.py
│   ├── cli.py            # argparse entry point + dispatch
│   ├── flomo.py          # Flomo zip → list[Memo]
│   ├── render.py         # Memo → (relative_path, content_str)
│   └── tree.py           # scan / diff / apply on the output root
└── tests/
    ├── fixtures/
    │   └── flomo-sample.zip
    └── test_*.py
```

### Module responsibilities

- **`flomo.py`** — Knows the Flomo export format (and only that format). Public surface: `parse_zip(path: Path) -> list[Memo]`. Returns dataclass instances; no I/O after the parse returns.
- **`render.py`** — Pure functions. `render(memo: Memo) -> tuple[Path, str]` produces the relative file path and the full file contents (frontmatter + body). Stable: identical input → byte-identical output.
- **`tree.py`** — Owns the output directory. Three functions: `scan(root) -> dict[memo_id, (path, content)]`, `diff(desired, current) -> Plan`, `apply(plan, root)`. Only considers files with frontmatter `source: flomo`.
- **`cli.py`** — Wires the three modules together. No business logic.

### `Memo` dataclass

```python
@dataclass(frozen=True)
class Memo:
    memo_id: str           # Flomo's stable id
    created_at: datetime   # local-tz aware
    updated_at: datetime   # local-tz aware
    content: str           # body, markdown
    tags: list[str]        # extracted hashtags / Flomo tags
```

---

## 4. Output layout

### Directory structure (under hub root)

```
~/context-hub/
└── 2026/
    └── 04/
        └── 25/
            ├── 0931-MTcwOTI3MzgxNw.md
            ├── 1402-MTcwOTM5NDIyMQ.md
            └── 2218-MTcwOTQyNzgwMw.md
```

- Path template: `<YYYY>/<MM>/<DD>/<HHMM>-<memo_id>.md`
- All path components are zero-padded (e.g. `2026/04/05/0931-...`), so lexicographic sort matches chronological sort.
- `<HHMM>` prefix gives natural sort order in `ls`.
- `<memo_id>` guarantees uniqueness even within the same minute.
- Times are interpreted in the **system local timezone of the import machine** (read once per import). This matches how the user thinks of "what I wrote on April 25" and avoids cross-timezone churn.

### File format

```markdown
---
source: flomo
memo_id: MTcwOTI3MzgxNw
created_at: 2026-04-25T09:31:14+08:00
updated_at: 2026-04-25T09:31:14+08:00
tags: [想法, context-hub]
---

今天想到 context hub 的 frontmatter schema 可以...
```

Frontmatter is the only machine-readable contract between hub and agents. Body is the memo's original markdown.

### Coexistence with non-hub files

`tree.scan` only indexes files where frontmatter `source: flomo`. Anything else under the hub root — user's own notes, READMEs, future importers' output — is invisible to the diff and never touched by `apply`.

---

## 5. Data flow & diff algorithm

### Pipeline

```
zip path
   │
   ▼
[1] flomo.parse_zip(path) ─────────────▶ list[Memo]
   │
   ▼
[2] render-each(memos) ────────────────▶ desired: dict[memo_id → (rel_path, content_str)]
   │
   ▼
[3] tree.scan(root) ───────────────────▶ current: dict[memo_id → (abs_path, content_str)]
   │                                       (only files with `source: flomo`)
   ▼
[4] tree.diff(desired, current) ───────▶ Plan(adds, updates, moves, deletes)
   │
   ▼
[5] tree.apply(plan, root) ────────────▶ write/delete + summary
```

### Diff classification

Both maps are keyed by `memo_id`. For each id:

| In desired? | In current? | Content equal? | Path equal? | Action |
|---|---|---|---|---|
| ✓ | ✗ | — | — | **ADD** — write new file |
| ✓ | ✓ | yes | yes | **SKIP** — nothing to do |
| ✓ | ✓ | no | yes | **UPDATE** — overwrite |
| ✓ | ✓ | — | no | **MOVE** — delete old path, write new path |
| ✗ | ✓ | — | — | **DELETE** — remove file |

**Content comparison** is byte-equality on the full file string (frontmatter + body). Any frontmatter field change (e.g. `updated_at`, new tag) is therefore treated as UPDATE, with no special-casing.

**MOVE** happens when the user changes a memo's creation time in Flomo, shifting its target path.

### Apply order

1. Apply DELETEs and the "remove old path" half of MOVEs first (frees up paths).
2. Apply ADDs, UPDATEs, and the "write new path" half of MOVEs.
3. Recursively rmdir empty directories under the hub root (only directories that became empty, only if empty).

### Atomicity

MVP is **not transactional**. Files are written one at a time. If the process crashes mid-apply, the next run's diff will reconcile the partial state automatically. This is safe because the operation is idempotent and the output tree is the only state.

### CLI summary line

```
$ context-hub import flomo ~/Downloads/flomo-2026-04-25.zip
+12 added  ~3 updated  →2 moved  -1 deleted  =847 unchanged
```

`--dry-run` prints the plan in the same format and exits with code 0 without writing.

---

## 6. Error handling

Three boundaries, three strategies.

### Input boundary — fail fast, never write

- Zip path missing / unreadable → exit non-zero with clear message.
- Zip structure does not match Flomo export schema → exit non-zero.
- Individual memo malformed (missing date, corrupt body) → log a warning, **skip that memo**, continue. Final summary includes `! N skipped`.

### Output boundary — protect existing state

- Hub root does not exist → create it.
- Hub root not writable → run a write-probe (`.context_hub_probe`) **before** the apply phase. Abort if the probe fails. Never crash mid-apply due to permissions.
- IO error mid-apply (disk full etc.) → propagate the exception. Partial files on disk are fine; next run will reconcile.

### Files we don't own

- Missing frontmatter, malformed YAML, or `source != flomo` → silently skip during `scan`. Never read for diff, never affected by apply.

### Concurrency

Out of scope. Documentation should state: do not run two imports concurrently against the same hub root.

---

## 7. Testing

`pytest`, local-only, no CI for MVP.

### Unit tests

- **`test_flomo.py`** — Fixture zip with 3–5 memos covering: standard memo, memo with tags, memo with missing optional fields. Asserts the parsed `Memo` list.
- **`test_render.py`** — Table-driven over `Memo → (path, content)`. Asserts file naming, frontmatter serialization, and stability (same input → byte-identical output).
- **`test_tree_diff.py`** — Most important. Table-driven covering ADD, SKIP, UPDATE, MOVE, DELETE individually plus 1–2 mixed scenarios.
- **`test_tree_apply.py`** — Uses `tmp_path`. Writes a starting state, applies a plan, asserts final filesystem state. Includes assertion that empty parent directories get cleaned up.

### Integration test

- **`test_e2e.py`** — Run `parse → render → scan → diff → apply` against the fixture zip into an empty `tmp_path`. Snapshot-assert the resulting tree (file list + contents). Then mutate the fixture (modify one memo, delete one) and re-run; assert the tree mirrors the new state.

### Coverage target

- Diff logic: every branch covered.
- Each I/O boundary: a happy path + at least one error path.
- Everything else: YAGNI.

### Not doing

- No mocks for external services (none exist).
- No performance tests (MVP corpus is small).
- No concurrency tests (not supported).

---

## 8. Open questions / explicit deferrals

- Frontmatter schema may grow as future sources are added; MVP frontmatter is intentionally minimal and stable enough not to need migration when source #2 lands.
- Plugin architecture for multi-source support is deferred to the spec that introduces source #2 (likely Obsidian or Notion). At that point a refactor extracts an `Importer` interface; the current `flomo.py` becomes the first implementation.

---

## 9. Flomo export format reality (addendum after inspecting real zip)

A real Flomo export zip was inspected and the following amendments to the spec were necessary.

### Format

The export contains exactly one HTML index file (`<username>的笔记.html`) plus a `file/` tree of attachments. There is **no JSON or markdown index**. Each memo in the HTML is structured as:

```html
<div class="memo">
  <div class="time">YYYY-MM-DD HH:MM:SS</div>
  <div class="content">[HTML body with <p>, <ul>, <li>, inline #tags]</div>
  <div class="files">
    [optional <img>... and/or <div class="audio-player"><audio><div class="audio-player__content">transcript</div></div>]
  </div>
</div>
```

### Amendments to the spec

1. **No memo_id in source.** Flomo's HTML export does not expose a stable id. memo_id is **derived as `sha1(created_at_iso + "\n" + raw_content_html)[:16]`**. Consequence: editing a memo in Flomo and re-exporting produces a different id — the import treats this as DELETE old + ADD new. This is consistent with full-mirror semantics.

2. **No updated_at in source.** The HTML only carries the creation time. The frontmatter field `updated_at` is **removed**. Final frontmatter schema is:
   ```yaml
   source: flomo
   memo_id: <16-hex-chars>
   created_at: 2026-04-25T09:31:14+08:00
   tags: [想法, context-hub]
   ```

3. **Content is HTML, must be converted to markdown.** Use `markdownify` library to convert the inner HTML of `<div class="content">` to markdown. Tags appear inline as text (`#日记 #nice`) and are preserved verbatim in the body — they're additionally **extracted via regex** `#([\w/]+)` (unicode-aware) to populate the frontmatter `tags` list.

4. **Audio transcripts are preserved.** `<div class="audio-player__content">` text is extracted from the `<div class="files">` block and appended to the body as a separate paragraph prefixed with `[audio transcript] ` so an agent can distinguish original text from transcribed audio.

5. **Images and audio files are dropped.** Per the original brief ("先不考虑多模态") MVP does not copy or reference attachments. If a memo's content is empty after conversion AND it has no audio transcript (e.g. a memo containing only images), the memo is skipped, counted in the `! N skipped` summary line.

6. **Timezone for created_at.** Flomo's HTML displays naive `YYYY-MM-DD HH:MM:SS` strings. They are interpreted as the **system local timezone of the import machine** (per spec §4) and emitted as ISO-8601 with offset.

### Implementation note on parsing

Use `BeautifulSoup` for the HTML parse. The structure is regular enough that a `soup.select('.memo')` walk plus three `.select_one` calls per memo extracts everything cleanly.
