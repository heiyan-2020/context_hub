from __future__ import annotations
from tests.conftest import managed_md

import io
import zipfile
from pathlib import Path

from context_hub.cli import main as cli_main
from .conftest import make_flomo_html, memo_block


def _write_zip(path: Path, html_bytes: bytes) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("flomo@user-20260425/user的笔记.html", html_bytes)
    path.write_bytes(buf.getvalue())


def test_e2e_first_import_creates_tree(tmp_path: Path, fixture_zip: Path):
    root = tmp_path / "hub"
    rc = cli_main(["import", "flomo", str(fixture_zip), "--root", str(root)])
    assert rc == 0
    files = sorted(p.relative_to(root).as_posix() for p in managed_md(root))
    # 3 memos (one image-only skipped)
    assert len(files) == 3
    # all paths conform to YYYY/MM/DD/HHMM-id.md
    for f in files:
        parts = f.split("/")
        assert len(parts) == 4
        assert parts[0].isdigit() and len(parts[0]) == 4
        assert parts[3].endswith(".md")


def test_e2e_second_import_is_idempotent(tmp_path: Path, fixture_zip: Path):
    root = tmp_path / "hub"
    cli_main(["import", "flomo", str(fixture_zip), "--root", str(root)])
    snapshot1 = {p.relative_to(root).as_posix(): p.read_text() for p in managed_md(root)}

    rc = cli_main(["import", "flomo", str(fixture_zip), "--root", str(root)])
    assert rc == 0
    snapshot2 = {p.relative_to(root).as_posix(): p.read_text() for p in managed_md(root)}
    assert snapshot1 == snapshot2


def test_e2e_full_mirror_handles_deletion(tmp_path: Path, simple_memos_html: bytes):
    root = tmp_path / "hub"
    zip1 = tmp_path / "z1.zip"
    _write_zip(zip1, simple_memos_html)
    cli_main(["import", "flomo", str(zip1), "--root", str(root)])
    files_before = sorted(p.relative_to(root).as_posix() for p in managed_md(root))
    assert len(files_before) == 3

    # second zip with one memo dropped
    smaller_html = make_flomo_html(
        memo_block("2026-04-25 09:31:14", "<p>第一条 #日记 #想法/灵感</p>")
    )
    zip2 = tmp_path / "z2.zip"
    _write_zip(zip2, smaller_html)
    rc = cli_main(["import", "flomo", str(zip2), "--root", str(root)])
    assert rc == 0
    files_after = sorted(p.relative_to(root).as_posix() for p in managed_md(root))
    assert len(files_after) == 1


def test_e2e_dry_run_writes_nothing(tmp_path: Path, fixture_zip: Path):
    root = tmp_path / "hub"
    rc = cli_main(["import", "flomo", str(fixture_zip), "--root", str(root), "--dry-run"])
    assert rc == 0
    assert not root.exists() or not any(managed_md(root))


def test_e2e_does_not_touch_user_files(tmp_path: Path, fixture_zip: Path):
    root = tmp_path / "hub"
    root.mkdir()
    user_note = root / "my-note.md"
    user_note.write_text("---\nsource: handwritten\n---\n\nhi\n")
    cli_main(["import", "flomo", str(fixture_zip), "--root", str(root)])
    assert user_note.exists()
    assert user_note.read_text() == "---\nsource: handwritten\n---\n\nhi\n"
