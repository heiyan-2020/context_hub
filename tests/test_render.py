from __future__ import annotations

from datetime import datetime, timezone, timedelta

from context_hub.flomo import Memo
from context_hub.render import memo_id, render


TZ = timezone(timedelta(hours=8))


def make_memo(**overrides) -> Memo:
    base = dict(
        created_at=datetime(2026, 4, 25, 9, 31, 14, tzinfo=TZ),
        raw_content_html="<p>hello #想法</p>",
        audio_transcripts=(),
        tags=("想法",),
    )
    base.update(overrides)
    return Memo(**base)


def test_memo_id_is_stable():
    a = make_memo()
    b = make_memo()
    assert memo_id(a) == memo_id(b)


def test_memo_id_changes_with_content():
    a = make_memo()
    b = make_memo(raw_content_html="<p>different</p>")
    assert memo_id(a) != memo_id(b)


def test_memo_id_changes_with_time():
    a = make_memo()
    b = make_memo(created_at=datetime(2026, 4, 25, 9, 31, 15, tzinfo=TZ))
    assert memo_id(a) != memo_id(b)


def test_render_path_format():
    rel, _ = render(make_memo())
    parts = rel.parts
    assert parts[0] == "2026"
    assert parts[1] == "04"
    assert parts[2] == "25"
    assert parts[3].startswith("0931-")
    assert parts[3].endswith(".md")


def test_render_content_has_frontmatter_and_body():
    _, content = render(make_memo())
    assert content.startswith("---\n")
    assert "source: flomo" in content
    assert "memo_id:" in content
    assert "created_at: '2026-04-25T09:31:14+08:00'" in content
    assert "tags:" in content
    # body comes after second ---
    body_start = content.index("\n---\n", 4) + len("\n---\n")
    body = content[body_start:].strip()
    assert "hello" in body
    assert "#想法" in body  # tag preserved inline


def test_render_is_byte_stable():
    """Same memo input → identical output. Critical for diff to converge."""
    a = render(make_memo())
    b = render(make_memo())
    assert a == b


def test_render_appends_audio_transcripts():
    memo = make_memo(audio_transcripts=("第一段", "第二段"))
    _, content = render(memo)
    assert "[audio transcript] 第一段" in content
    assert "[audio transcript] 第二段" in content
