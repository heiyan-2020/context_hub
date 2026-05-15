"""Stage 5 aggregate: merge per-community Cx.yaml → _index/community_summaries.yaml."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    work = args.root / "_index" / "agent-work" / "communities"
    graph_data = json.loads((args.root / "_index" / "graph.json").read_text(encoding="utf-8"))
    by_c: dict[int, list[str]] = {}
    for n in graph_data["nodes"]:
        by_c.setdefault(n["community"], []).append(n["id"])

    summaries = []
    for p in sorted(work.glob("C[0-9]*.yaml"), key=lambda x: int(x.stem[1:])):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cid_str = d.get("id")
        if not isinstance(cid_str, str) or not cid_str.startswith("C"):
            continue
        try:
            cid = int(cid_str[1:])
        except ValueError:
            continue
        d["size"] = len(by_c.get(cid, []))
        d["member_notes"] = sorted(by_c.get(cid, []))
        summaries.append(d)

    out = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level": 0,
        "note_count": sum(s["size"] for s in summaries),
        "community_count": len(summaries),
        "communities": summaries,
    }
    dest = args.root / "_index" / "community_summaries.yaml"
    dest.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    print(f"wrote {dest}")
    print(f"  {len(summaries)} L0 community summaries covering "
          f"{out['note_count']} notes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
