from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath

import yaml


def make_path(created_at: datetime, item_id: str) -> PurePosixPath:
    """Time-based hub path: <YYYY>/<MM>/<DD>/<HHMM>-<item_id>.md."""
    dt = created_at
    return PurePosixPath(
        f"{dt.year:04d}",
        f"{dt.month:02d}",
        f"{dt.day:02d}",
        f"{dt.hour:02d}{dt.minute:02d}-{item_id}.md",
    )


def make_file_content(frontmatter: dict, body: str) -> str:
    """Serialize frontmatter dict + body into the canonical hub file format.

    Frontmatter is dumped with insertion order preserved (sort_keys=False),
    so callers control field ordering.
    """
    fm = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
    return f"---\n{fm}---\n\n{body.strip()}\n"
