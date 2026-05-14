"""Find clusters in <hub>/_index/synthetic_tags.yaml that exceed --max-pct of
the corpus, and dump each one's notes to a markdown file the subagent can read.

For each oversized cluster Auto/<path>, write
  <hub>/_index/cluster-work/subcluster/<slug>/notes.md

containing all its notes (path + date + tags + body), AND
  <hub>/_index/cluster-work/subcluster/<slug>/parent.yaml
recording parent name, total count, and the corpus-relative size budget.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml


from context_hub.index import iter_managed, load_synthetic_tags, _TAG_INLINE


def slugify(path: str) -> str:
    # Auto/自我反思与内省 -> 自我反思与内省  ; replace any non-word char with -
    s = path.split("/", 1)[1] if path.startswith("Auto/") else path
    s = re.sub(r"[^\w一-鿿]+", "-", s).strip("-")
    return s or "unnamed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--max-pct", type=float, default=5.0,
                    help="any cluster larger than this fraction must be split (default 5)")
    ap.add_argument("--body-cap", type=int, default=600)
    args = ap.parse_args()

    items = list(iter_managed(args.root))
    by_path = {it.rel_path: it for it in items}
    overlay = load_synthetic_tags(args.root / "_index")
    total = len(items)
    threshold = total * args.max_pct / 100

    bucket: dict[str, list[str]] = defaultdict(list)
    for path, label in overlay.items():
        bucket[label].append(path)

    work_root = args.root / "_index" / "cluster-work" / "subcluster"
    work_root.mkdir(parents=True, exist_ok=True)
    # clean old runs
    for child in work_root.iterdir():
        if child.is_dir():
            for f in child.iterdir():
                if f.is_file():
                    f.unlink()
            child.rmdir()

    oversized = []
    for label, paths in bucket.items():
        if len(paths) > threshold:
            oversized.append((label, paths))
    oversized.sort(key=lambda t: -len(t[1]))

    print(f"corpus={total}, 5% threshold = {threshold:.0f}")
    print(f"oversized clusters: {len(oversized)}\n")

    for label, paths in oversized:
        slug = slugify(label)
        sub_dir = work_root / slug
        sub_dir.mkdir(parents=True, exist_ok=True)

        # parent.yaml
        meta = {
            "parent_label": label,
            "parent_count": len(paths),
            "parent_pct": round(100 * len(paths) / total, 2),
            "corpus_total": total,
            "max_pct_per_subcluster": args.max_pct,
            "max_notes_per_subcluster": int(threshold),
            "slug": slug,
        }
        (sub_dir / "parent.yaml").write_text(
            yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        # notes.md
        notes_path = sub_dir / "notes.md"
        with notes_path.open("w", encoding="utf-8") as f:
            f.write(f"# Sub-cluster source: {label}\n\n")
            f.write(f"parent_label: {label}\n")
            f.write(f"parent_count: {len(paths)}\n")
            f.write(f"max_sub_size: {int(threshold)} (5% of {total})\n\n")
            f.write("---\n\n")
            for p in sorted(paths, key=lambda rp: by_path[rp].created_at if rp in by_path else 0):
                it = by_path.get(p)
                if it is None:
                    continue
                body = _TAG_INLINE.sub("", it.body)
                body = re.sub(r"\s+", " ", body).strip()
                body = body[: args.body_cap] + ("…" if len(body) > args.body_cap else "")
                tags_str = ", ".join(it.tags) if it.tags else "(untagged)"
                f.write(f"### {it.rel_path}\n")
                f.write(f"_{it.created_at.strftime('%Y-%m-%d')}_ · "
                        f"len={len(it.body)} · tags: {tags_str}\n\n")
                f.write(f"{body}\n\n")

        print(f"  {len(paths):>4}  ({100*len(paths)/total:5.2f}%)  {label}")
        print(f"       -> {sub_dir.relative_to(args.root)}/notes.md")
        print(f"       budget: 3-7 sub-clusters, each ≤ {int(threshold)} notes")

    print(f"\nNow dispatch {len(oversized)} sub-clustering subagents, one per parent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
