"""Merge Phase 4 sub-cluster results back into synthetic_tags.yaml + scopes.yaml.

For each <hub>/_index/cluster-work/subcluster/<slug>/result.yaml:
  1. Read its `assignments` list.
  2. Replace the parent-level label in synthetic_tags.yaml with the sub-level
     label (`Auto/<parent>/<sub>`) for every path it covers.
  3. Append `sub_categories` entries to scopes.yaml under `scopes:` (preserve
     existing).

Idempotent: running twice produces the same output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def load_yaml(p: Path):
    if not p.is_file():
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise SystemExit(f"YAML parse error in {p}: {e}")


def dump_yaml(p: Path, data) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    tmp.replace(p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    syn_path = args.root / "_index" / "synthetic_tags.yaml"
    scopes_path = args.root / "_index" / "scopes.yaml"
    sub_root = args.root / "_index" / "cluster-work" / "subcluster"

    syn = load_yaml(syn_path) or {}
    if "assignments" not in syn or not isinstance(syn["assignments"], dict):
        raise SystemExit(f"{syn_path} missing assignments mapping")
    assignments = syn["assignments"]

    scopes_doc = load_yaml(scopes_path) or {}
    if "scopes" not in scopes_doc or not isinstance(scopes_doc["scopes"], dict):
        raise SystemExit(f"{scopes_path} missing scopes mapping")
    existing_scopes = scopes_doc["scopes"]

    total_remapped = 0
    new_scope_count = 0
    summary: list[tuple[str, int]] = []

    for sub_dir in sorted(sub_root.iterdir()):
        if not sub_dir.is_dir():
            continue
        result_file = sub_dir / "result.yaml"
        if not result_file.is_file():
            continue
        result = load_yaml(result_file)
        if not isinstance(result, dict):
            continue
        parent = result.get("parent")
        sub_cats = result.get("sub_categories") or []
        sub_assignments = result.get("assignments") or []
        if not isinstance(parent, str):
            continue

        # 1. Remap assignments
        remapped = 0
        for entry in sub_assignments:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            cat = entry.get("category")
            if not isinstance(path, str) or not isinstance(cat, str):
                continue
            if path in assignments:
                assignments[path] = cat
                remapped += 1

        # 2. Merge sub_categories into scopes (don't overwrite if user-edited)
        for sc in sub_cats:
            if not isinstance(sc, dict):
                continue
            name = sc.get("name")
            if not isinstance(name, str):
                continue
            if name in existing_scopes:
                continue  # respect user edits
            entry = {}
            desc = sc.get("description") or sc.get("one_liner")
            scope = sc.get("routing_scope")
            if isinstance(desc, str):
                entry["description"] = desc
            if isinstance(scope, str):
                entry["routing_scope"] = scope
            if entry:
                existing_scopes[name] = entry
                new_scope_count += 1

        summary.append((parent, remapped))
        total_remapped += remapped

    # Write back synthetic_tags
    syn["assignments"] = dict(sorted(assignments.items()))
    dump_yaml(syn_path, syn)

    # Write back scopes
    scopes_doc["scopes"] = existing_scopes
    dump_yaml(scopes_path, scopes_doc)

    print(f"merged {len(summary)} parent buckets:")
    for parent, n in summary:
        print(f"  {n:>4} paths remapped under {parent}")
    print()
    print(f"total paths remapped: {total_remapped}")
    print(f"new scope entries added: {new_scope_count}")
    print(f"synthetic_tags.yaml -> {syn_path}")
    print(f"scopes.yaml         -> {scopes_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
