# -*- coding: utf-8 -*-
"""说话人分离（pyannote.audio 3.x）。

设计要点：
1. 模型按 (model, device) 缓存，避免每个任务重复加载（pyannote 加载很慢）。
2. 缺 HF_TOKEN / 模型协议未同意 / 依赖缺失时，不阻断主流程 —— 交由上层决定
   是否降级为「单一说话人 A」。
3. 兼容 pyannote.audio 3.0（Annotation）与 3.1+（DiarizeOutput）两种返回结构。
"""
from __future__ import annotations

import inspect
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..config import settings

ProgressCallback = Callable[[float, str], None]


class DiarizationError(RuntimeError):
    """说话人分离失败。"""


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: str  # 模型原始标签，如 SPEAKER_00


_pipeline_lock = threading.Lock()
_pipeline_cache: dict[str, object] = {}


def _load_pipeline(model_name: str, device: str):
    key = f"{model_name}::{device}"
    with _pipeline_lock:
        if key in _pipeline_cache:
            return _pipeline_cache[key]
        try:
            from pyannote.audio import Pipeline  # type: ignore
        except ImportError as exc:
            raise DiarizationError(
                "未安装 pyannote.audio，请执行：pip install pyannote.audio torch torchaudio"
            ) from exc

        if not settings.hf_token:
            raise DiarizationError(
                "未配置 HF_TOKEN。请在 https://huggingface.co/settings/tokens 生成 Token 填入 .env，"
                "并先同意 pyannote/speaker-diarization-3.1 与 pyannote/segmentation-3.0 的模型协议。"
            )

        try:
            pipeline = Pipeline.from_pretrained(model_name, use_auth_token=settings.hf_token)
        except TypeError:
            # 新版 pyannote 参数名改为 token
            pipeline = Pipeline.from_pretrained(model_name, token=settings.hf_token)
        except Exception as exc:
            raise DiarizationError(
                f"说话人分离模型加载失败：{exc}。请确认已同意模型协议且 HF_TOKEN 有效。"
            ) from exc

        if pipeline is None:
            raise DiarizationError("说话人分离模型加载失败：请确认已在 HuggingFace 同意模型使用协议。")

        if device == "cuda":
            try:
                import torch  # type: ignore

                pipeline.to(torch.device("cuda"))
            except Exception:
                pass  # 显存不足时静默退回 CPU

        _pipeline_cache[key] = pipeline
        return pipeline


def available() -> tuple[bool, str]:
    """返回 (是否可用, 原因)。用于 /api/health 与前端状态提示。"""
    if settings.asr_backend == "mock":
        return True, "mock 演示模式：说话人标签为示例数据，非真实分离结果"
    if not settings.diarization_enabled:
        return False, "配置中已关闭说话人分离"
    try:
        import pyannote.audio  # type: ignore  # noqa: F401
    except ImportError:
        return False, "未安装 pyannote.audio（pip install pyannote.audio torch torchaudio）"
    if not settings.hf_token:
        return False, "未配置 HF_TOKEN，将默认按单一说话人输出"
    return True, "可用"


def mock_diarize(
    duration: float = 0.0,
    num_speakers: int = 0,
    *,
    on_progress: Optional[ProgressCallback] = None,
) -> list[SpeakerTurn]:
    """mock 演示模式的说话人分段：不加载任何模型，按固定节奏轮换 2-6 位说话人。

    仅用于 ASR_BACKEND=mock 时快速跑通「A/B/C 区分 + 时间轴文稿 + 导出」全链路。
    """
    total = float(duration) or 96.0
    count = int(num_speakers) if num_speakers and int(num_speakers) > 0 else 3
    count = max(2, min(count, 6))

    if on_progress:
        on_progress(30.0, "mock 演示模式：生成示例说话人分段…")

    spans = [7.5, 5.5, 8.5, 6.0, 4.5, 6.5]
    turns: list[SpeakerTurn] = []
    cursor = 0.0
    i = 0
    while cursor < total and i < 5000:
        end = min(total, cursor + spans[i % len(spans)])
        if end - cursor < 0.6:
            break
        turns.append(SpeakerTurn(start=round(cursor, 2), end=round(end, 2),
                                 speaker=f"SPEAKER_{i % count:02d}"))
        cursor = end + 0.3
        i += 1

    if on_progress:
        on_progress(100.0, f"mock 演示模式：已生成 {count} 位说话人分段")
    return turns


def diarize(
    audio_path: str | Path,
    *,
    num_speakers: int = 0,
    min_speakers: int = 1,
    max_speakers: int = 20,
    on_progress: Optional[ProgressCallback] = None,
    duration: float = 0.0,
) -> list[SpeakerTurn]:
    """执行说话人分离，返回按时间排序的说话人片段。"""
    if on_progress:
        on_progress(2.0, "正在加载说话人分离模型…")

    device = "cpu"
    try:
        import torch  # type: ignore

        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        pass

    pipeline = _load_pipeline(settings.diarization_model, device)

    kwargs: dict = {}
    if num_speakers and num_speakers > 0:
        kwargs["num_speakers"] = int(num_speakers)
    else:
        kwargs["min_speakers"] = int(min_speakers)
        kwargs["max_speakers"] = int(max_speakers)

    # pyannote 3.1 支持 hook 回调；老版本不支持则跳过
    if on_progress and "hook" in inspect.signature(pipeline.__call__).parameters:
        def hook(step_name: str, step_artifact, file=None, total=None, completed=None):  # noqa: ANN001
            if total and completed is not None:
                pct = min(99.0, float(completed) * 100.0 / float(total))
                on_progress(pct, f"说话人分离中（{step_name}）…")

        kwargs["hook"] = hook

    if on_progress:
        on_progress(5.0, "说话人分离计算中（长音频较慢，请耐心等待）…")

    try:
        output = pipeline(str(audio_path), **kwargs)
    except TypeError:
        kwargs.pop("hook", None)
        output = pipeline(str(audio_path), **kwargs)
    except Exception as exc:
        raise DiarizationError(f"说话人分离失败：{exc}") from exc

    annotation = getattr(output, "speaker_diarization", output)
    turns: list[SpeakerTurn] = []
    try:
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            turns.append(SpeakerTurn(start=float(turn.start), end=float(turn.end), speaker=str(speaker)))
    except AttributeError as exc:  # pragma: no cover
        raise DiarizationError(f"无法解析说话人分离结果：{exc}") from exc

    if not turns:
        raise DiarizationError("说话人分离未返回任何片段")

    turns.sort(key=lambda t: t.start)
    if on_progress:
        on_progress(100.0, f"识别到 {len({t.speaker for t in turns})} 位说话人")
    return turns


def merge_turns(turns: list[SpeakerTurn], gap: float = 0.35) -> list[SpeakerTurn]:
    """合并同一说话人的相邻片段，减少碎片。"""
    merged: list[SpeakerTurn] = []
    for turn in sorted(turns, key=lambda t: t.start):
        if merged and merged[-1].speaker == turn.speaker and turn.start - merged[-1].end <= gap:
            merged[-1].end = max(merged[-1].end, turn.end)
        else:
            merged.append(SpeakerTurn(turn.start, turn.end, turn.speaker))
    return merged
