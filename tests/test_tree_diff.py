from __future__ import annotations

from pathlib import Path, PurePosixPath

from context_hub import tree


def D(*items):
    return {mid: (PurePosixPath(p), c) for mid, p, c in items}


def C(*items):
    return {mid: (Path(p), c) for mid, p, c in items}


def test_diff_add(tmp_path: Path):
    desired = D(("a", "2026/04/25/0931-a.md", "X"))
    current = C()
    plan = tree.diff(desired, current, tmp_path)
    assert len(plan.adds) == 1
    assert plan.adds[0] == (PurePosixPath("2026/04/25/0931-a.md"), "X")


def test_diff_skip(tmp_path: Path):
    rel = "2026/04/25/0931-a.md"
    abs_path = (tmp_path / rel).resolve()
    desired = D(("a", rel, "X"))
    current = C(("a", str(abs_path), "X"))
    plan = tree.diff(desired, current, tmp_path)
    assert plan.is_empty()
    assert plan.skipped_unchanged == 1


def test_diff_update(tmp_path: Path):
    rel = "2026/04/25/0931-a.md"
    abs_path = (tmp_path / rel).resolve()
    desired = D(("a", rel, "NEW"))
    current = C(("a", str(abs_path), "OLD"))
    plan = tree.diff(desired, current, tmp_path)
    assert len(plan.updates) == 1
    assert plan.updates[0][1] == "NEW"


def test_diff_move(tmp_path: Path):
    desired = D(("a", "2026/04/25/0931-a.md", "X"))
    # current is at a different path (e.g. created_at changed)
    current = C(("a", str((tmp_path / "2026/04/24/2200-a.md").resolve()), "X"))
    plan = tree.diff(desired, current, tmp_path)
    assert len(plan.moves) == 1
    old, new_rel, content = plan.moves[0]
    assert new_rel == PurePosixPath("2026/04/25/0931-a.md")
    assert content == "X"


def test_diff_delete(tmp_path: Path):
    desired = D()
    current = C(("a", str(tmp_path / "2026/04/25/0931-a.md"), "X"))
    plan = tree.diff(desired, current, tmp_path)
    assert len(plan.deletes) == 1


def test_diff_mixed(tmp_path: Path):
    rel_a = "2026/04/25/0931-a.md"
    rel_b = "2026/04/25/0932-b.md"
    rel_c = "2026/04/25/0933-c.md"

    desired = D(
        ("a", rel_a, "X"),  # skip
        ("b", rel_b, "NEW"),  # update
        ("d", "2026/04/25/0934-d.md", "NEW-D"),  # add
    )
    current = C(
        ("a", str((tmp_path / rel_a).resolve()), "X"),
        ("b", str((tmp_path / rel_b).resolve()), "OLD"),
        ("c", str((tmp_path / rel_c).resolve()), "C"),  # delete
    )
    plan = tree.diff(desired, current, tmp_path)
    assert len(plan.adds) == 1
    assert len(plan.updates) == 1
    assert len(plan.deletes) == 1
    assert plan.skipped_unchanged == 1
