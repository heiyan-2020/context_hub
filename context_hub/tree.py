from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml


@dataclass
class Plan:
    adds: list[tuple[PurePosixPath, str]] = field(default_factory=list)
    updates: list[tuple[Path, str]] = field(default_factory=list)
    moves: list[tuple[Path, PurePosixPath, str]] = field(default_factory=list)
    deletes: list[Path] = field(default_factory=list)
    skipped_unchanged: int = 0

    def is_empty(self) -> bool:
        return not (self.adds or self.updates or self.moves or self.deletes)

    def summary(self) -> str:
        return (
            f"+{len(self.adds)} added  "
            f"~{len(self.updates)} updated  "
            f"→{len(self.moves)} moved  "
            f"-{len(self.deletes)} deleted  "
            f"={self.skipped_unchanged} unchanged"
        )


_ID_FIELDS = ("memo_id", "note_id", "id")


def scan(root: Path, source: str) -> dict[str, tuple[Path, str]]:
    """Walk root, parse frontmatter, return {item_id: (abs_path, content_str)}.

    Only files with frontmatter `source: <source>` are indexed. Anything
    else is silently ignored (not our content).

    The id is read from the first present of: memo_id, note_id, id.
    """
    out: dict[str, tuple[Path, str]] = {}
    if not root.exists():
        return out
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fm = _read_frontmatter(content)
        if fm is None:
            continue
        if fm.get("source") != source:
            continue
        item_id = None
        for k in _ID_FIELDS:
            v = fm.get(k)
            if isinstance(v, str) and v:
                item_id = v
                break
        if item_id is None:
            continue
        out[item_id] = (path, content)
    return out


def diff(
    desired: dict[str, tuple[PurePosixPath, str]],
    current: dict[str, tuple[Path, str]],
    root: Path,
) -> Plan:
    plan = Plan()
    desired_ids = set(desired)
    current_ids = set(current)

    for mid in desired_ids - current_ids:
        plan.adds.append(desired[mid])

    for mid in desired_ids & current_ids:
        d_rel, d_content = desired[mid]
        c_path, c_content = current[mid]
        d_abs = (root / d_rel).resolve()
        same_path = c_path.resolve() == d_abs
        same_content = c_content == d_content
        if same_path and same_content:
            plan.skipped_unchanged += 1
        elif same_path and not same_content:
            plan.updates.append((c_path, d_content))
        else:
            plan.moves.append((c_path, d_rel, d_content))

    for mid in current_ids - desired_ids:
        plan.deletes.append(current[mid][0])

    return plan


def apply(plan: Plan, root: Path) -> None:
    # 1. deletes + remove-half of moves
    for path in plan.deletes:
        path.unlink(missing_ok=True)
    for old_path, _new_rel, _content in plan.moves:
        old_path.unlink(missing_ok=True)

    # 2. adds + updates + write-half of moves
    for rel, content in plan.adds:
        _write(root / rel, content)
    for path, content in plan.updates:
        _write(path, content)
    for _old_path, new_rel, content in plan.moves:
        _write(root / new_rel, content)

    # 3. clean up empty dirs
    _cleanup_empty_dirs(root)


def probe_writable(root: Path) -> None:
    """Raise OSError if root is not writable. Run before mutating anything."""
    root.mkdir(parents=True, exist_ok=True)
    probe = root / ".context_hub_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def _write(abs_path: Path, content: str) -> None:
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")


def _read_frontmatter(content: str) -> dict | None:
    if not content.startswith("---\n"):
        return None
    end = content.find("\n---", 4)
    if end == -1:
        return None
    block = content[4:end]
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _cleanup_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    # walk bottom-up so parent dirs become empty after children are removed
    for path in sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            path.rmdir()
        except OSError:
            pass  # not empty, leave it
