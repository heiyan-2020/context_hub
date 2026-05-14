"""Split the hub's notes into N batch files, each readable by one subagent.

Step 4 of cluster-context-hub.  Each batch lands at
`<hub_root>/_index/cluster-work/batches/batch-NN.md` and contains ~`size`
notes with their full body, existing tags, and date.

The batch format is designed for an LLM subagent to read directly and emit
per-note category assignments.  Each note appears as:

    ### path/to/note.md
    _2026-04-24_ · len=124 · tags: 思考, 长线记录/观点演进
    <body, inline #tags stripped, capped at body_cap chars>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


from context_hub.index import iter_managed, _TAG_INLINE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--size", type=int, default=150,
                    help="approximate notes per batch (default 150)")
    ap.add_argument("--body-cap", type=int, default=600,
                    help="cap each note body to N chars (default 600)")
    ap.add_argument("--order", choices=["chronological", "random"], default="chronological")
    args = ap.parse_args()

    items = list(iter_managed(args.root))
    if not items:
        print(f"no hub-managed notes under {args.root}", file=sys.stderr)
        return 2

    if args.order == "chronological":
        items.sort(key=lambda i: i.created_at)
    else:
        import random
        random.Random(42).shuffle(items)

    work_dir = args.root / "_index" / "cluster-work"
    batches_dir = work_dir / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)

    # Clean previous batches
    for old in batches_dir.glob("batch-*.md"):
        old.unlink()

    n_batches = (len(items) + args.size - 1) // args.size
    width = max(2, len(str(n_batches)))
    for bidx in range(n_batches):
        start = bidx * args.size
        chunk = items[start : start + args.size]
        fname = batches_dir / f"batch-{bidx + 1:0{width}d}.md"
        with fname.open("w", encoding="utf-8") as f:
            f.write(f"# Batch {bidx + 1} of {n_batches}  ({len(chunk)} notes)\n\n")
            f.write(f"batch_id: {bidx + 1:0{width}d}\n")
            f.write(f"total_in_batch: {len(chunk)}\n\n")
            f.write("---\n\n")
            for it in chunk:
                body = _TAG_INLINE.sub("", it.body)
                body = re.sub(r"\s+", " ", body).strip()
                body = body[: args.body_cap] + ("…" if len(body) > args.body_cap else "")
                tags_str = ", ".join(it.tags) if it.tags else "(untagged)"
                f.write(f"### {it.rel_path}\n")
                f.write(f"_{it.created_at.strftime('%Y-%m-%d')}_ · "
                        f"len={len(it.body)} · tags: {tags_str}\n\n")
                f.write(f"{body}\n\n")

    print(f"wrote {n_batches} batches of ≤{args.size} notes to {batches_dir}")
    for f in sorted(batches_dir.glob("batch-*.md")):
        print(f"  {f.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
