# -*- coding: utf-8 -*-
"""Mock 引擎：不加载任何模型，生成结构完整的多说话人假文稿。

用途：① 无 GPU / 未配 HF_TOKEN 时快速跑通前后端链路；
     ② 前端开发与演示；③ 自动化冒烟测试。
启用方式：.env 中 ASR_BACKEND=mock，或 python run.py --mock
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Callable, Optional

from .asr import ASRResult, ASRSegment

ProgressCallback = Callable[[float, str], None]

_SCRIPT: list[tuple[str, str]] = [
    ("A", "大家好，欢迎回到本期节目，今天我们聊一个很多人关心的话题。"),
    ("B", "对，就是怎么把长视频里的内容快速变成可以检索、可以复用的文字。"),
    ("A", "先说一下我们为什么需要这个功能，其实核心就两个字，效率。"),
    ("B", "没错，比如做内容的同学，一条十分钟的口播视频，手动扒稿要半小时以上。"),
    ("A", "而且不止慢，还容易漏字，尤其是多人对话的时候分不清谁在说。"),
    ("C", "我补充一点，会议录音、访谈素材、课程录像，其实都有同样的需求。"),
    ("B", "所以我们这次的做法是，先用模型把音轨抽出来，再做语音识别。"),
    ("A", "然后用说话人分离技术，把不同的人用 A、B、C 这样的标签区分开。"),
    ("C", "最后导出的时候，既可以要纯文稿，也可以要带时间轴的 SRT 字幕。"),
    ("B", "整个流程跑完，十分钟的视频大概两三分钟就能出稿，效率提升非常明显。"),
    ("A", "如果对准确率有更高要求，还可以换成更大的模型，或者接远程接口。"),
    ("C", "是的，另外提醒一句，涉及隐私的素材建议全程在本地处理，不要上传到第三方。"),
    ("A", "好，那这一期就先聊到这里，如果觉得有帮助，记得点个关注。"),
    ("B", "我们下期再见。"),
]


def mock_transcribe(
    audio_path: str | Path,
    *,
    duration: float = 0.0,
    on_progress: Optional[ProgressCallback] = None,
) -> ASRResult:
    from .audio import duration_of

    if duration <= 0:
        try:
            duration = duration_of(audio_path)
        except Exception:
            duration = 0.0
    if duration <= 20:
        duration = 30.0  # 演示时长下限：保证短音频也能展示多说话人分段

    rng = random.Random(20240917)
    segments: list[ASRSegment] = []
    cursor = 0.0
    i = 0
    while cursor < duration and i < 2000:
        speaker, text = _SCRIPT[i % len(_SCRIPT)]
        rate = 4.2 + rng.random() * 1.4  # 每秒约 4~5.5 个字
        span = max(1.6, len(text) / rate)
        end = min(duration, cursor + span)
        if end - cursor < 0.6:
            break
        segments.append(
            ASRSegment(
                start=round(cursor, 2),
                end=round(end, 2),
                text=text,
                avg_logprob=-0.18,
                no_speech_prob=0.01,
            )
        )
        cursor = end + 0.25
        if on_progress and duration > 0:
            on_progress(min(99.0, cursor * 100.0 / duration), "正在转写语音（mock）…")
        i += 1

    return ASRResult(
        segments=segments,
        language="zh",
        language_probability=0.99,
        duration=duration,
        backend="mock",
        model="mock-zh-demo",
    )
