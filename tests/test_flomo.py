from __future__ import annotations

from context_hub import flomo


def test_parse_html_extracts_memos(simple_memos_html):
    report = flomo.parse_html(simple_memos_html)
    # 4 memo blocks, 1 is image-only and gets skipped
    assert len(report.memos) == 3
    assert report.skipped_empty == 1
    assert report.skipped_malformed == 0


def test_parse_html_extracts_tags(simple_memos_html):
    report = flomo.parse_html(simple_memos_html)
    first = report.memos[0]  # 2026-04-25 09:31:14, has #日记 #想法/灵感
    assert "日记" in first.tags
    assert "想法/灵感" in first.tags


def test_parse_html_extracts_audio_transcripts(simple_memos_html):
    report = flomo.parse_html(simple_memos_html)
    audio_memo = next(m for m in report.memos if m.audio_transcripts)
    assert audio_memo.audio_transcripts == ("这是转录文本。",)


def test_parse_zip_roundtrip(fixture_zip):
    report = flomo.parse_zip(fixture_zip)
    assert len(report.memos) == 3
