# -*- coding: utf-8 -*-
"""音频处理：ffmpeg 定位、抽轨、时长探测、裁剪。

所有对外函数都只依赖标准库 + 可选 imageio-ffmpeg 兜底。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..config import settings

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1

VIDEO_AUDIO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".webm", ".m4v", ".ts", ".mpeg", ".mpg", ".3gp",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".amr", ".aiff",
}


class FFmpegNotFoundError(RuntimeError):
    """系统里找不到 ffmpeg。"""


class AudioProcessError(RuntimeError):
    """ffmpeg / ffprobe 执行失败。"""


@lru_cache(maxsize=1)
def resolve_ffmpeg() -> str:
    """按 环境变量 → PATH → imageio-ffmpeg 的顺序找 ffmpeg。"""
    if settings.ffmpeg_binary and Path(settings.ffmpeg_binary).exists():
        return settings.ffmpeg_binary
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # 可选依赖
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise FFmpegNotFoundError(
            "未找到 ffmpeg，请先安装并加入 PATH（Windows 可 winget install Gyan.FFmpeg），"
            "或在 .env 中设置 FFMPEG_BINARY 指向 ffmpeg 可执行文件。"
        ) from exc


@lru_cache(maxsize=1)
def resolve_ffprobe() -> str | None:
    """ffprobe 通常与 ffmpeg 同目录；找不到返回 None（时长会退化为按文件大小估算）。"""
    found = shutil.which("ffprobe")
    if found:
        return found
    try:
        ffmpeg_path = Path(resolve_ffmpeg())
    except FFmpegNotFoundError:
        return None  # 没有 ffmpeg 时不阻断流程：wav 走内置时长估算
    candidate = ffmpeg_path.with_name("ffprobe" + ffmpeg_path.suffix)
    return str(candidate) if candidate.exists() else None


def ffmpeg_available() -> bool:
    try:
        resolve_ffmpeg()
        return True
    except FFmpegNotFoundError:
        return False


def _run(cmd: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover
        raise AudioProcessError(f"命令执行超时（>{timeout}s）：{' '.join(cmd[:4])} …") from exc


def is_media_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_AUDIO_EXTENSIONS


def extract_audio(media_path: str | Path, workdir: str | Path, *,
                  sample_rate: int = TARGET_SAMPLE_RATE, timeout: int = 3600) -> Path:
    """把任意音视频文件抽成 16kHz 单声道 wav（ASR / 说话人分离的标准输入）。"""
    media_path = Path(media_path)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = workdir / "audio_16k.wav"

    if media_path.suffix.lower() == ".wav" and media_path.stat().st_size > 44:
        probe = probe_audio_info(media_path)
        if probe.get("sample_rate") == sample_rate and probe.get("channels") == TARGET_CHANNELS:
            if media_path.resolve() != out_path.resolve():
                shutil.copy2(media_path, out_path)
            return out_path

    cmd = [
        resolve_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(media_path),
        "-vn",                      # 丢弃视频轨
        "-sn", "-dn",               # 丢弃字幕轨 / 数据轨
        "-ac", str(TARGET_CHANNELS),
        "-ar", str(sample_rate),
        "-acodec", "pcm_s16le",
        str(out_path),
    ]
    result = _run(cmd, timeout=timeout)
    if result.returncode != 0 or not out_path.exists():
        stderr = (result.stderr or b"").decode("utf-8", "ignore").strip()
        raise AudioProcessError(f"音频提取失败：{stderr[-500:] or '未知错误'}")
    return out_path


def wav_header_info(path: str | Path) -> dict | None:
    """直接读 WAV 头（标准库），无需 ffprobe。失败返回 None。"""
    try:
        with wave.open(str(path), "rb") as reader:
            rate = reader.getframerate() or 0
            frames = reader.getnframes()
            width = reader.getsampwidth()
            return {
                "sample_rate": rate,
                "channels": reader.getnchannels(),
                "duration": (frames / float(rate)) if rate else None,
                "codec": f"pcm_s{width * 8}le" if width else None,
            }
    except Exception:
        return None


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def duration_via_ffmpeg(path: str | Path) -> float | None:
    """无 ffprobe 时，从 `ffmpeg -i` 的 stderr 里解析时长（imageio-ffmpeg 场景）。"""
    try:
        ffmpeg = resolve_ffmpeg()
    except FFmpegNotFoundError:
        return None
    result = _run([ffmpeg, "-hide_banner", "-i", str(path)], timeout=120)
    text = (result.stderr or b"").decode("utf-8", "ignore")
    match = _DURATION_RE.search(text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def probe_audio_info(path: str | Path) -> dict:
    """返回 {duration, sample_rate, channels, codec}，探测失败时字段为 None。

    优先级：ffprobe → WAV 头解析 → 按文件大小估算（16bit 单声道）。
    """
    path = Path(path)
    info: dict = {"duration": None, "sample_rate": None, "channels": None, "codec": None}
    ffprobe = resolve_ffprobe()
    if ffprobe:
        cmd = [
            ffprobe, "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels,codec_name,duration",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ]
        result = _run(cmd, timeout=120)
        if result.returncode == 0:
            try:
                data = json.loads((result.stdout or b"{}").decode("utf-8", "ignore"))
            except ValueError:
                data = {}
            stream = (data.get("streams") or [{}])[0]
            fmt = data.get("format") or {}
            for key, raw in (
                ("sample_rate", stream.get("sample_rate")),
                ("channels", stream.get("channels")),
                ("codec", stream.get("codec_name")),
                ("duration", stream.get("duration") or fmt.get("duration")),
            ):
                try:
                    info[key] = float(raw) if raw is not None else None
                    if key in {"sample_rate", "channels"} and info[key] is not None:
                        info[key] = int(info[key])
                except (TypeError, ValueError):
                    info[key] = None

    if path.suffix.lower() == ".wav":
        header = wav_header_info(path)
        if header:
            for key in ("sample_rate", "channels", "codec", "duration"):
                if info.get(key) is None:
                    info[key] = header.get(key)

    if info["duration"] is None and path.suffix.lower() == ".wav":
        # 16bit 单声道 wav：数据字节数 / (采样率 * 2)
        rate = info["sample_rate"] or TARGET_SAMPLE_RATE
        try:
            size = path.stat().st_size
        except OSError:
            return info
        info["duration"] = max(0.0, (size - 44) / float(rate * 2))

    if info["duration"] is None:
        # 没有 ffprobe（例如只装了 imageio-ffmpeg）时，退化为解析 ffmpeg 输出
        info["duration"] = duration_via_ffmpeg(path)
    return info


def duration_of(path: str | Path) -> float:
    info = probe_audio_info(path)
    return float(info.get("duration") or 0.0)
