"""Read <hub_root>/_index/synthetic_tags.yaml and flag distribution issues.

Step 5 follow-up of cluster-context-hub.  Surfaces:
  - Oversized buckets (>30% of total) -> need sub-clustering
  - Undersized buckets (<2% of total) -> merge candidates
  - Heavy fallback bucket (Auto/URL·碎片 or similar >15%) -> rules too narrow
  - Hierarchy depth distribution
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


from context_hub.index import iter_managed, load_synthetic_tags


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--oversize-pct", type=float, default=30.0)
    ap.add_argument("--undersize-pct", type=float, default=2.0)
    ap.add_argument("--fallback-pct", type=float, default=15.0,
                    help="threshold where the catch-all bucket flags as too big")
    args = ap.parse_args()

    items = list(iter_managed(args.root))
    overlay = load_synthetic_tags(args.root / "_index")
    if not overlay:
        print("no synthetic_tags.yaml -- nothing to audit")
        return 0

    total = len(items)
    bucket = Counter(overlay.values())
    print(f"=== audit: {sum(bucket.values())} assignments / {total} notes ===")

    oversized = []
    undersized = []
    fallback_like = []
    for label, count in bucket.most_common():
        pct = 100 * count / total
        if pct > args.oversize_pct:
            oversized.append((label, count, pct))
        elif pct < args.undersize_pct:
            undersized.append((label, count, pct))
        # Heuristic: anything labelled with 碎片/misc/other/fallback/未知
        if any(k in label for k in ["碎片", "misc", "Misc", "Other", "其他", "未分类", "未知"]):
            if pct > args.fallback_pct:
                fallback_like.append((label, count, pct))

    # Depth distribution
    depth_counter: Counter[int] = Counter()
    for path in overlay.values():
        depth_counter[path.count("/")] += 1

    print()
    print("Depth distribution (0 = Auto root, 1 = Auto/top, 2 = Auto/top/sub):")
    for depth, count in sorted(depth_counter.items()):
        print(f"  depth {depth}: {count} notes")

    print()
    if oversized:
        print(f"⚠  Oversized (> {args.oversize_pct}%) -- consider sub-clustering:")
        for label, count, pct in oversized:
            print(f"   {count:>5}  ({pct:5.1f}%)  {label}")
    else:
        print("✓  no oversized buckets")

    print()
    if undersized:
        print(f"⚠  Undersized (< {args.undersize_pct}%) -- merge candidates:")
        for label, count, pct in undersized:
            print(f"   {count:>5}  ({pct:5.1f}%)  {label}")
    else:
        print("✓  no undersized buckets")

    print()
    if fallback_like:
        print(f"⚠  Fallback-like buckets > {args.fallback_pct}% "
              f"-- rules may be too narrow:")
        for label, count, pct in fallback_like:
            print(f"   {count:>5}  ({pct:5.1f}%)  {label}")
    else:
        print("✓  no oversized fallback buckets")

    return 0


if __name__ == "__main__":
    sys.exit(main())
