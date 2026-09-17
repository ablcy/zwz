# -*- coding: utf-8 -*-
"""导出：TXT / SRT / VTT / Markdown / JSON。"""
from __future__ import annotations

import json
from typing import Iterable

from ..utils import fmt_duration, fmt_timestamp
from .align import AlignedSegment

EXPORT_FORMATS = ("txt", "srt", "vtt", "md", "json")

MIME_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "json": "application/json; charset=utf-8",
}

# 按说话人数切换 SRT 前缀风格：1 人不用前缀，多人用 [A] 前缀
def _prefix(speaker: str, speaker_count: int) -> str:
    return f"[{speaker}] " if speaker_count > 1 else ""


def to_txt(segments: Iterable[AlignedSegment], speaker_count: int = 1, *,
           with_timestamp: bool = True, with_speaker: bool = True, meta: dict | None = None) -> str:
    lines: list[str] = []
    if meta:
        lines.append(f"# {meta.get('title') or '转写文稿'}")
        if meta.get("source_url"):
            lines.append(f"# 来源：{meta['source_url']}")
        lines.append(f"# 时长：{fmt_duration(meta.get('duration', 0))}    说话人：{speaker_count} 位")
        lines.append("")
    for seg in segments:
        parts = []
        if with_timestamp:
            parts.append(f"[{fmt_timestamp(seg.start)} - {fmt_timestamp(seg.end)}]")
        if with_speaker and speaker_count > 1:
            parts.append(f"{seg.speaker}:")
        parts.append(seg.text)
        lines.append(" ".join(parts))
    return "\n".join(lines) + "\n"


def to_srt(segments: Iterable[AlignedSegment], speaker_count: int = 1) -> str:
    blocks: list[str] = []
    for i, seg in enumerate(segments, start=1):
        start = fmt_timestamp(seg.start, with_ms=True)
        end = fmt_timestamp(max(seg.end, seg.start + 0.2), with_ms=True)
        blocks.append(f"{i}\n{start} --> {end}\n{_prefix(seg.speaker, speaker_count)}{seg.text}\n")
    return "\n".join(blocks)


def to_vtt(segments: Iterable[AlignedSegment], speaker_count: int = 1) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        start = fmt_timestamp(seg.start, with_ms=True).replace(",", ".")
        end = fmt_timestamp(max(seg.end, seg.start + 0.2), with_ms=True).replace(",", ".")
        lines.append(f"{start} --> {end}")
        lines.append(f"{_prefix(seg.speaker, speaker_count)}{seg.text}")
        lines.append("")
    return "\n".join(lines)


def to_markdown(segments: Iterable[AlignedSegment], speaker_count: int = 1, meta: dict | None = None) -> str:
    lines: list[str] = []
    if meta:
        lines.append(f"# {meta.get('title') or '转写文稿'}")
        if meta.get("source_url"):
            lines.append(f"> 来源：{meta['source_url']}")
        lines.append(f"> 时长 {fmt_duration(meta.get('duration', 0))} · 说话人 {speaker_count} 位")
        lines.append("")
        lines.append("| 时间 | 说话人 | 内容 |")
        lines.append("| --- | --- | --- |")
        for seg in segments:
            text = seg.text.replace("|", "\\|")
            lines.append(f"| {fmt_timestamp(seg.start)} - {fmt_timestamp(seg.end)} | {seg.speaker} | {text} |")
    else:
        for seg in segments:
            lines.append(f"**[{fmt_timestamp(seg.start)}] {seg.speaker}**：{seg.text}")
            lines.append("")
    return "\n".join(lines) + "\n"


def to_json(segments: Iterable[AlignedSegment], speaker_count: int = 1, meta: dict | None = None) -> str:
    payload = {
        "meta": meta or {},
        "speaker_count": speaker_count,
        "segments": [
            {
                "index": seg.index,
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "speaker": seg.speaker,
                "text": seg.text,
                "words": seg.words,
            }
            for seg in segments
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def export(fmt: str, segments: Iterable[AlignedSegment], speaker_count: int = 1, meta: dict | None = None) -> str:
    fmt = (fmt or "txt").lower()
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"不支持的导出格式：{fmt}，可选 {', '.join(EXPORT_FORMATS)}")
    segments = list(segments)
    if fmt == "txt":
        return to_txt(segments, speaker_count, meta=meta)
    if fmt == "srt":
        return to_srt(segments, speaker_count)
    if fmt == "vtt":
        return to_vtt(segments, speaker_count)
    if fmt == "md":
        return to_markdown(segments, speaker_count, meta)
    return to_json(segments, speaker_count, meta)
