# -*- coding: utf-8 -*-
"""语音转文字：faster-whisper（本地）/ OpenAI 兼容接口（远程）/ mock（假数据）。

统一输出 ASRSegment 列表，字段与 SRT 对齐：
    start / end（秒）、text、words（可选词级时间戳）
"""
from __future__ import annotations

import json
import mimetypes
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..config import settings

ProgressCallback = Callable[[float, str], None]


class ASRError(RuntimeError):
    """识别失败。"""


@dataclass
class ASRWord:
    start: float
    end: float
    word: str
    probability: float = 0.0


@dataclass
class ASRSegment:
    start: float
    end: float
    text: str
    words: list[ASRWord] = field(default_factory=list)
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0


@dataclass
class ASRResult:
    segments: list[ASRSegment]
    language: str = ""
    language_probability: float = 0.0
    duration: float = 0.0
    backend: str = ""
    model: str = ""


# --------------------------------------------------------------------------
# 本地 faster-whisper
# --------------------------------------------------------------------------
_model_lock = threading.Lock()
_model_cache: dict[tuple[str, str, str], object] = {}


def _resolve_device(device: str) -> str:
    if device and device != "auto":
        return device
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _resolve_compute_type(device: str, compute_type: str) -> str:
    if compute_type and compute_type != "auto":
        return compute_type
    return "float16" if device == "cuda" else "int8"


def _get_whisper_model(model_name: str, device: str, compute_type: str):
    key = (model_name, device, compute_type)
    with _model_lock:
        if key in _model_cache:
            return _model_cache[key]
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:
            raise ASRError("未安装 faster-whisper，请执行：pip install faster-whisper") from exc

        kwargs: dict = {"device": device, "compute_type": compute_type}
        if settings.whisper_cache_dir:
            kwargs["download_root"] = settings.whisper_cache_dir
        try:
            model = WhisperModel(model_name, **kwargs)
        except Exception as exc:
            if device == "cuda":
                # 显存不足 / CUDA 版本不匹配时自动退回 CPU，保证任务能出稿
                model = WhisperModel(model_name, device="cpu", compute_type="int8",
                                     **({"download_root": settings.whisper_cache_dir} if settings.whisper_cache_dir else {}))
                compute_type = "int8"
            else:
                raise ASRError(f"模型加载失败：{exc}") from exc
        _model_cache[key] = model
        return model


def transcribe_local(
    audio_path: str | Path,
    *,
    model_name: str,
    device: str,
    compute_type: str,
    language: Optional[str],
    initial_prompt: Optional[str],
    vad_filter: bool,
    word_timestamps: bool,
    duration: float = 0.0,
    on_progress: Optional[ProgressCallback] = None,
) -> ASRResult:
    device = _resolve_device(device)
    compute_type = _resolve_compute_type(device, compute_type)
    if on_progress:
        on_progress(2.0, f"正在加载模型 {model_name}（{device}/{compute_type}）…")

    model = _get_whisper_model(model_name, device, compute_type)

    try:
        seg_iter, info = model.transcribe(
            str(audio_path),
            language=language or None,
            initial_prompt=initial_prompt or None,
            vad_filter=bool(vad_filter),
            vad_parameters={"min_silence_duration_ms": 400} if vad_filter else None,
            word_timestamps=bool(word_timestamps),
            beam_size=5,
            condition_on_previous_text=False,
        )
    except Exception as exc:
        raise ASRError(f"识别失败：{exc}") from exc

    total = duration or float(getattr(info, "duration", 0.0) or 0.0)
    segments: list[ASRSegment] = []
    for seg in seg_iter:  # 生成器，边转写边推进进度
        words = [
            ASRWord(start=float(w.start), end=float(w.end), word=w.word, probability=float(getattr(w, "probability", 0.0)))
            for w in (getattr(seg, "words", None) or [])
            if w.start is not None and w.end is not None
        ]
        text = (seg.text or "").strip()
        if text:
            segments.append(
                ASRSegment(
                    start=float(seg.start),
                    end=float(seg.end),
                    text=text,
                    words=words,
                    avg_logprob=float(getattr(seg, "avg_logprob", 0.0) or 0.0),
                    no_speech_prob=float(getattr(seg, "no_speech_prob", 0.0) or 0.0),
                )
            )
        if on_progress and total > 0:
            on_progress(min(99.0, float(seg.end) * 100.0 / total), "正在转写语音…")

    return ASRResult(
        segments=segments,
        language=getattr(info, "language", "") or (language or ""),
        language_probability=float(getattr(info, "language_probability", 0.0) or 0.0),
        duration=total,
        backend="faster-whisper",
        model=model_name,
    )


# --------------------------------------------------------------------------
# OpenAI 兼容接口
# --------------------------------------------------------------------------
def transcribe_openai(
    audio_path: str | Path,
    *,
    model_name: str,
    language: Optional[str],
    initial_prompt: Optional[str],
    on_progress: Optional[ProgressCallback] = None,
) -> ASRResult:
    """调用任意 OpenAI 兼容的 /audio/transcriptions 接口（OpenAI / Groq / SiliconFlow / 本地 vLLM）。"""
    if not settings.openai_api_key:
        raise ASRError("未配置 OPENAI_API_KEY，无法使用远程识别引擎")

    try:
        import requests  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ASRError("未安装 requests，请执行：pip install requests") from exc

    audio_path = Path(audio_path)
    if on_progress:
        on_progress(10.0, f"正在上传音频到 {settings.openai_base_url} …")

    url = f"{settings.openai_base_url}/audio/transcriptions"
    mime = mimetypes.guess_type(audio_path.name)[0] or "audio/wav"
    data: dict = {
        "model": model_name or settings.openai_asr_model,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "segment",
    }
    if language:
        data["language"] = language
    if initial_prompt:
        data["prompt"] = initial_prompt

    try:
        with audio_path.open("rb") as fh:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                files={"file": (audio_path.name, fh, mime)},
                data=data,
                timeout=settings.openai_timeout,
            )
    except Exception as exc:
        raise ASRError(f"调用远程识别接口失败：{exc}") from exc

    if resp.status_code >= 400:
        raise ASRError(f"远程识别接口返回 {resp.status_code}：{resp.text[:300]}")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise ASRError("远程识别接口返回内容不是合法 JSON") from exc

    if on_progress:
        on_progress(92.0, "正在解析识别结果…")

    segments: list[ASRSegment] = []
    for item in payload.get("segments") or []:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            ASRSegment(
                start=float(item.get("start") or 0.0),
                end=float(item.get("end") or 0.0),
                text=text,
                avg_logprob=float(item.get("avg_logprob") or 0.0),
                no_speech_prob=float(item.get("no_speech_prob") or 0.0),
            )
        )

    if not segments and payload.get("text"):
        # 部分兼容实现不返回分段，退化为整段一句（用总时长兜底）
        from .audio import duration_of

        segments = [ASRSegment(start=0.0, end=duration_of(audio_path), text=payload["text"].strip())]

    if not segments:
        raise ASRError("远程接口未返回任何文字，请检查音频是否有效或模型是否支持分段时间戳")

    return ASRResult(
        segments=segments,
        language=payload.get("language") or (language or ""),
        duration=segments[-1].end,
        backend="openai-compatible",
        model=data["model"],
    )


# --------------------------------------------------------------------------
# 统一入口
# --------------------------------------------------------------------------
def transcribe(
    audio_path: str | Path,
    *,
    backend: str,
    model_name: str,
    device: str,
    compute_type: str,
    language: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    vad_filter: bool = True,
    word_timestamps: bool = True,
    duration: float = 0.0,
    on_progress: Optional[ProgressCallback] = None,
) -> ASRResult:
    backend = (backend or settings.asr_backend or "faster-whisper").lower()
    try:
        if backend == "mock":
            from .mock import mock_transcribe

            return mock_transcribe(audio_path, duration=duration, on_progress=on_progress)
        if backend == "openai":
            return transcribe_openai(
                audio_path,
                model_name=model_name or settings.openai_asr_model,
                language=language,
                initial_prompt=initial_prompt,
                on_progress=on_progress,
            )
        return transcribe_local(
            audio_path,
            model_name=model_name or settings.whisper_model,
            device=device or settings.whisper_device,
            compute_type=compute_type or settings.whisper_compute_type,
            language=language,
            initial_prompt=initial_prompt,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
            duration=duration,
            on_progress=on_progress,
        )
    except ASRError:
        raise
    except Exception as exc:  # 兜底：任何未预期异常都包装成可读错误
        raise ASRError(f"识别过程出错：{exc}") from exc


def parse_words_json(raw: str | None) -> list[ASRWord]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    return [ASRWord(**item) for item in data]
