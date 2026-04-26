from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath

import yaml

from . import render as _render


SOURCE = "obsidian"

_TAG_RE = re.compile(r"(?<![\w/])#([\w/\-]+)", re.UNICODE)
_CREATED_KEYS = ("created", "created_at", "date", "creation_date")
_FM_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")


@dataclass(frozen=True)
class Note:
    vault_path: str  # POSIX-style relative path within the vault
    title: str
    body: str
    created_at: datetime
    tags: tuple[str, ...] = field(default=())


@dataclass
class ParseReport:
    notes: list[Note]
    skipped_empty: int = 0
    skipped_malformed: int = 0


def scan_vault(vault: Path) -> ParseReport:
    """Walk an Obsidian vault directory, parse every `.md` file into a Note.

    Skips:
    - any path that traverses a hidden directory (e.g. `.obsidian/`, `.trash/`)
    - files that fail to read as utf-8 (counted as malformed)
    - notes whose body is empty after stripping frontmatter (counted as empty)
    """
    if not vault.exists():
        raise FileNotFoundError(f"vault not found: {vault}")
    if not vault.is_dir():
        raise NotADirectoryError(f"vault is not a directory: {vault}")

    report = ParseReport(notes=[])
    for path in sorted(vault.rglob("*.md")):
        if not path.is_file():
            continue
        rel = path.relative_to(vault)
        if any(part.startswith(".") for part in rel.parts):
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            report.skipped_malformed += 1
            continue

        try:
            note = _parse_note(rel, path, text)
        except _ParseError:
            report.skipped_malformed += 1
            continue

        if note is None:
            report.skipped_empty += 1
            continue
        report.notes.append(note)
    return report


def note_id(note: Note) -> str:
    """Stable id derived from the note's vault-relative path.

    Edits to body do NOT change the id (so they show up as UPDATE).
    Renames change the id (treated as DELETE old + ADD new).
    """
    h = hashlib.sha1()
    h.update(note.vault_path.encode("utf-8"))
    return h.hexdigest()[:16]


def render(note: Note) -> tuple[PurePosixPath, str]:
    """Render a Note to (relative posix path, full file content)."""
    nid = note_id(note)
    fm = {
        "source": SOURCE,
        "note_id": nid,
        "created_at": note.created_at.isoformat(),
        "tags": list(note.tags),
        "title": note.title,
        "vault_path": note.vault_path,
    }
    rel_path = _render.make_path(note.created_at, nid)
    content = _render.make_file_content(fm, note.body)
    return rel_path, content


class _ParseError(Exception):
    pass


def _parse_note(rel: Path, path: Path, text: str) -> Note | None:
    fm, body = _split_frontmatter(text)
    body = body.strip()
    if not body:
        return None

    fallback = _file_mtime_local(path)
    created_at = _parse_created(fm, fallback)

    fm_tags = _tags_from_frontmatter(fm)
    inline_tags = _TAG_RE.findall(body)
    tags = _dedupe_preserve_order(fm_tags + inline_tags)

    vault_path = rel.as_posix()
    title = rel.stem

    return Note(
        vault_path=vault_path,
        title=title,
        body=body,
        created_at=created_at,
        tags=tuple(tags),
    )


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Strip a leading `---\\n...\\n---\\n` block. Returns (frontmatter, body).

    If there is no leading frontmatter (or it's malformed), returns ({}, text).
    """
    if not text.startswith("---"):
        return {}, text
    # tolerate either `---\n` or `---\r\n`
    after_open = text.split("\n", 1)
    if len(after_open) < 2 or after_open[0].strip() != "---":
        return {}, text
    rest = after_open[1]
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    block = rest[:end]
    # body starts after the closing `---` and the following newline
    after_close = rest[end + len("\n---"):]
    if after_close.startswith("\r\n"):
        after_close = after_close[2:]
    elif after_close.startswith("\n"):
        after_close = after_close[1:]
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, after_close
    return data, after_close


def _parse_created(fm: dict, fallback: datetime) -> datetime:
    for key in _CREATED_KEYS:
        v = fm.get(key)
        if v is None:
            continue
        parsed = _coerce_to_datetime(v)
        if parsed is not None:
            return parsed
    return fallback


def _coerce_to_datetime(v) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.astimezone()
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day).astimezone()
    if isinstance(v, (int, float)):
        # heuristically detect millisecond epochs
        ts = float(v)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts).astimezone()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            d = datetime.fromisoformat(s)
            return d if d.tzinfo else d.astimezone()
        except ValueError:
            pass
        for fmt in _FM_TIME_FORMATS:
            try:
                d = datetime.strptime(s, fmt)
                return d.astimezone()
            except ValueError:
                continue
    return None


def _tags_from_frontmatter(fm: dict) -> list[str]:
    raw = fm.get("tags")
    if raw is None:
        raw = fm.get("tag")
    if raw is None:
        return []
    if isinstance(raw, str):
        # accept comma- or whitespace-separated, with optional leading '#'
        parts = [p.strip().lstrip("#") for p in raw.replace(",", " ").split()]
        return [p for p in parts if p]
    if isinstance(raw, list):
        out = []
        for t in raw:
            if t is None:
                continue
            s = str(t).strip().lstrip("#")
            if s:
                out.append(s)
        return out
    return []


def _dedupe_preserve_order(items) -> list[str]:
    seen = set()
    out = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


def _file_mtime_local(path: Path) -> datetime:
    st = path.stat()
    ts = getattr(st, "st_birthtime", None) or st.st_mtime
    return datetime.fromtimestamp(ts).astimezone()
