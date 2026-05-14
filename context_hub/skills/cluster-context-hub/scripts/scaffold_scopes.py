"""Print Auto/* paths that have synthetic_tags assignments but no scopes
entry yet.  For each missing scope, print 3-5 sample notes from that bucket
so the agent can author description + routing_scope text.

Step 6 of cluster-context-hub.
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import defaultdict
from pathlib import Path


from context_hub.index import (
    iter_managed,
    load_scopes,
    load_synthetic_tags,
    _TAG_INLINE,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--samples", type=int, default=4,
                    help="number of sample notes to print per missing scope")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    items = list(iter_managed(args.root))
    by_path = {it.rel_path: it for it in items}
    overlay = load_synthetic_tags(args.root / "_index")
    scopes = load_scopes(args.root / "_index")

    bucket_to_paths: dict[str, list[str]] = defaultdict(list)
    for path, label in overlay.items():
        bucket_to_paths[label].append(path)

    # Compute ALL Auto/* paths used, including their ancestor prefixes
    used_paths: set[str] = set()
    for label in bucket_to_paths:
        parts = label.split("/")
        for i in range(1, len(parts) + 1):
            used_paths.add("/".join(parts[:i]))

    # Existing scope keys
    have = set(scopes.keys())

    missing = sorted(p for p in used_paths if p not in have)

    if not missing:
        print("All Auto/* paths already have scopes entries. Nothing to do.")
        return 0

    print(f"Missing scopes for {len(missing)} Auto/* paths:\n")
    for path in missing:
        # samples come from leaf buckets matching this prefix
        candidates: list[str] = []
        for bucket, paths in bucket_to_paths.items():
            if bucket == path or bucket.startswith(path + "/"):
                candidates.extend(paths)
        rng.shuffle(candidates)
        sample = candidates[: args.samples]
        print(f"## {path}  ({len(candidates)} notes)")
        for p in sample:
            it = by_path.get(p)
            if it is None:
                continue
            body = re.sub(r"\s+", " ", _TAG_INLINE.sub("", it.body)).strip()[:240]
            print(f"  - {p} · {it.created_at.strftime('%Y-%m-%d')} · "
                  f"tags={list(it.tags)}")
            print(f"      > {body}")
        print()

    print()
    print("=== Author scopes.yaml entries (paste under `scopes:`) ===")
    print()
    for path in missing:
        print(f"  {path}:")
        print(f"    description: <one-line collection-level description>")
        print(f"    routing_scope: >-")
        print(f"      <2-3 sentence agent-only hint describing what's in the cluster>")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
