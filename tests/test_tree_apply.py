from __future__ import annotations

from pathlib import Path, PurePosixPath

from context_hub import tree


FM_FLOMO = "---\nsource: flomo\nmemo_id: a\n---\n\n"
FM_OTHER = "---\nsource: notion\nmemo_id: b\n---\n\n"
NO_FM = "just plain markdown, no frontmatter\n"


def test_apply_writes_adds(tmp_path: Path):
    plan = tree.Plan(adds=[(PurePosixPath("2026/04/25/0931-a.md"), FM_FLOMO + "hi")])
    tree.apply(plan, tmp_path)
    p = tmp_path / "2026" / "04" / "25" / "0931-a.md"
    assert p.exists()
    assert p.read_text() == FM_FLOMO + "hi"


def test_apply_deletes_and_cleans_empty_dirs(tmp_path: Path):
    target = tmp_path / "2026" / "04" / "25" / "0931-a.md"
    target.parent.mkdir(parents=True)
    target.write_text(FM_FLOMO + "hi")
    plan = tree.Plan(deletes=[target])
    tree.apply(plan, tmp_path)
    assert not target.exists()
    # parent dirs should be removed too
    assert not (tmp_path / "2026").exists()


def test_apply_move(tmp_path: Path):
    old = tmp_path / "2026" / "04" / "24" / "2200-a.md"
    old.parent.mkdir(parents=True)
    old.write_text(FM_FLOMO + "old-body")
    plan = tree.Plan(
        moves=[(old, PurePosixPath("2026/04/25/0931-a.md"), FM_FLOMO + "new-body")]
    )
    tree.apply(plan, tmp_path)
    assert not old.exists()
    new = tmp_path / "2026" / "04" / "25" / "0931-a.md"
    assert new.read_text() == FM_FLOMO + "new-body"


def test_scan_only_picks_up_flomo_files(tmp_path: Path):
    (tmp_path / "f.md").write_text(FM_FLOMO + "hi")
    (tmp_path / "n.md").write_text(FM_OTHER + "hi")
    (tmp_path / "plain.md").write_text(NO_FM)
    (tmp_path / "not_md.txt").write_text("ignore me")
    out = tree.scan(tmp_path)
    assert set(out.keys()) == {"a"}


def test_scan_handles_missing_root(tmp_path: Path):
    out = tree.scan(tmp_path / "does_not_exist")
    assert out == {}


def test_apply_does_not_touch_non_hub_files(tmp_path: Path):
    other = tmp_path / "user_note.md"
    other.write_text(FM_OTHER + "keep me")
    plain = tmp_path / "plain.md"
    plain.write_text(NO_FM)
    plan = tree.Plan(adds=[(PurePosixPath("2026/04/25/0931-a.md"), FM_FLOMO + "added")])
    tree.apply(plan, tmp_path)
    assert other.exists() and other.read_text() == FM_OTHER + "keep me"
    assert plain.exists() and plain.read_text() == NO_FM
