"""Stage 6b aggregate: assemble the final community_hierarchy.yaml from
L0 summaries + L1 super-summaries + the level-1 grouping."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import yaml


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    idx = args.root / "_index"
    work = idx / "agent-work"
    L0 = yaml.safe_load((idx / "community_summaries.yaml").read_text(encoding="utf-8"))
    G = yaml.safe_load((work / "level1_grouping.yaml").read_text(encoding="utf-8"))
    by_l0 = {c["id"]: c for c in L0["communities"]}

    # parent map
    child_to_parent: dict[str, str] = {}
    for sid, kids in G["super_communities"].items():
        for k in kids:
            child_to_parent[k] = sid

    # load L1 summary files
    cdir = work / "communities"
    l1_nodes = []
    for sid in G["super_communities"]:
        fname = sid.replace(":", "_") + ".yaml"
        p = cdir / fname
        if not p.is_file():
            print(f"  ⚠ missing {p} — Stage 6b incomplete for {sid}")
            continue
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        kids = G["super_communities"][sid]
        d["children"] = kids
        d["note_count"] = sum(by_l0[k]["size"] for k in kids)
        d["parent"] = None
        l1_nodes.append(d)

    # annotate L0 parents
    for c in L0["communities"]:
        c["parent"] = child_to_parent.get(c["id"])

    hierarchy = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "levels": [
            {
                "level": 1,
                "description": "top-level super-communities (Louvain on L0 summaries)",
                "n": len(l1_nodes),
                "nodes": sorted(l1_nodes, key=lambda n: -n["note_count"]),
            },
            {
                "level": 0,
                "description": "first-level communities (Louvain on the note graph)",
                "n": len(L0["communities"]),
                "nodes": sorted(L0["communities"], key=lambda n: -n["size"]),
            },
        ],
    }
    dest = idx / "community_hierarchy.yaml"
    dest.write_text(yaml.safe_dump(hierarchy, allow_unicode=True,
                                   sort_keys=False, width=120),
                    encoding="utf-8")

    print(f"wrote {dest}")
    print(f"  level 1: {len(l1_nodes)} super-communities")
    print(f"  level 0: {len(L0['communities'])} communities")
    print(f"\nTop level (by note count):")
    for n in hierarchy["levels"][0]["nodes"]:
        print(f"  {n['id']:8} «{n['title']}» — {n['note_count']} notes "
              f"({len(n['children'])} children)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
