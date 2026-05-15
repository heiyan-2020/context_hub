"""Read parsed notes from the hub and produce auxiliary index files.

Two aux artifacts:
- `tags.json`    inverted index: user tag → [note paths]
- `recents.json` newest N notes with preview metadata

The hierarchical structure of the hub is *not* a tag tree any more — the
thought-network's community hierarchy (`community_hierarchy.yaml`) is the
canonical organisation, produced by the `build-graph` skill. This module
just supplies the lightweight tag-based retrieval indices.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import yaml


SCHEMA_VERSION = 1
RECENTS_LIMIT = 100
INDEX_DIR_NAME = "_index"
PREVIEW_CHARS = 80

_TAG_INLINE = re.compile(r"(?<![\w/])#([\w/\-一-鿿]+)")
_FRONTMATTER_HEAD = "---\n"
_FRONTMATTER_FOOT = "\n---\n"
_KNOWN_ID_FIELDS = ("memo_id", "note_id", "id")


@dataclass(frozen=True)
class ManagedItem:
    path: Path
    rel_path: str          # POSIX, hub-root-relative
    source: str
    item_id: str
    created_at: datetime
    tags: tuple[str, ...]
    title: Optional[str]
    body: str


def iter_managed(root: Path) -> Iterator[ManagedItem]:
    """Walk hub root and yield one ManagedItem per parseable hub-managed markdown.

    Skips files under <root>/_index/.  Silently drops files that fail frontmatter
    parsing, lack a `source`, an id field, or a parseable `created_at`.
    """
    if not root.exists() or not root.is_dir():
        return
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if parts and parts[0] == INDEX_DIR_NAME:
            continue
        try:
            txt = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        item = _parse(path, txt, root)
        if item is not None:
            yield item


def _parse(path: Path, txt: str, root: Path) -> Optional[ManagedItem]:
    if not txt.startswith(_FRONTMATTER_HEAD):
        return None
    end = txt.find(_FRONTMATTER_FOOT, len(_FRONTMATTER_HEAD))
    if end == -1:
        return None
    fm_raw = txt[len(_FRONTMATTER_HEAD):end]
    body = txt[end + len(_FRONTMATTER_FOOT):].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_raw)
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    source = fm.get("source")
    if not isinstance(source, str) or not source:
        return None
    item_id = None
    for k in _KNOWN_ID_FIELDS:
        v = fm.get(k)
        if isinstance(v, str) and v:
            item_id = v
            break
    if item_id is None:
        return None
    created_at = _coerce_dt(fm.get("created_at"))
    if created_at is None:
        return None

    fm_tags = fm.get("tags") or []
    if not isinstance(fm_tags, list):
        fm_tags = []
    inline = _TAG_INLINE.findall(body)
    seen: set[str] = set()
    tags: list[str] = []
    for t in list(fm_tags) + list(inline):
        if isinstance(t, str) and t and t not in seen:
            seen.add(t)
            tags.append(t)

    title_v = fm.get("title")
    title = title_v if isinstance(title_v, str) and title_v else None

    rel = path.relative_to(root).as_posix()
    return ManagedItem(
        path=path,
        rel_path=rel,
        source=source,
        item_id=item_id,
        created_at=created_at,
        tags=tuple(tags),
        title=title,
        body=body,
    )


def _coerce_dt(v) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        s = v.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


def _preview(body: str, n: int = PREVIEW_CHARS) -> str:
    stripped = _TAG_INLINE.sub("", body)
    cleaned = re.sub(r"\s+", " ", stripped).strip()
    if len(cleaned) <= n:
        return cleaned
    return cleaned[:n].rstrip() + "…"


# ---------- aux renderers ----------


def render_tags_json(items: list[ManagedItem], generated_at: str) -> str:
    inv: dict[str, list[str]] = {}
    for it in items:
        for t in it.tags:
            inv.setdefault(t, []).append(it.rel_path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "count": sum(len(v) for v in inv.values()),
        "tags": {k: sorted(inv[k]) for k in sorted(inv)},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def render_recents_json(items: list[ManagedItem], generated_at: str,
                        limit: int = RECENTS_LIMIT) -> str:
    sorted_items = sorted(
        items,
        key=lambda i: (i.created_at, i.source, i.item_id),
        reverse=True,
    )
    entries = []
    for it in sorted_items[:limit]:
        entries.append({
            "source": it.source,
            "id": it.item_id,
            "path": it.rel_path,
            "created_at": it.created_at.isoformat(),
            "tags": list(it.tags),
            "title": it.title,
            "preview": _preview(it.body, PREVIEW_CHARS),
        })
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "limit": limit,
        "count": len(entries),
        "entries": entries,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


# ---------- orchestrator ----------


class IndexLayoutError(RuntimeError):
    pass


def generate_full_index(root: Path) -> dict:
    """Regenerate <root>/_index/tags.json and recents.json.

    Returns a small dict of counts for the CLI summary.
    """
    items = list(iter_managed(root))
    idx_dir = root / INDEX_DIR_NAME
    if idx_dir.exists() and not idx_dir.is_dir():
        raise IndexLayoutError(f"{idx_dir} exists and is not a directory")
    idx_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _atomic_write(idx_dir / "tags.json", render_tags_json(items, generated_at))
    _atomic_write(idx_dir / "recents.json", render_recents_json(items, generated_at))

    by_source: dict[str, int] = {}
    for it in items:
        by_source[it.source] = by_source.get(it.source, 0) + 1
    return {
        "total": len(items),
        "by_source": by_source,
        "generated_at": generated_at,
    }


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
