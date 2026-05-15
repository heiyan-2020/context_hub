"""Stage 2 aggregate: merge per-batch result-XX.yaml → _index/agent_handles.yaml.

Validates that every label is in vocabulary.yaml; drops OOV labels with a
reported count.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()

    idx = args.root / "_index"
    work = idx / "agent-work"
    vocab_path = work / "vocabulary.yaml"
    if not vocab_path.is_file():
        print(f"error: {vocab_path} missing — run Stage 1 first",
              file=sys.stderr)
        return 2
    vocab = set(yaml.safe_load(vocab_path.read_text(encoding="utf-8"))["vocabulary"])

    batches = sorted(work.glob("result-*.yaml"))
    if not batches:
        print(f"error: no result-*.yaml files in {work}", file=sys.stderr)
        return 2

    merged: dict[str, list[str]] = {}
    oov: Counter = Counter()
    used: Counter = Counter()
    for bp in batches:
        raw = yaml.safe_load(bp.read_text(encoding="utf-8")) or {}
        for rel, hs in (raw.get("assignments", {}) or {}).items():
            if rel in merged:
                continue
            clean: list[str] = []
            for h in hs or []:
                if not isinstance(h, str):
                    continue
                h = h.strip()
                if not h:
                    continue
                if h in vocab:
                    clean.append(h)
                    used[h] += 1
                else:
                    oov[h] += 1
            merged[rel] = clean

    out = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vocabulary_size": len(vocab),
        "note_count": len(merged),
        "assignments": merged,
    }
    dest = idx / "agent_handles.yaml"
    dest.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    print(f"wrote {dest}")
    print(f"  {len(merged)} notes; {sum(len(v) for v in merged.values())} assignments")
    print(f"  {len(used)}/{len(vocab)} vocabulary handles used at least once")
    if oov:
        print(f"  ! {sum(oov.values())} OOV labels dropped "
              f"({len(oov)} distinct); top: {oov.most_common(10)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
