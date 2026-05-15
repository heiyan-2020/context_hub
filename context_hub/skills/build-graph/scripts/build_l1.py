"""Stage 6a: build the level-1 graph from L0 community summaries and run Louvain.

Reads `_index/community_summaries.yaml`. Treats each summary as a node with
its agent-emitted handles. Computes IDF over the small summary corpus,
builds edges from shared handles (Σ IDF), runs Louvain. Writes
`agent-work/level1_grouping.yaml` plus one `agent-work/communities/L1_Cx.md`
input file per super-community for the Stage 6b summarizers.
"""
from __future__ import annotations

import argparse
import math
from collections import Counter
from pathlib import Path

import yaml

from context_hub.graph import louvain


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    S = yaml.safe_load((args.root / "_index" / "community_summaries.yaml")
                       .read_text(encoding="utf-8"))
    comms = S["communities"]
    n = len(comms)
    by_id = {c["id"]: c for c in comms}

    def norm(h):
        return h.strip().lower() if h.isascii() else h.strip()

    per = {c["id"]: {norm(h) for h in c["handles"]} for c in comms}
    df: Counter = Counter()
    for hs in per.values():
        for h in hs:
            df[h] += 1
    max_df = max(2, int(n * 0.5))
    idf = {h: math.log(n / d) for h, d in df.items() if 2 <= d <= max_df}

    by_handle: dict[str, list[str]] = {}
    for cid, hs in per.items():
        for h in hs & idf.keys():
            by_handle.setdefault(h, []).append(cid)

    edges: dict[tuple[str, str], dict] = {}
    for h, members in by_handle.items():
        if len(members) < 2:
            continue
        members = sorted(set(members))
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pair = (members[i], members[j])
                e = edges.setdefault(pair, {"weight": 0.0, "handles": []})
                e["weight"] += idf[h]
                e["handles"].append(h)

    print(f"level-1 graph: {n} nodes, {len(edges)} edges")
    super_of = louvain([c["id"] for c in comms], edges)
    groups: dict[int, list[str]] = {}
    for cid, sid in super_of.items():
        groups.setdefault(sid, []).append(cid)

    out = {
        "schema_version": 1,
        "level": 1,
        "super_communities": {f"L1:C{sid}": sorted(kids)
                              for sid, kids in groups.items()},
    }
    work = args.root / "_index" / "agent-work"
    (work / "level1_grouping.yaml").write_text(
        yaml.safe_dump(out, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    # write Stage 6b input files
    cdir = work / "communities"
    cdir.mkdir(parents=True, exist_ok=True)
    for sid, kids in out["super_communities"].items():
        hc: Counter = Counter()
        for cid in kids:
            for h in by_id[cid]["handles"]:
                hc[h] += 1
        lines = [
            f"# Level-1 super-community {sid}",
            "",
            f"This super-community contains {len(kids)} L0 communities "
            f"(covering {sum(by_id[c]['size'] for c in kids)} notes total).",
            "",
            "## Recurring handles across children:",
            "  " + ", ".join(f"{h}×{c}" for h, c in hc.most_common()),
            "",
            "## Children",
            "",
        ]
        for cid in kids:
            c = by_id[cid]
            lines += [
                f"### {cid}  «{c['title']}»  ({c['size']} notes)",
                "",
                f"**Summary**: {c['summary']}",
                "",
                f"**Handles**: {', '.join(c['handles'])}",
                "",
            ]
        (cdir / f"{sid.replace(':', '_')}.md").write_text("\n".join(lines),
                                                         encoding="utf-8")

    print(f"=> {len(out['super_communities'])} super-communities")
    for sid, kids in sorted(out["super_communities"].items(),
                            key=lambda kv: -len(kv[1])):
        print(f"  {sid}: {len(kids)} children "
              f"({sum(by_id[c]['size'] for c in kids)} notes)")
    if len(out["super_communities"]) < 10:
        print("\n  < 10 super-communities → this is the top level. "
              "Now dispatch Stage 6b summarizers, then "
              "run aggregate_hierarchy.py.")
    else:
        print("\n  ⚠ ≥ 10 super-communities — a deeper recursion would "
              "be needed (not implemented in v1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
