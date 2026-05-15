from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import flomo, graph as graph_mod, index as index_mod, obsidian, tree


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
    imp.add_argument(
        "--no-index",
        action="store_true",
        help="skip regenerating <root>/_index/ after import",
    )

    rx = sub.add_parser("reindex", help="rebuild <root>/_index/{tags,recents}.json")
    rx.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "context-hub",
        help="hub root (default: ~/context-hub)",
    )

    gp = sub.add_parser(
        "graph",
        help="build the thought-network graph (_index/graph.{json,html}). "
             "Uses agent_handles.yaml if present, otherwise the deterministic "
             "bigram pipeline. Orchestration of the full agent-driven build "
             "lives in the `build-graph` skill.",
    )
    gp.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "context-hub",
        help="hub root (default: ~/context-hub)",
    )

    viz = sub.add_parser(
        "visualize",
        help="re-render _index/graph.html from the existing _index/graph.json "
             "(use after editing context_hub/visualize.py)",
    )
    viz.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "context-hub",
        help="hub root (reads <root>/_index/graph.json)",
    )
    viz.add_argument("--input", type=Path, help="explicit input JSON path")
    viz.add_argument("--output", type=Path, help="explicit output HTML path")

    sp = sub.add_parser("skill-path", help="print path to a packaged skill bundle")
    sp.add_argument(
        "skill",
        nargs="?",
        choices=["context-hub", "build-graph"],
        default="context-hub",
        help="which skill (default: context-hub, the query skill)",
    )

    inst = sub.add_parser(
        "install-skill",
        help="copy the packaged skill bundles into ~/.claude/skills/ "
             "(or a custom --target) so Claude Code picks them up",
    )
    inst.add_argument(
        "--target",
        type=Path,
        default=Path.home() / ".claude" / "skills",
        help="skills base directory (default: ~/.claude/skills)",
    )
    inst.add_argument(
        "--skill",
        choices=["context-hub", "build-graph", "all"],
        default="all",
        help="which skill(s) to install (default: all)",
    )
    inst.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing skill directories in target",
    )

    args = parser.parse_args(argv)

    if args.cmd == "import":
        return _cmd_import(args)
    if args.cmd == "reindex":
        return _cmd_reindex(args)
    if args.cmd == "graph":
        return _cmd_graph(args)
    if args.cmd == "visualize":
        return _cmd_visualize(args)
    if args.cmd == "skill-path":
        return _cmd_skill_path(args)
    if args.cmd == "install-skill":
        return _cmd_install_skill(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2


def _cmd_import(args) -> int:
    source: str = args.source
    input_path: Path = args.input_path
    root: Path = args.root

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
    if not args.no_index:
        try:
            stats = index_mod.generate_full_index(root)
            print(_index_summary(stats))
        except index_mod.IndexLayoutError as e:
            print(
                f"markdown changes applied; index regeneration failed: {e}; "
                f"run `context-hub reindex --root {root}` to refresh _index/",
                file=sys.stderr,
            )
            return 1
    return 0


def _cmd_reindex(args) -> int:
    root: Path = args.root
    if not root.exists():
        print(f"error: hub root does not exist: {root}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"error: hub root is not a directory: {root}", file=sys.stderr)
        return 2
    try:
        stats = index_mod.generate_full_index(root)
    except index_mod.IndexLayoutError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(_index_summary(stats))
    return 0


def _cmd_graph(args) -> int:
    root: Path = args.root
    if not root.is_dir():
        print(f"error: hub root does not exist: {root}", file=sys.stderr)
        return 2
    agent_path = root / "_index" / "agent_handles.yaml"
    if not agent_path.is_file():
        print(f"⚠ {agent_path} not found — building from the deterministic "
              f"bigram path. Run the build-graph skill to produce agent handles.",
              file=sys.stderr)
    stats = graph_mod.generate_graph(root)
    print(
        f"graph built: {stats['connected_notes']}/{stats['in_scope_notes']} "
        f"in-scope notes connected; {stats['edges']} edges; "
        f"{stats['handles']} handles; source={stats['handle_source']}; "
        f"{stats['excluded_notes']} chore notes excluded; "
        f"generated {stats['generated_at']}"
    )
    top = list(stats["communities"].items())[:5]
    if top:
        print(f"  top communities: " +
              ", ".join(f"{k}={v}" for k, v in top))
    print(f"  -> {root / '_index' / 'graph.html'}")
    return 0


def _cmd_visualize(args) -> int:
    from .visualize import render_to_file
    idx = args.root / "_index"
    input_path = args.input or idx / "graph.json"
    output_path = args.output or idx / "graph.html"
    if not input_path.is_file():
        print(f"error: input JSON not found: {input_path}", file=sys.stderr)
        return 2
    stats = render_to_file(input_path, output_path)
    print(f"rendered {stats['nodes']} nodes, {stats['edges']} edges "
          f"({stats['handle_source']}) -> {stats['output']}")
    return 0


def _packaged_skill_dir(name: str):
    """Return a Traversable for context_hub/skills/<name>/, or None if missing."""
    from importlib.resources import files
    try:
        d = files("context_hub").joinpath("skills", name)
    except (ModuleNotFoundError, FileNotFoundError):
        return None
    return d if d.is_dir() else None


def _cmd_skill_path(args) -> int:
    d = _packaged_skill_dir(args.skill)
    if d is None:
        print(f"error: skill bundle '{args.skill}' not packaged", file=sys.stderr)
        return 1
    skill_md = d.joinpath("SKILL.md")
    if not skill_md.is_file():
        print(f"error: {args.skill}/SKILL.md missing in package", file=sys.stderr)
        return 1
    print(str(skill_md))
    return 0


def _cmd_install_skill(args) -> int:
    """Copy packaged skill bundles into a Claude-discoverable directory."""
    import shutil
    from importlib.resources import as_file

    names = (
        ["context-hub", "build-graph"]
        if args.skill == "all"
        else [args.skill]
    )
    base: Path = args.target
    base.mkdir(parents=True, exist_ok=True)

    installed: list[Path] = []
    for name in names:
        src = _packaged_skill_dir(name)
        if src is None:
            print(f"error: skill bundle '{name}' not packaged", file=sys.stderr)
            return 1
        dst = base / name
        if dst.exists() and not args.force:
            print(
                f"error: {dst} already exists; pass --force to overwrite",
                file=sys.stderr,
            )
            return 1
        with as_file(src) as real_src:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(real_src, dst)
        installed.append(dst)

    for dst in installed:
        print(f"installed -> {dst}")
    print()
    print("Next steps:")
    print(f"  - set CONTEXT_HUB_ROOT to your hub root "
          f"(where `context-hub import` wrote to)")
    print(f"  - restart Claude Code (or /reload-plugins)")
    print(f"  - `context-hub` auto-triggers when you ask about your past notes;")
    print(f"    `build-graph` triggers when you ask to (re)build the hierarchical graph.")
    return 0


def _index_summary(stats: dict) -> str:
    by = ", ".join(f"{k}={v}" for k, v in sorted(stats["by_source"].items()))
    return (
        f"_index/ rebuilt: {stats['total']} notes ({by or 'no sources'}); "
        f"generated {stats['generated_at']}"
    )


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
