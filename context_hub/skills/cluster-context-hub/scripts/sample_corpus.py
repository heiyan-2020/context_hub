"""Write a stratified sample of the hub's notes to a markdown file the
caller can read.  Step 2 of cluster-context-hub.

Stratification axes:
  - Year (proportional to corpus density)
  - Body length tertile (short / medium / long)
  - Tag presence (some tagged, some untagged)
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import defaultdict
from pathlib import Path


from context_hub.index import iter_managed, _TAG_INLINE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True, help="output markdown file")
    ap.add_argument("--n", type=int, default=160,
                    help="approximate total samples (will be split across strata)")
    ap.add_argument("--body-cap", type=int, default=400,
                    help="cap each note's body preview to N chars")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    items = list(iter_managed(args.root))
    if not items:
        print(f"no hub-managed notes under {args.root}", file=sys.stderr)
        return 2

    # Length tertiles
    sorted_by_len = sorted(items, key=lambda i: len(i.body))
    t1 = len(sorted_by_len) // 3
    t2 = 2 * len(sorted_by_len) // 3
    length_of: dict[str, str] = {}
    for it in sorted_by_len[:t1]:
        length_of[it.rel_path] = "S"
    for it in sorted_by_len[t1:t2]:
        length_of[it.rel_path] = "M"
    for it in sorted_by_len[t2:]:
        length_of[it.rel_path] = "L"

    # Bucket by (year, length, has_tags)
    buckets: dict[tuple, list] = defaultdict(list)
    for it in items:
        key = (it.created_at.year, length_of[it.rel_path], bool(it.tags))
        buckets[key].append(it)

    # Quota per bucket = ceil(n * |bucket| / |corpus|), min 1
    total = len(items)
    samples = []
    seen = set()
    for key, bucket in buckets.items():
        quota = max(1, round(args.n * len(bucket) / total))
        rng.shuffle(bucket)
        for it in bucket[:quota]:
            if it.rel_path not in seen:
                samples.append(it)
                seen.add(it.rel_path)

    # Sort samples chronologically for readability
    samples.sort(key=lambda i: i.created_at)

    with args.out.open("w", encoding="utf-8") as f:
        f.write(f"# Hub sample for clustering  ({len(samples)} of {total} notes)\n\n")
        f.write(f"Stratified across year × length-tertile × tag-presence.\n\n")
        for it in samples:
            body = _TAG_INLINE.sub("", it.body)
            body = re.sub(r"\s+", " ", body).strip()
            body = body[:args.body_cap] + ("…" if len(body) > args.body_cap else "")
            tags_str = ", ".join(it.tags) if it.tags else "(untagged)"
            f.write(f"### {it.rel_path}\n")
            f.write(f"_{it.created_at.strftime('%Y-%m-%d')}_ · "
                    f"len={len(it.body)} · tags: {tags_str}\n\n")
            f.write(f"{body}\n\n")

    print(f"wrote {len(samples)} samples to {args.out}")
    print(f"  buckets: {len(buckets)} cells "
          f"(years × length-tertile × tag-presence)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
