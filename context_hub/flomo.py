from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Memo:
    created_at: datetime
    raw_content_html: str
    audio_transcripts: tuple[str, ...] = ()
    tags: tuple[str, ...] = field(default=())


@dataclass
class ParseReport:
    memos: list[Memo]
    skipped_empty: int = 0
    skipped_malformed: int = 0


_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_TAG_RE = re.compile(r"#([\w/]+)", re.UNICODE)


def parse_zip(zip_path: Path) -> ParseReport:
    """Parse a Flomo export zip and return memos + a report.

    Looks for a single `*的笔记.html` index inside, parses every `.memo` div.
    Memos with no text body and no audio transcript are skipped (counted).
    """
    with zipfile.ZipFile(zip_path) as zf:
        html_name = _find_index_html(zf)
        with zf.open(html_name) as f:
            html_bytes = f.read()
    return parse_html(html_bytes)


def parse_html(html_bytes: bytes) -> ParseReport:
    soup = BeautifulSoup(html_bytes, "html.parser")
    report = ParseReport(memos=[])

    for div in soup.select("div.memo"):
        try:
            memo = _parse_one(div)
        except _ParseError:
            report.skipped_malformed += 1
            continue
        if memo is None:
            report.skipped_empty += 1
            continue
        report.memos.append(memo)
    return report


class _ParseError(Exception):
    pass


def _parse_one(div) -> Memo | None:
    time_el = div.select_one(".time")
    content_el = div.select_one(".content")
    if time_el is None or content_el is None:
        raise _ParseError("missing .time or .content")

    time_text = time_el.get_text(strip=True)
    try:
        created_naive = datetime.strptime(time_text, _TIME_FMT)
    except ValueError as e:
        raise _ParseError(f"bad time: {time_text!r}") from e
    created_at = created_naive.astimezone()  # attach system local tz

    raw_content_html = content_el.decode_contents().strip()

    audio_transcripts: list[str] = []
    files_el = div.select_one(".files")
    if files_el is not None:
        for ap in files_el.select(".audio-player__content"):
            text = ap.get_text("\n", strip=True)
            if text:
                audio_transcripts.append(text)

    text_only = content_el.get_text(" ", strip=True)
    if not text_only and not audio_transcripts:
        return None  # purely image memo, skip

    tags = tuple(_TAG_RE.findall(text_only))

    return Memo(
        created_at=created_at,
        raw_content_html=raw_content_html,
        audio_transcripts=tuple(audio_transcripts),
        tags=tags,
    )


def _find_index_html(zf: zipfile.ZipFile) -> str:
    candidates = [n for n in zf.namelist() if n.endswith(".html") and not n.endswith("/")]
    if not candidates:
        raise ValueError("no .html index file found in zip")
    # prefer the one matching `*的笔记.html`; fall back to the only/first .html
    preferred = [c for c in candidates if c.endswith("的笔记.html")]
    if preferred:
        return preferred[0]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(f"ambiguous html files in zip: {candidates}")
