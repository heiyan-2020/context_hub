"""Merge subagent batch results into the canonical synthetic_tags.yaml.

Step 5 of cluster-context-hub.  Reads every
`<hub_root>/_index/cluster-work/results/result-NN.yaml`, validates them
against the agreed category set in `categories.yaml`, and emits
`<hub_root>/_index/synthetic_tags.yaml`.

Validation:
  - Every rel_path appears at most once across all results.
  - Every category is either in categories.yaml's list, or the literal
    "Auto/未分类" sentinel, or a hierarchical extension `Auto/<top>/<sub>`
    whose top-level prefix is in the list (for phase-4 sub-clustered batches).
  - Every hub-managed note has exactly one assignment (or appears in the
    skipped list with a reason).
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


from context_hub.index import iter_managed


def load_categories(work_dir: Path) -> tuple[set[str], str]:
    cat_file = work_dir / "categories.yaml"
    if not cat_file.is_file():
        raise SystemExit(
            f"missing {cat_file} -- run Phase 1 (discovery) first and write "
            "the agreed category list there"
        )
    raw = yaml.safe_load(cat_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "categories" not in raw:
        raise SystemExit(f"{cat_file} must have top-level `categories:` list")
    cats = raw["categories"]
    if not isinstance(cats, list):
        raise SystemExit(f"{cat_file} `categories:` must be a list")
    names: set[str] = set()
    for c in cats:
        if isinstance(c, str):
            names.add(c)
        elif isinstance(c, dict) and "name" in c:
            names.add(c["name"])
    if not names:
        raise SystemExit(f"{cat_file} categories list is empty")
    sentinel = "Auto/未分类"
    return names, sentinel


def validate_category(label: str, valid_set: set[str], sentinel: str) -> bool:
    if label == sentinel:
        return True
    if label in valid_set:
        return True
    # Phase-4: hierarchical extension under an existing top-level.
    if "/" in label:
        top = "/".join(label.split("/")[:2])  # Auto/<top>
        return top in valid_set
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--strict", action="store_true",
                    help="fail if any hub note lacks an assignment")
    args = ap.parse_args()

    work_dir = args.root / "_index" / "cluster-work"
    results_dir = work_dir / "results"
    if not results_dir.is_dir():
        raise SystemExit(f"missing {results_dir} -- run Phase 2 first")

    valid_cats, sentinel = load_categories(work_dir)

    all_paths = {it.rel_path for it in iter_managed(args.root)}
    assignments: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []  # (path, existing, new)
    unknown_cats: list[tuple[str, str, str]] = []  # (file, path, label)
    extra_paths: list[tuple[str, str]] = []  # (file, path not in hub)

    for result_file in sorted(results_dir.glob("result-*.yaml")):
        raw = yaml.safe_load(result_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            print(f"warn: {result_file} not a YAML mapping -- skipped", file=sys.stderr)
            continue
        entries = raw.get("assignments") or []
        if not isinstance(entries, list):
            print(f"warn: {result_file} `assignments` not a list -- skipped",
                  file=sys.stderr)
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            label = entry.get("category")
            if not isinstance(path, str) or not isinstance(label, str):
                continue
            if path not in all_paths:
                extra_paths.append((result_file.name, path))
                continue
            if not validate_category(label, valid_cats, sentinel):
                unknown_cats.append((result_file.name, path, label))
                continue
            if path in assignments and assignments[path] != label:
                duplicates.append((path, assignments[path], label))
                continue
            assignments[path] = label

    missing = sorted(p for p in all_paths if p not in assignments)

    counter: Counter[str] = Counter(assignments.values())
    total = len(all_paths)
    print(f"=== aggregate: {len(assignments)} / {total} notes assigned ===")
    print(f"missing: {len(missing)}, duplicates: {len(duplicates)}, "
          f"unknown-category: {len(unknown_cats)}, "
          f"extra-paths: {len(extra_paths)}")
    print()
    print("Distribution:")
    for label, count in counter.most_common():
        pct = 100 * count / total
        flag = ""
        if pct > 30:
            flag = "  [OVERSIZED >30%]"
        elif pct < 2:
            flag = "  [UNDERSIZED <2%]"
        print(f"  {count:>5}  ({pct:5.1f}%)  {label}{flag}")

    if unknown_cats:
        print()
        print("⚠  Unknown categories (not in categories.yaml, dropped):")
        for f, p, label in unknown_cats[:10]:
            print(f"   {f}: {p} -> {label}")
        if len(unknown_cats) > 10:
            print(f"   ... and {len(unknown_cats) - 10} more")

    if duplicates:
        print()
        print("⚠  Conflicting assignments (path appears in multiple batches):")
        for p, a, b in duplicates[:10]:
            print(f"   {p}: {a}  vs  {b}")
        if len(duplicates) > 10:
            print(f"   ... and {len(duplicates) - 10} more")

    if missing:
        print()
        print(f"⚠  {len(missing)} hub notes have NO assignment "
              f"(re-batch + re-dispatch, or accept as fallthrough):")
        for p in missing[:8]:
            print(f"   {p}")
        if len(missing) > 8:
            print(f"   ... and {len(missing) - 8} more")
        if args.strict:
            return 1

    out = args.root / "_index" / "synthetic_tags.yaml"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "note": (
            "Synthetic tag assignments authored by Claude in-session "
            "(cluster-context-hub skill, two-phase agent-driven design). "
            "Each note's rel_path -> exactly one Auto/<...> path. "
            "Hand-editable. Original .md files are not modified by this overlay."
        ),
        "assignments": dict(sorted(assignments.items())),
    }
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    tmp.replace(out)
    print()
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
