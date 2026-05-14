from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import yaml


SCHEMA_VERSION = 1
RECENTS_LIMIT = 100
INDEX_DIR_NAME = "_index"
INLINE_NOTE_CAP = 25  # notes shown inline per tag node before "...more"
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
    parsing, lack a `source`, an id field, or a parseable `created_at` — matches
    tree.scan's defensive semantics.
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
    # Strip inline #tags (they're already captured as structured data).
    stripped = _TAG_INLINE.sub("", body)
    cleaned = re.sub(r"\s+", " ", stripped).strip()
    if len(cleaned) <= n:
        return cleaned
    return cleaned[:n].rstrip() + "…"


# ---------- tag-tree ----------


@dataclass
class TreeNode:
    name: str                                          # last path segment, "" for root
    path: tuple[str, ...]                              # full segment path from root
    items: list[ManagedItem] = field(default_factory=list)   # attached *exactly* at this node
    children: dict[str, "TreeNode"] = field(default_factory=dict)

    def total_count(self) -> int:
        n = len(self.items)
        for c in self.children.values():
            n += c.total_count()
        return n


_UNTAGGED_LABEL = "(untagged)"


def build_tag_tree(items: list[ManagedItem]) -> TreeNode:
    """Group items into a tag-hierarchy tree.  A multi-tag item appears under each tag path.

    Untagged items go under a synthetic top-level node named "(untagged)".
    """
    root = TreeNode(name="", path=())
    untagged = TreeNode(name=_UNTAGGED_LABEL, path=(_UNTAGGED_LABEL,))
    for it in items:
        if not it.tags:
            untagged.items.append(it)
            continue
        for tag in it.tags:
            segs = tuple(s for s in tag.split("/") if s)
            if not segs:
                continue
            cur = root
            for seg in segs:
                child = cur.children.get(seg)
                if child is None:
                    child = TreeNode(name=seg, path=cur.path + (seg,))
                    cur.children[seg] = child
                cur = child
            cur.items.append(it)
    if untagged.items:
        root.children[_UNTAGGED_LABEL] = untagged
    return root


# ---------- scopes overlay ----------


def load_scopes(idx_dir: Path) -> dict[str, dict]:
    """Read <idx_dir>/scopes.yaml if present.

    Returns a dict keyed by full tag path (e.g., "长线记录/观点演进") mapping to
    {"description": str|None, "routing_scope": str|None}.

    routing_scope is agent-only; description is display-safe.
    """
    p = idx_dir / "scopes.yaml"
    if not p.is_file():
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(raw, dict):
        return {}
    scopes = raw.get("scopes")
    if not isinstance(scopes, dict):
        return {}
    out: dict[str, dict] = {}
    for k, v in scopes.items():
        if not isinstance(k, str) or not isinstance(v, dict):
            continue
        out[k] = {
            "description": v.get("description") if isinstance(v.get("description"), str) else None,
            "routing_scope": v.get("routing_scope") if isinstance(v.get("routing_scope"), str) else None,
        }
    return out


def _node_tag_path(node: "TreeNode") -> str:
    return "/".join(node.path)


def load_synthetic_tags(idx_dir: Path) -> dict[str, str]:
    """Read <idx_dir>/synthetic_tags.yaml.  Maps rel_path -> synthetic tag string.

    Used to give the originally-untagged notes an Auto-derived top-level
    bucket so the page-index has clustering instead of one flat (untagged) bin.
    The note's source file is never modified.
    """
    p = idx_dir / "synthetic_tags.yaml"
    if not p.is_file():
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(raw, dict):
        return {}
    assignments = raw.get("assignments")
    if not isinstance(assignments, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in assignments.items():
        if isinstance(k, str) and isinstance(v, str) and v:
            out[k] = v
    return out


def apply_synthetic_tags(items: list[ManagedItem], overlay: dict[str, str]) -> list[ManagedItem]:
    """Return a new item list where each item with an overlay entry gains the
    synthetic tag APPENDED to its existing tags tuple.  Items without an
    overlay entry are returned unchanged.  This supports dual-track rendering:
    the original user-tag tree and the agent-clustered tree coexist, with each
    overlaid note appearing in both.
    """
    if not overlay:
        return items
    out: list[ManagedItem] = []
    for it in items:
        syn = overlay.get(it.rel_path)
        if not syn:
            out.append(it)
            continue
        # Append synthetic tag to existing tags (preserve original).
        # Dedup defensively (a hand-edited overlay could repeat).
        if syn in it.tags:
            out.append(it)
            continue
        out.append(ManagedItem(
            path=it.path,
            rel_path=it.rel_path,
            source=it.source,
            item_id=it.item_id,
            created_at=it.created_at,
            tags=it.tags + (syn,),
            title=it.title,
            body=it.body,
        ))
    return out


# ---------- renderers ----------


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


def render_recents_json(items: list[ManagedItem], generated_at: str, limit: int = RECENTS_LIMIT) -> str:
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


def render_index_md(tree: TreeNode, generated_at: str, total_items: int, scopes: dict[str, dict] | None = None) -> str:
    scopes = scopes or {}
    lines: list[str] = []
    lines.append("# Context Hub Index")
    lines.append("")
    lines.append(f"_Generated {generated_at} · {total_items} notes · tag-tree view_")
    lines.append("")
    top = sorted(tree.children.values(), key=lambda n: (-n.total_count(), n.name))
    # Push (untagged) and Auto/ (synthetic) to the bottom; user-curated first.
    is_demoted = lambda n: n.name == _UNTAGGED_LABEL or n.name == "Auto"
    user_curated = [n for n in top if not is_demoted(n)]
    demoted = [n for n in top if is_demoted(n)]
    if not user_curated and not demoted:
        lines.append("_(no managed notes yet)_")
        lines.append("")
        return "\n".join(lines)
    for node in user_curated + demoted:
        _render_node_md(node, depth=2, lines=lines, scopes=scopes)
    return "\n".join(lines)


def _render_node_md(node: TreeNode, depth: int, lines: list[str], scopes: dict[str, dict]) -> None:
    header = "#" * min(depth, 6)
    lines.append(f"{header} {node.name} ({node.total_count()})")
    lines.append("")
    entry = scopes.get(_node_tag_path(node))
    if entry and entry.get("description"):
        lines.append(f"_{entry['description']}_")
        lines.append("")
    if node.children:
        for child in sorted(node.children.values(), key=lambda n: (-n.total_count(), n.name)):
            _render_node_md(child, depth + 1, lines, scopes)
    if node.items:
        sorted_items = sorted(node.items, key=lambda i: i.created_at, reverse=True)
        shown = sorted_items[:INLINE_NOTE_CAP]
        for it in shown:
            date = it.created_at.strftime("%Y-%m-%d")
            preview = _preview(it.body, 60).replace("|", r"\|")
            title = it.title or ""
            head = f"{title} · " if title else ""
            lines.append(f"- `{it.rel_path}` · {date} · {head}{preview}")
        if len(sorted_items) > INLINE_NOTE_CAP:
            lines.append(f"- _… +{len(sorted_items) - INLINE_NOTE_CAP} more notes in this exact tag_")
        lines.append("")


def render_tree_json(tree: TreeNode, scopes: dict[str, dict], generated_at: str) -> str:
    """Recursive tag-tree with both description and routing_scope per node.

    Schema:
      {
        "schema_version": 1,
        "generated_at": <iso>,
        "agent_contract": "<contract text>",
        "tree": <node>,
      }
    Node:
      {
        "name": str, "path": "a/b/c", "count": int,
        "description": str|None,   # display-safe
        "routing_scope": str|None, # agent-only, NEVER quote verbatim to user
        "direct_paths": [<rel_path>],  # notes attached exactly at this node
        "children": [<node>...],
      }
    """
    def serialize(node: TreeNode) -> dict:
        tag_path = _node_tag_path(node)
        sc = scopes.get(tag_path, {}) if tag_path else {}
        children = [
            serialize(c)
            for c in sorted(node.children.values(), key=lambda n: (-n.total_count(), n.name))
        ]
        return {
            "name": node.name,
            "path": tag_path,
            "count": node.total_count(),
            "description": sc.get("description"),
            "routing_scope": sc.get("routing_scope"),
            "direct_paths": sorted(it.rel_path for it in node.items),
            "children": children,
        }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "agent_contract": (
            "Each node has `description` (display-safe) and `routing_scope` "
            "(LLM-inferred, agent-only). You MUST use routing_scope to decide which "
            "notes under `direct_paths` (and children's direct_paths) to read, but "
            "NEVER quote routing_scope text to the user as if it were the user's words. "
            "Always cite from the original note files."
        ),
        "tree": serialize(_synth_root_node(tree)),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _synth_root_node(tree: TreeNode) -> "TreeNode":
    """Wrap tree with a synthetic root so serialization is uniform."""
    # tree already has name="" and is the root; serialize it directly
    return tree


# ---------- orchestrator ----------


class IndexLayoutError(RuntimeError):
    pass


def generate_full_index(root: Path) -> dict:
    """Regenerate <root>/_index/INDEX.md, tags.json, recents.json.

    Returns a small dict of counts for the CLI summary.
    """
    items = list(iter_managed(root))
    idx_dir = root / INDEX_DIR_NAME
    if idx_dir.exists() and not idx_dir.is_dir():
        raise IndexLayoutError(f"{idx_dir} exists and is not a directory")
    idx_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    scopes = load_scopes(idx_dir)
    synthetic = load_synthetic_tags(idx_dir)
    items_overlaid = apply_synthetic_tags(items, synthetic)

    tags_json = render_tags_json(items_overlaid, generated_at)
    recents_json = render_recents_json(items_overlaid, generated_at)
    tree = build_tag_tree(items_overlaid)
    index_md = render_index_md(tree, generated_at, total_items=len(items_overlaid), scopes=scopes)
    tree_json = render_tree_json(tree, scopes, generated_at)

    _atomic_write(idx_dir / "tags.json", tags_json)
    _atomic_write(idx_dir / "recents.json", recents_json)
    _atomic_write(idx_dir / "INDEX.md", index_md)
    _atomic_write(idx_dir / "tree.json", tree_json)

    by_source: dict[str, int] = {}
    for it in items:
        by_source[it.source] = by_source.get(it.source, 0) + 1
    return {
        "total": len(items),
        "by_source": by_source,
        "tag_nodes": _count_nodes(tree),
        "scopes_applied": len(scopes),
        "synthetic_tags_applied": len(synthetic),
        "generated_at": generated_at,
    }


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _count_nodes(node: TreeNode) -> int:
    n = 0 if node.name == "" else 1
    for c in node.children.values():
        n += _count_nodes(c)
    return n
