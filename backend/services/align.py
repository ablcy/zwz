# -*- coding: utf-8 -*-
"""对齐：把 ASR 文稿片段与说话人时间段匹配，生成带 A/B/C 标签的分段文稿。

策略：
1. 逐条 ASR 片段与说话人片段求时间重叠，取重叠最多者；
2. 完全无重叠（ASR 比分离结果略长/略短）时，取时间中心最近的说话人；
3. 按"首次出现顺序"把模型原始标签（SPEAKER_00）映射为 A / B / C …；
4. 合并同一说话人、间隔极小的相邻片段，让文稿更接近自然句。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..utils import speaker_color, speaker_letter
from .asr import ASRSegment
from .diarization import SpeakerTurn, merge_turns

UNKNOWN_SPEAKER = "UNKNOWN"


@dataclass
class AlignedSegment:
    index: int
    start: float
    end: float
    text: str
    speaker: str          # A / B / C
    speaker_raw: str      # 模型原始标签或 UNKNOWN
    words: list[dict] = field(default_factory=list)


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _pick_speaker(segment: ASRSegment, turns: list[SpeakerTurn]) -> str:
    if not turns:
        return UNKNOWN_SPEAKER

    best_speaker, best_overlap = None, 0.0
    for turn in turns:
        if turn.start >= segment.end and turn.end >= segment.end and best_overlap > 0:
            continue
        ov = _overlap(segment.start, segment.end, turn.start, turn.end)
        if ov > best_overlap:
            best_overlap, best_speaker = ov, turn.speaker
    if best_speaker is not None and best_overlap > 0:
        return best_speaker

    # 无重叠 → 找时间中心最近的片段
    center = (segment.start + segment.end) / 2.0
    nearest = min(turns, key=lambda t: abs((t.start + t.end) / 2.0 - center))
    return nearest.speaker


def align(
    asr_segments: list[ASRSegment],
    turns: list[SpeakerTurn] | None,
    *,
    merge_gap: float = 0.8,
    merge_max_chars: int = 220,
) -> tuple[list[AlignedSegment], list[dict]]:
    """返回 (对齐后的分段列表, 说话人统计信息)。"""
    turns = merge_turns(turns) if turns else []

    ordered_speakers: list[str] = []
    raw_to_label: dict[str, str] = {}

    def label_of(raw: str) -> str:
        if raw not in raw_to_label:
            raw_to_label[raw] = speaker_letter(len(ordered_speakers))
            ordered_speakers.append(raw)
        return raw_to_label[raw]

    rows: list[AlignedSegment] = []
    for seg in asr_segments:
        raw = _pick_speaker(seg, turns)
        rows.append(
            AlignedSegment(
                index=len(rows),
                start=float(seg.start),
                end=float(seg.end),
                text=seg.text.strip(),
                speaker=label_of(raw),
                speaker_raw=raw,
                words=[
                    {"start": w.start, "end": w.end, "word": w.word, "probability": w.probability}
                    for w in seg.words
                ],
            )
        )

    rows = _merge_adjacent(rows, merge_gap=merge_gap, merge_max_chars=merge_max_chars)
    for i, row in enumerate(rows):
        row.index = i

    stats = _speaker_stats(rows)
    return rows, stats


def _merge_adjacent(rows: list[AlignedSegment], *, merge_gap: float, merge_max_chars: int) -> list[AlignedSegment]:
    """同一说话人、间隔 <= merge_gap、合并后不超过长度上限的片段，合并为一行。"""
    merged: list[AlignedSegment] = []
    for row in rows:
        if not merged:
            merged.append(row)
            continue
        last = merged[-1]
        same_speaker = last.speaker == row.speaker
        close_enough = row.start - last.end <= merge_gap
        short_enough = len(last.text) + len(row.text) <= merge_max_chars
        if same_speaker and close_enough and short_enough:
            last.end = max(last.end, row.end)
            joiner = "" if _needs_no_space(last.text[-1:], row.text[:1]) else " "
            last.text = f"{last.text}{joiner}{row.text}".strip()
            last.words.extend(row.words)
        else:
            merged.append(row)
    return merged


def _needs_no_space(tail: str, head: str) -> bool:
    """中文/日文之间不加空格，其余加空格。"""
    if not tail or not head:
        return False
    cjk = lambda ch: "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff" or "\uac00" <= ch <= "\ud7af"
    return cjk(tail) or cjk(head)


def _speaker_stats(rows: list[AlignedSegment]) -> list[dict]:
    buckets: dict[str, dict] = {}
    total_speech = 0.0
    for row in rows:
        item = buckets.setdefault(
            row.speaker,
            {"id": row.speaker, "label": row.speaker, "seconds": 0.0, "segment_count": 0, "color": ""},
        )
        dur = max(0.0, row.end - row.start)
        item["seconds"] += dur
        item["segment_count"] += 1
        total_speech += dur

    stats: list[dict] = []
    for idx, (label, item) in enumerate(sorted(buckets.items())):
        item["seconds"] = round(item["seconds"], 1)
        item["percent"] = round(item["seconds"] * 100.0 / total_speech, 1) if total_speech > 0 else 0.0
        item["color"] = speaker_color(idx)
        stats.append(item)
    stats.sort(key=lambda s: s["label"])
    return stats


def single_speaker_rows(asr_segments: list[ASRSegment], *, merge_gap: float = 0.8,
                        merge_max_chars: int = 220) -> tuple[list[AlignedSegment], list[dict]]:
    """无说话人信息时的降级路径：全部标为 A。"""
    rows = [
        AlignedSegment(index=i, start=float(s.start), end=float(s.end), text=s.text.strip(),
                       speaker="A", speaker_raw=UNKNOWN_SPEAKER,
                       words=[{"start": w.start, "end": w.end, "word": w.word, "probability": w.probability}
                              for w in s.words])
        for i, s in enumerate(asr_segments)
        if s.text.strip()
    ]
    rows = _merge_adjacent(rows, merge_gap=merge_gap, merge_max_chars=merge_max_chars)
    for i, row in enumerate(rows):
        row.index = i
    return rows, _speaker_stats(rows)
