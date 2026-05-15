"""Stage 4 prep: write per-community input files for the Stage 5 summarizers.

Reads `_index/graph.json` (which must be from the agent path) and writes one
`agent-work/communities/Cx.md` per community with size ≥ --min-size.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--min-size", type=int, default=5,
                    help="skip communities smaller than this (default 5)")
    args = ap.parse_args()

    data = json.loads((args.root / "_index" / "graph.json").read_text(encoding="utf-8"))
    nodes = data["nodes"]
    comms = data["stats"]["communities"]

    work = args.root / "_index" / "agent-work" / "communities"
    work.mkdir(parents=True, exist_ok=True)

    by_c: dict[int, list[dict]] = {}
    for n in nodes:
        by_c.setdefault(n["community"], []).append(n)

    emitted, skipped = [], []
    for cid_str, size in comms.items():
        cid = int(cid_str[1:])
        if size < args.min_size:
            skipped.append((cid_str, size))
            continue
        members = sorted(by_c[cid], key=lambda n: -n["degree"])
        hc: Counter = Counter()
        for n in members:
            for h in n["handles"]:
                hc[h] += 1

        lines = [
            f"# Community {cid_str}",
            "",
            f"Size: {size} notes",
            f"Top handles: " + ", ".join(f"{h}×{c}" for h, c in hc.most_common(15)),
            "",
            "## Notes in this community (sorted by degree):",
            "",
        ]
        show = members[:40]
        for n in show:
            prev = n["preview"][:160].replace("\n", " ").strip()
            handles_str = ", ".join(n["handles"][:6])
            lines.append(f"- `{n['id']}` [deg={n['degree']}] handles=[{handles_str}]")
            lines.append(f"  {prev}")
        if len(members) > 40:
            lines.append(f"")
            lines.append(f"_(showing top 40 of {len(members)} by degree)_")
        (work / f"{cid_str}.md").write_text("\n".join(lines), encoding="utf-8")
        emitted.append(cid_str)

    print(f"emitted {len(emitted)} community input files "
          f"(min-size {args.min_size})")
    print(f"skipped {len(skipped)} small communities "
          f"({sum(s for _, s in skipped)} notes total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
