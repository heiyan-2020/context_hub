from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import dedent

import pytest

from context_hub import obsidian, tree
from context_hub.cli import main as cli_main


TZ = timezone(timedelta(hours=8))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _set_mtime(path: Path, dt: datetime) -> None:
    ts = dt.timestamp()
    import os
    os.utime(path, (ts, ts))


# ---- vault scanning ----


def test_scan_vault_collects_md_files(tmp_path: Path):
    vault = tmp_path / "vault"
    _write(vault / "a.md", "hello")
    _write(vault / "sub" / "b.md", "world")
    report = obsidian.scan_vault(vault)
    assert {n.vault_path for n in report.notes} == {"a.md", "sub/b.md"}


def test_scan_vault_skips_hidden_directories(tmp_path: Path):
    vault = tmp_path / "vault"
    _write(vault / "keep.md", "hello")
    _write(vault / ".obsidian" / "config.md", "ignore")
    _write(vault / ".trash" / "deleted.md", "ignore")
    _write(vault / "notes" / ".draft" / "hidden.md", "ignore")
    report = obsidian.scan_vault(vault)
    assert {n.vault_path for n in report.notes} == {"keep.md"}


def test_scan_vault_counts_empty_notes(tmp_path: Path):
    vault = tmp_path / "vault"
    _write(vault / "blank.md", "")
    _write(vault / "frontmatter-only.md", "---\ntags: [a]\n---\n\n")
    _write(vault / "real.md", "content")
    report = obsidian.scan_vault(vault)
    assert {n.vault_path for n in report.notes} == {"real.md"}
    assert report.skipped_empty == 2


def test_scan_vault_missing_dir_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        obsidian.scan_vault(tmp_path / "nope")


def test_scan_vault_not_a_directory(tmp_path: Path):
    f = tmp_path / "file.md"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        obsidian.scan_vault(f)


# ---- frontmatter parsing ----


def test_frontmatter_created_at_iso(tmp_path: Path):
    vault = tmp_path / "v"
    _write(
        vault / "n.md",
        dedent(
            """\
            ---
            created: 2026-04-25T09:31:14+08:00
            ---

            body
            """
        ),
    )
    note = obsidian.scan_vault(vault).notes[0]
    assert note.created_at == datetime(2026, 4, 25, 9, 31, 14, tzinfo=TZ)


def test_frontmatter_created_at_yaml_datetime(tmp_path: Path):
    vault = tmp_path / "v"
    _write(
        vault / "n.md",
        dedent(
            """\
            ---
            created: 2026-04-25 09:31:14
            ---

            body
            """
        ),
    )
    note = obsidian.scan_vault(vault).notes[0]
    # naive YAML datetime gets local-tz attached
    assert note.created_at.year == 2026
    assert note.created_at.month == 4
    assert note.created_at.day == 25
    assert note.created_at.tzinfo is not None


def test_frontmatter_created_at_date_only(tmp_path: Path):
    vault = tmp_path / "v"
    _write(
        vault / "n.md",
        "---\ndate: 2026-04-25\n---\n\nbody\n",
    )
    note = obsidian.scan_vault(vault).notes[0]
    assert note.created_at.year == 2026
    assert note.created_at.month == 4
    assert note.created_at.day == 25


def test_frontmatter_created_at_epoch_ms(tmp_path: Path):
    vault = tmp_path / "v"
    # 2026-04-25T01:31:14Z in ms
    epoch_ms = int(datetime(2026, 4, 25, 1, 31, 14, tzinfo=timezone.utc).timestamp() * 1000)
    _write(vault / "n.md", f"---\ncreated_at: {epoch_ms}\n---\n\nbody\n")
    note = obsidian.scan_vault(vault).notes[0]
    assert note.created_at.year == 2026
    assert note.created_at.month == 4


def test_frontmatter_falls_back_to_mtime(tmp_path: Path):
    vault = tmp_path / "v"
    p = vault / "n.md"
    _write(p, "no frontmatter, just body")
    target = datetime(2024, 3, 1, 12, 0, 0, tzinfo=TZ)
    _set_mtime(p, target)
    note = obsidian.scan_vault(vault).notes[0]
    assert note.created_at.year == 2024
    assert note.created_at.month == 3
    assert note.created_at.day == 1


def test_tags_from_frontmatter_list(tmp_path: Path):
    vault = tmp_path / "v"
    _write(
        vault / "n.md",
        dedent(
            """\
            ---
            tags: [foo, bar/baz]
            ---

            body
            """
        ),
    )
    note = obsidian.scan_vault(vault).notes[0]
    assert "foo" in note.tags and "bar/baz" in note.tags


def test_tags_from_frontmatter_string(tmp_path: Path):
    vault = tmp_path / "v"
    _write(vault / "n.md", "---\ntags: foo, bar\n---\n\nbody\n")
    note = obsidian.scan_vault(vault).notes[0]
    assert "foo" in note.tags and "bar" in note.tags


def test_tags_inline_in_body(tmp_path: Path):
    vault = tmp_path / "v"
    _write(vault / "n.md", "Some text with #想法 and #foo/bar inline.")
    note = obsidian.scan_vault(vault).notes[0]
    assert "想法" in note.tags
    assert "foo/bar" in note.tags


def test_tags_combined_no_duplicates(tmp_path: Path):
    vault = tmp_path / "v"
    _write(
        vault / "n.md",
        dedent(
            """\
            ---
            tags: [想法, common]
            ---

            #common #another
            """
        ),
    )
    note = obsidian.scan_vault(vault).notes[0]
    assert note.tags.count("common") == 1
    assert "想法" in note.tags and "another" in note.tags


def test_body_strips_frontmatter(tmp_path: Path):
    vault = tmp_path / "v"
    _write(
        vault / "n.md",
        dedent(
            """\
            ---
            tags: [a]
            ---

            real content here
            """
        ),
    )
    note = obsidian.scan_vault(vault).notes[0]
    assert note.body.strip() == "real content here"
    assert "tags:" not in note.body


# ---- note_id + render ----


def test_note_id_is_stable(tmp_path: Path):
    vault = tmp_path / "v"
    _write(vault / "x.md", "body")
    n1 = obsidian.scan_vault(vault).notes[0]
    n2 = obsidian.scan_vault(vault).notes[0]
    assert obsidian.note_id(n1) == obsidian.note_id(n2)


def test_note_id_changes_with_path(tmp_path: Path):
    vault = tmp_path / "v"
    _write(vault / "a.md", "body")
    _write(vault / "b.md", "body")
    notes = {n.vault_path: n for n in obsidian.scan_vault(vault).notes}
    assert obsidian.note_id(notes["a.md"]) != obsidian.note_id(notes["b.md"])


def test_note_id_stable_across_edits(tmp_path: Path):
    vault = tmp_path / "v"
    _write(vault / "n.md", "version one")
    n1 = obsidian.scan_vault(vault).notes[0]
    _write(vault / "n.md", "version two")
    n2 = obsidian.scan_vault(vault).notes[0]
    # body changed but path didn't → id stable (UPDATE behavior, not DELETE+ADD)
    assert obsidian.note_id(n1) == obsidian.note_id(n2)


def test_render_output_shape(tmp_path: Path):
    vault = tmp_path / "v"
    _write(
        vault / "daily" / "2026-04-25.md",
        "---\ncreated_at: 2026-04-25T09:31:14+08:00\ntags: [日记]\n---\n\nhello world\n",
    )
    note = obsidian.scan_vault(vault).notes[0]
    rel, content = obsidian.render(note)
    parts = rel.parts
    assert parts[0] == "2026"
    assert parts[1] == "04"
    assert parts[2] == "25"
    assert parts[3].startswith("0931-") and parts[3].endswith(".md")
    assert content.startswith("---\n")
    assert "source: obsidian" in content
    assert "note_id:" in content
    assert "vault_path: daily/2026-04-25.md" in content
    assert "title: '2026-04-25'" in content  # date-like strings get quoted by YAML
    assert "hello world" in content


def test_render_is_byte_stable(tmp_path: Path):
    vault = tmp_path / "v"
    _write(vault / "n.md", "---\ncreated_at: 2026-04-25T09:31:14+08:00\n---\n\nbody\n")
    note = obsidian.scan_vault(vault).notes[0]
    a = obsidian.render(note)
    b = obsidian.render(note)
    assert a == b


# ---- e2e via CLI ----


def _make_basic_vault(vault: Path) -> None:
    _write(
        vault / "a.md",
        "---\ncreated_at: 2026-04-25T09:31:14+08:00\ntags: [foo]\n---\n\nfirst note\n",
    )
    _write(
        vault / "sub" / "b.md",
        "---\ncreated_at: 2026-04-24T22:18:03+08:00\n---\n\nsecond #bar\n",
    )
    _write(vault / ".obsidian" / "skip.md", "ignore me")


def test_e2e_obsidian_first_import(tmp_path: Path):
    vault = tmp_path / "vault"
    hub = tmp_path / "hub"
    _make_basic_vault(vault)
    rc = cli_main(["import", "obsidian", str(vault), "--root", str(hub)])
    assert rc == 0
    files = sorted(p.relative_to(hub).as_posix() for p in hub.rglob("*.md"))
    assert len(files) == 2


def test_e2e_obsidian_idempotent(tmp_path: Path):
    vault = tmp_path / "vault"
    hub = tmp_path / "hub"
    _make_basic_vault(vault)
    cli_main(["import", "obsidian", str(vault), "--root", str(hub)])
    snap1 = {p.relative_to(hub).as_posix(): p.read_text() for p in hub.rglob("*.md")}
    rc = cli_main(["import", "obsidian", str(vault), "--root", str(hub)])
    assert rc == 0
    snap2 = {p.relative_to(hub).as_posix(): p.read_text() for p in hub.rglob("*.md")}
    assert snap1 == snap2


def test_e2e_obsidian_full_mirror_on_delete(tmp_path: Path):
    vault = tmp_path / "vault"
    hub = tmp_path / "hub"
    _make_basic_vault(vault)
    cli_main(["import", "obsidian", str(vault), "--root", str(hub)])
    assert len(list(hub.rglob("*.md"))) == 2

    # delete one note from vault and re-import
    (vault / "sub" / "b.md").unlink()
    cli_main(["import", "obsidian", str(vault), "--root", str(hub)])
    files = list(hub.rglob("*.md"))
    assert len(files) == 1


def test_e2e_obsidian_update_on_edit(tmp_path: Path):
    vault = tmp_path / "vault"
    hub = tmp_path / "hub"
    _write(
        vault / "n.md",
        "---\ncreated_at: 2026-04-25T09:31:14+08:00\n---\n\nfirst version\n",
    )
    cli_main(["import", "obsidian", str(vault), "--root", str(hub)])
    files = list(hub.rglob("*.md"))
    assert len(files) == 1
    first_path = files[0]

    _write(
        vault / "n.md",
        "---\ncreated_at: 2026-04-25T09:31:14+08:00\n---\n\nsecond version\n",
    )
    cli_main(["import", "obsidian", str(vault), "--root", str(hub)])
    # path unchanged (id is path-based, created_at unchanged) → UPDATE
    assert first_path.exists()
    assert "second version" in first_path.read_text()
    assert len(list(hub.rglob("*.md"))) == 1


def test_e2e_obsidian_coexists_with_flomo(tmp_path: Path):
    """Importing obsidian must not touch flomo-source files in the same hub."""
    vault = tmp_path / "vault"
    hub = tmp_path / "hub"
    hub.mkdir()
    flomo_file = hub / "2025" / "01" / "01" / "0900-deadbeefdeadbeef.md"
    flomo_file.parent.mkdir(parents=True)
    flomo_file.write_text(
        "---\nsource: flomo\nmemo_id: deadbeefdeadbeef\n"
        "created_at: '2025-01-01T09:00:00+08:00'\ntags: []\n---\n\nflomo body\n"
    )
    _make_basic_vault(vault)
    cli_main(["import", "obsidian", str(vault), "--root", str(hub)])
    assert flomo_file.exists()
    # 1 flomo + 2 obsidian
    assert len(list(hub.rglob("*.md"))) == 3


def test_e2e_obsidian_does_not_touch_user_files(tmp_path: Path):
    vault = tmp_path / "vault"
    hub = tmp_path / "hub"
    hub.mkdir()
    note = hub / "personal.md"
    note.write_text("---\nsource: handwritten\n---\n\nkeep me\n")
    _make_basic_vault(vault)
    cli_main(["import", "obsidian", str(vault), "--root", str(hub)])
    assert note.exists()
    assert "keep me" in note.read_text()


def test_e2e_obsidian_dry_run(tmp_path: Path):
    vault = tmp_path / "vault"
    hub = tmp_path / "hub"
    _make_basic_vault(vault)
    rc = cli_main(["import", "obsidian", str(vault), "--root", str(hub), "--dry-run"])
    assert rc == 0
    assert not hub.exists() or not any(hub.rglob("*.md"))


def test_e2e_obsidian_missing_vault(tmp_path: Path):
    hub = tmp_path / "hub"
    rc = cli_main(["import", "obsidian", str(tmp_path / "nope"), "--root", str(hub)])
    assert rc == 2


def test_e2e_obsidian_input_must_be_dir(tmp_path: Path):
    f = tmp_path / "x.md"
    f.write_text("y")
    hub = tmp_path / "hub"
    rc = cli_main(["import", "obsidian", str(f), "--root", str(hub)])
    assert rc == 2
