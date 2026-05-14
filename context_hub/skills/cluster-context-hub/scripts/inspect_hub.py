"""Inspect a context-hub corpus: totals, tag distribution, length stats,
existing Auto/ state.  Step 1 of the cluster-context-hub skill workflow.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


from context_hub.index import (
    iter_managed,
    load_scopes,
    load_synthetic_tags,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True, help="hub root directory")
    args = ap.parse_args()

    root: Path = args.root
    if not root.is_dir():
        print(f"error: hub root is not a directory: {root}", file=sys.stderr)
        return 2

    items = list(iter_managed(root))
    if not items:
        print(f"hub root {root} has 0 hub-managed notes.")
        return 0

    total = len(items)
    untagged = sum(1 for i in items if not i.tags)
    tag_counter: Counter[str] = Counter()
    for it in items:
        for t in it.tags:
            tag_counter[t] += 1
    body_lens = sorted(len(i.body) for i in items)
    by_year: Counter[int] = Counter(i.created_at.year for i in items)
    by_source: Counter[str] = Counter(i.source for i in items)

    print(f"=== {root} ===")
    print(f"Total hub-managed notes: {total}")
    print(f"  Untagged (no frontmatter + no inline #tags): {untagged}  "
          f"({100*untagged/total:.1f}%)")
    print(f"  Tagged: {total - untagged}")
    print()
    print(f"By source: {dict(by_source.most_common())}")
    print(f"By year: {dict(sorted(by_year.items()))}")
    print()
    print(f"Body length: min={body_lens[0]} "
          f"p25={body_lens[total//4]} median={body_lens[total//2]} "
          f"p75={body_lens[3*total//4]} max={body_lens[-1]}")
    print(f"Unique tags: {len(tag_counter)}")
    print("Top 20 tags:")
    for tag, count in tag_counter.most_common(20):
        print(f"  {count:>5}  {tag}")
    print()

    # Existing overlay state
    idx_dir = root / "_index"
    syn = load_synthetic_tags(idx_dir)
    if syn:
        bucket_counter: Counter[str] = Counter(syn.values())
        print(f"Existing synthetic_tags.yaml: {len(syn)} assignments "
              f"across {len(bucket_counter)} Auto/* paths")
        for path_, c in bucket_counter.most_common():
            pct = 100 * c / total
            flag = ""
            if pct > 30:
                flag = "  [OVERSIZED >30%]"
            elif pct < 2:
                flag = "  [UNDERSIZED <2%]"
            print(f"  {c:>5}  ({pct:4.1f}%)  {path_}{flag}")
    else:
        print("No synthetic_tags.yaml yet.")

    scopes = load_scopes(idx_dir)
    print(f"Existing scopes.yaml: {len(scopes)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
