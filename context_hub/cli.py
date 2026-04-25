from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import flomo, render, tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="context-hub")
    sub = parser.add_subparsers(dest="cmd", required=True)

    imp = sub.add_parser("import", help="import a source export into the hub")
    imp.add_argument("source", choices=["flomo"], help="which source format")
    imp.add_argument("zip_path", type=Path, help="path to the source export zip")
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
    zip_path: Path = args.zip_path
    root: Path = args.root

    if not zip_path.exists():
        print(f"error: zip not found: {zip_path}", file=sys.stderr)
        return 2
    if not zip_path.is_file():
        print(f"error: not a file: {zip_path}", file=sys.stderr)
        return 2

    # parse
    report = flomo.parse_zip(zip_path)

    # render desired
    desired: dict[str, tuple] = {}
    for memo in report.memos:
        rel_path, content = render.render(memo)
        mid = render.memo_id(memo)
        desired[mid] = (rel_path, content)

    # scan current
    current = tree.scan(root)

    # diff
    plan = tree.diff(desired, current, root)

    skipped = report.skipped_empty + report.skipped_malformed
    skipped_suffix = f"  ! {skipped} skipped" if skipped else ""

    if args.dry_run:
        print(f"[dry-run] {plan.summary()}{skipped_suffix}")
        _print_plan_details(plan)
        return 0

    # write probe before any mutation
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
