from __future__ import annotations

import io
import zipfile
from pathlib import Path
from textwrap import dedent

import pytest


def managed_md(root: Path) -> list[Path]:
    """All `*.md` files under root, excluding the hub-owned `_index/` directory."""
    return [
        p
        for p in root.rglob("*.md")
        if p.is_file() and "_index" not in p.relative_to(root).parts
    ]


def make_flomo_html(memos_html: str) -> bytes:
    return dedent(
        f"""\
        <html><head><title>flomo</title></head>
        <body>
          <div class="memos">
        {memos_html}
          </div>
        </body></html>
        """
    ).encode("utf-8")


def memo_block(time: str, content_html: str, files_html: str = "") -> str:
    return dedent(
        f"""\
        <div class="memo">
          <div class="time">{time}</div>
          <div class="content">{content_html}</div>
          <div class="files">{files_html}</div>
        </div>
        """
    )


@pytest.fixture
def simple_memos_html() -> bytes:
    blocks = "\n".join(
        [
            memo_block(
                "2026-04-25 09:31:14",
                "<p>第一条 #日记 #想法/灵感</p>",
            ),
            memo_block(
                "2026-04-24 22:18:03",
                "<p>第二条</p><ul><li>有列表</li><li>多行</li></ul>",
            ),
            memo_block(
                "2026-04-24 12:00:00",
                "",
                files_html='<img src="file/2026-04-24/x/foo.png" alt="img"/>',
            ),  # image-only memo, should be skipped
            memo_block(
                "2026-04-23 08:05:09",
                "<p>含音频</p>",
                files_html=(
                    '<div class="audio-player">'
                    '<audio src="file/x.m4a"></audio>'
                    '<div class="audio-player__content">这是转录文本。</div>'
                    "</div>"
                ),
            ),
        ]
    )
    return make_flomo_html(blocks)


@pytest.fixture
def fixture_zip(tmp_path: Path, simple_memos_html: bytes) -> Path:
    zp = tmp_path / "flomo-fixture.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("flomo@user-20260425/", "")
        zf.writestr("flomo@user-20260425/user的笔记.html", simple_memos_html)
    zp.write_bytes(buf.getvalue())
    return zp
