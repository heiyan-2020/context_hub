from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import flomo, obsidian, tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="context-hub")
    sub = parser.add_subparsers(dest="cmd", required=True)

    imp = sub.add_parser("import", help="import a source export into the hub")
    imp.add_argument(
        "source",
        choices=["flomo", "obsidian"],
        help="which source format",
    )
    imp.add_argument(
        "input_path",
        type=Path,
        help="path to the source input (flomo: export zip; obsidian: vault dir)",
    )
    imp.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "context-hub",
        help="hub output root directory (default: ~/context-hub)",
    )
    imp.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan without writing or deleting files",
    )

    args = parser.parse_args(argv)

    if args.cmd == "import":
        return _cmd_import(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2


def _cmd_import(args) -> int:
    source: str = args.source
    input_path: Path = args.input_path
    root: Path = args.root

    # parse + render — each source produces (item_id → (rel_path, content)).
    if source == "flomo":
        if not input_path.exists():
            print(f"error: zip not found: {input_path}", file=sys.stderr)
            return 2
        if not input_path.is_file():
            print(f"error: not a file: {input_path}", file=sys.stderr)
            return 2
        report = flomo.parse_zip(input_path)
        desired = {flomo.memo_id(m): flomo.render(m) for m in report.memos}
        skipped = report.skipped_empty + report.skipped_malformed
    elif source == "obsidian":
        if not input_path.exists():
            print(f"error: vault not found: {input_path}", file=sys.stderr)
            return 2
        if not input_path.is_dir():
            print(f"error: not a directory: {input_path}", file=sys.stderr)
            return 2
        report = obsidian.scan_vault(input_path)
        desired = {obsidian.note_id(n): obsidian.render(n) for n in report.notes}
        skipped = report.skipped_empty + report.skipped_malformed
    else:
        print(f"error: unknown source: {source}", file=sys.stderr)
        return 2

    current = tree.scan(root, source)
    plan = tree.diff(desired, current, root)

    skipped_suffix = f"  ! {skipped} skipped" if skipped else ""

    if args.dry_run:
        print(f"[dry-run] {plan.summary()}{skipped_suffix}")
        _print_plan_details(plan)
        return 0

    if not plan.is_empty():
        try:
            tree.probe_writable(root)
        except OSError as e:
            print(f"error: hub root not writable ({root}): {e}", file=sys.stderr)
            return 1

    tree.apply(plan, root)
    print(f"{plan.summary()}{skipped_suffix}")
    return 0


def _print_plan_details(plan: tree.Plan, max_per_kind: int = 5) -> None:
    if plan.adds:
        print(f"  ADD ({len(plan.adds)}):")
        for rel, _ in plan.adds[:max_per_kind]:
            print(f"    + {rel}")
        if len(plan.adds) > max_per_kind:
            print(f"    + ... and {len(plan.adds) - max_per_kind} more")
    if plan.updates:
        print(f"  UPDATE ({len(plan.updates)}):")
        for path, _ in plan.updates[:max_per_kind]:
            print(f"    ~ {path}")
        if len(plan.updates) > max_per_kind:
            print(f"    ~ ... and {len(plan.updates) - max_per_kind} more")
    if plan.moves:
        print(f"  MOVE ({len(plan.moves)}):")
        for old, new_rel, _ in plan.moves[:max_per_kind]:
            print(f"    {old} → {new_rel}")
        if len(plan.moves) > max_per_kind:
            print(f"    ... and {len(plan.moves) - max_per_kind} more")
    if plan.deletes:
        print(f"  DELETE ({len(plan.deletes)}):")
        for path in plan.deletes[:max_per_kind]:
            print(f"    - {path}")
        if len(plan.deletes) > max_per_kind:
            print(f"    - ... and {len(plan.deletes) - max_per_kind} more")


if __name__ == "__main__":
    sys.exit(main())
