"""Stage 2 prep: split the in-scope notes into N batches for parallel labelers.

Applies the same EXCLUDE_USER_TAGS filter as the graph pipeline, so chore
notes aren't sent for labeling.
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

from context_hub.graph import EXCLUDE_USER_TAGS
from context_hub.index import iter_managed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--batches", type=int, default=14,
                    help="number of parallel labeler batches (default 14)")
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()

    def excluded(it):
        return any(t.split("/")[-1] in EXCLUDE_USER_TAGS for t in it.tags)

    notes = [it for it in iter_managed(args.root) if not excluded(it)]
    rng = random.Random(args.seed)
    rng.shuffle(notes)

    work = args.root / "_index" / "agent-work"
    work.mkdir(parents=True, exist_ok=True)

    size = (len(notes) + args.batches - 1) // args.batches
    for b in range(args.batches):
        sl = notes[b * size:(b + 1) * size]
        if not sl:
            continue
        lines = []
        for it in sl:
            body = it.body.strip().replace("\r", "")
            if len(body) > 600:
                body = body[:600] + "…"
            tags = ",".join(it.tags) if it.tags else "-"
            lines.append(f"=== {it.rel_path}\nTAGS: {tags}\n{body}\n")
        (work / f"batch-{b + 1:02d}.md").write_text("\n".join(lines),
                                                   encoding="utf-8")

    print(f"in-scope notes: {len(notes)} (excluded by user tag: see "
          f"EXCLUDE_USER_TAGS in graph.py)")
    print(f"wrote {args.batches} batches × ~{size} notes each to {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
