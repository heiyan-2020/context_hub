"""Stage 1 prep: dump unique handles + df from the deterministic graph.

Reads `_index/graph.json` (which must be from a deterministic run — delete
`_index/agent_handles.yaml` first if you have one from an earlier session)
and writes `_index/agent-work/candidates.md` for the curator agent.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True, help="hub root")
    args = ap.parse_args()

    graph_path = args.root / "_index" / "graph.json"
    if not graph_path.is_file():
        raise SystemExit(f"error: {graph_path} not found. "
                         f"Run `context-hub graph --root {args.root}` first.")

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    if data.get("stats", {}).get("handle_source") == "agent":
        raise SystemExit(
            f"error: graph.json was produced from the agent path. "
            f"Stage 1 needs the deterministic pool. "
            f"Delete {args.root}/_index/agent_handles.yaml and re-run "
            f"`context-hub graph --root {args.root}`, then retry."
        )

    df: Counter = Counter()
    for n in data["nodes"]:
        for h in n["handles"]:
            df[h] += 1

    work = args.root / "_index" / "agent-work"
    work.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Handle Curation Candidates",
        "",
        f"Pool: {len(df)} programmatically-extracted handles from "
        f"{data['stats']['in_scope_notes']} in-scope notes.",
        "`df` = number of notes containing this handle. Higher df = more common.",
        "",
        "## User-curated tags (almost always KEEP unless vacuous)",
        "",
    ]
    by_kind = {"tag": [], "en": [], "cjk": []}
    for h, d in df.most_common():
        if h.startswith("#"):
            by_kind["tag"].append((h[1:], d))
        elif h[0].isascii():
            by_kind["en"].append((h, d))
        else:
            by_kind["cjk"].append((h, d))

    for n, d in by_kind["tag"]:
        lines.append(f"  {n}\tdf={d}")
    lines += ["", "## English / ASCII words", ""]
    for n, d in by_kind["en"]:
        lines.append(f"  {n}\tdf={d}")
    lines += ["", "## CJK bigrams (the noisy mass — be ruthless)", ""]
    for n, d in by_kind["cjk"]:
        lines.append(f"  {n}\tdf={d}")

    out = work / "candidates.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} ({os.path.getsize(out):,} bytes) — "
          f"{len(by_kind['tag'])} tags + {len(by_kind['en'])} en + "
          f"{len(by_kind['cjk'])} cjk = {len(df)} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
