from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

import yaml
from markdownify import markdownify as md

from .flomo import Memo


def memo_id(memo: Memo) -> str:
    """Stable id derived from creation time + raw HTML content.

    Same input → same id. Editing a memo upstream changes the id (treated
    as DELETE + ADD on next import, which is consistent with full-mirror).
    """
    h = hashlib.sha1()
    h.update(memo.created_at.isoformat().encode("utf-8"))
    h.update(b"\n")
    h.update(memo.raw_content_html.encode("utf-8"))
    return h.hexdigest()[:16]


def render(memo: Memo) -> tuple[PurePosixPath, str]:
    """Render a Memo to (relative posix path, full file content).

    Path: <YYYY>/<MM>/<DD>/<HHMM>-<memo_id>.md
    """
    mid = memo_id(memo)
    dt = memo.created_at
    rel_path = PurePosixPath(
        f"{dt.year:04d}",
        f"{dt.month:02d}",
        f"{dt.day:02d}",
        f"{dt.hour:02d}{dt.minute:02d}-{mid}.md",
    )

    body = _render_body(memo)
    fm = _render_frontmatter(
        {
            "source": "flomo",
            "memo_id": mid,
            "created_at": dt.isoformat(),
            "tags": list(memo.tags),
        }
    )
    content = f"---\n{fm}---\n\n{body}\n"
    return rel_path, content


def _render_body(memo: Memo) -> str:
    body_md = md(memo.raw_content_html, heading_style="ATX").strip()
    if memo.audio_transcripts:
        for t in memo.audio_transcripts:
            body_md = body_md + "\n\n[audio transcript] " + t.strip()
    return body_md.strip()


def _render_frontmatter(d: dict) -> str:
    return yaml.safe_dump(d, allow_unicode=True, sort_keys=False)
