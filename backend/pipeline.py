# -*- coding: utf-8 -*-
"""任务流水线编排：下载 → 抽音频 → 转写 → 说话人分离 → 对齐 → 落盘。

进度区间（0-100）：
    downloading   0  → 30
    extracting   30  → 38
    transcribing 38  → 74
    diarizing    74  → 92
    aligning     92  → 98
    exporting    98  → 100
"""
from __future__ import annotations

import json
import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import settings
from .store import Task, store
from .utils import detect_platform, fmt_duration, speaker_color

_EXECUTOR = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="voxscript")

_SPAN = {
    "downloading": (0.0, 30.0),
    "extracting": (30.0, 38.0),
    "transcribing": (38.0, 74.0),
    "diarizing": (74.0, 92.0),
    "aligning": (92.0, 98.0),
    "exporting": (98.0, 100.0),
}


def submit(task: Task) -> None:
    _EXECUTOR.submit(_run, task.task_id)


def _scale(stage: str, inner_percent: float) -> float:
    lo, hi = _SPAN.get(stage, (0.0, 100.0))
    return lo + (hi - lo) * max(0.0, min(100.0, inner_percent)) / 100.0


def _reporter(task_id: str, stage: str, message: str = ""):
    def report(percent: float, msg: str | None = None) -> None:
        store.progress(task_id, stage=stage, percent=_scale(stage, percent), message=msg or message)

    return report


def _run(task_id: str) -> None:
    task = store.get(task_id)
    if task is None:
        return
    try:
        _execute(task)
    except Exception as exc:  # 任何异常都要落到任务状态里，不能静默
        detail = traceback.format_exc(limit=3)
        store.update(task_id, status="failed", stage="failed", error=str(exc), message=f"处理失败：{exc}")
        _write_error_log(task, detail)
        print(f"[voxscript] 任务 {task_id} 失败：{exc}\n{detail}")


def _execute(task: Task) -> None:
    from .services import asr as asr_service
    from .services import audio as audio_service
    from .services import diarization as diar_service
    from .services import downloader, exporter
    from .services.align import align, single_speaker_rows

    task_id = task.task_id
    workdir = task.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    opts = task.options or {}

    # ---------------- 1. 获取媒体 ----------------
    if task.source_type == "url":
        store.progress(task_id, stage="downloading", percent=_scale("downloading", 2.0),
                       message="正在解析视频链接…")
        media = downloader.download(
            task.source.get("url", ""),
            workdir,
            on_progress=_reporter(task_id, "downloading", "正在下载媒体流…"),
        )
        store.update(
            task_id,
            media_path=str(media.path),
            source={
                **task.source,
                "title": media.title,
                "uploader": media.uploader,
                "platform": media.platform or detect_platform(task.source.get("url", "")),
                "webpage_url": media.webpage_url,
                "duration": media.duration,
            },
        )
    else:
        media_path = Path(task.source.get("local_path", ""))
        if not media_path.exists():
            raise RuntimeError("上传的文件不存在，可能已被清理，请重新上传")
        store.progress(task_id, stage="downloading", percent=_scale("downloading", 100.0),
                       message="本地文件已就绪")
        store.update(task_id, media_path=str(media_path))

    media_path = Path(store.get(task_id).media_path)

    # ---------------- 2. 抽音频 ----------------
    store.progress(task_id, stage="extracting", percent=_scale("extracting", 5.0), message="正在提取音频轨…")
    wav_path = audio_service.extract_audio(media_path, workdir)
    probe = audio_service.probe_audio_info(wav_path)
    duration = float(probe.get("duration") or 0.0) or float(task.source.get("duration") or 0.0)
    store.update(
        task_id,
        audio_path=str(wav_path),
        source={**store.get(task_id).source, "duration": duration},
    )
    store.progress(task_id, stage="extracting", percent=_scale("extracting", 100.0),
                   message=f"音频就绪（{fmt_duration(duration)}）")

    # ---------------- 3. 语音转文字 ----------------
    backend = (opts.get("asr_backend") or settings.asr_backend or "faster-whisper").lower()
    store.progress(task_id, stage="transcribing", percent=_scale("transcribing", 1.0),
                   message=f"开始语音转文字（{backend}）…")
    asr_result = asr_service.transcribe(
        wav_path,
        backend=backend,
        model_name=opts.get("model") or settings.whisper_model,
        device=opts.get("device") or settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        language=opts.get("language"),
        initial_prompt=opts.get("initial_prompt"),
        vad_filter=bool(opts.get("vad_filter", True)),
        word_timestamps=bool(opts.get("word_timestamps", True)),
        duration=duration,
        on_progress=_reporter(task_id, "transcribing", "正在转写语音…"),
    )
    if not asr_result.segments:
        raise RuntimeError("未识别到任何语音内容，请确认音频中包含清晰人声")
    store.progress(task_id, stage="transcribing", percent=_scale("transcribing", 100.0),
                   message=f"转写完成，共 {len(asr_result.segments)} 段")
    if backend == "mock":
        store.add_note(
            task_id,
            "当前为 mock 演示模式：文稿、时间轴与说话人标签均为示例数据，仅用于预览界面与联调；"
            "处理真实素材请在 .env 中改用 faster-whisper 或 openai 引擎。",
        )

    # 用识别结果修正时长（更准）
    duration = max(duration, asr_result.duration, asr_result.segments[-1].end)

    # ---------------- 4. 说话人分离 ----------------
    want_diar = opts.get("diarization")
    want_diar = settings.diarization_enabled if want_diar is None else bool(want_diar)
    num_speakers = opts.get("num_speakers") or settings.diarization_num_speakers or 0

    turns = None
    if want_diar and backend == "mock":
        store.progress(task_id, stage="diarizing", percent=_scale("diarizing", 1.0), message="mock 演示模式：生成说话人分段…")
        turns = diar_service.mock_diarize(
            duration,
            int(num_speakers),
            on_progress=_reporter(task_id, "diarizing", "mock 演示模式：生成说话人分段…"),
        )
        store.progress(task_id, stage="diarizing", percent=_scale("diarizing", 100.0),
                       message=f"mock 演示模式：已生成 {len({t.speaker for t in turns})} 位说话人分段")
    elif want_diar:
        ok, reason = diar_service.available()
        if not ok:
            store.add_note(task_id, f"未执行说话人分离：{reason}。已按单一说话人 A 输出。")
            store.progress(task_id, stage="diarizing", percent=_scale("diarizing", 100.0), message=f"跳过说话人分离（{reason}）")
        else:
            store.progress(task_id, stage="diarizing", percent=_scale("diarizing", 1.0), message="正在做说话人分离…")
            try:
                turns = diar_service.diarize(
                    wav_path,
                    num_speakers=int(num_speakers),
                    on_progress=_reporter(task_id, "diarizing", "正在做说话人分离…"),
                    duration=duration,
                )
                store.progress(task_id, stage="diarizing", percent=_scale("diarizing", 100.0),
                               message=f"识别到 {len({t.speaker for t in turns})} 位说话人")
            except Exception as exc:
                if not settings.diarization_fallback:
                    raise
                turns = None
                store.add_note(task_id, f"说话人分离失败（{exc}），已按单一说话人 A 输出。")
                store.progress(task_id, stage="diarizing", percent=_scale("diarizing", 100.0), message="说话人分离失败，已降级")
    else:
        store.progress(task_id, stage="diarizing", percent=_scale("diarizing", 100.0), message="已关闭说话人分离")

    # ---------------- 5. 对齐 ----------------
    store.progress(task_id, stage="aligning", percent=_scale("aligning", 10.0),
                   message="正在对齐文稿与说话人…")
    if turns:
        rows, speakers = align(asr_result.segments, turns)
    else:
        rows, speakers = single_speaker_rows(asr_result.segments)
    store.progress(task_id, stage="aligning", percent=_scale("aligning", 100.0),
                   message=f"文稿对齐完成，共 {len(rows)} 段 / {len(speakers)} 位说话人")

    # ---------------- 6. 落盘 ----------------
    store.progress(task_id, stage="exporting", percent=_scale("exporting", 20.0),
                   message="正在生成文稿与字幕文件…")
    meta = {
        "task_id": task_id,
        "title": store.get(task_id).source.get("title") or "转写文稿",
        "source_url": store.get(task_id).source.get("webpage_url") or store.get(task_id).source.get("url") or "",
        "platform": store.get(task_id).source.get("platform", ""),
        "uploader": store.get(task_id).source.get("uploader", ""),
        "duration": round(duration, 2),
        "language": asr_result.language,
        "asr_backend": asr_result.backend,
        "asr_model": asr_result.model,
        "diarization": bool(turns),
        "speaker_count": len(speakers),
        "built_at": _now_str(),
    }

    result_payload = {
        "task_id": task_id,
        "meta": meta,
        "speakers": speakers,
        "segments": [
            {
                "index": row.index,
                "start": round(row.start, 3),
                "end": round(row.end, 3),
                "text": row.text,
                "speaker": row.speaker,
                "speaker_raw": row.speaker_raw,
                "words": row.words,
            }
            for row in rows
        ],
    }

    result_path = workdir / "result.json"
    result_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 顺手导出常用格式，用户也能直接从 data 目录取
    exports_dir = workdir / "exports"
    exports_dir.mkdir(exist_ok=True)
    stem = _safe_stem(meta["title"])
    for fmt in ("txt", "srt", "json"):
        content = exporter.export(fmt, rows, len(speakers), meta)
        (exports_dir / f"{stem}.{fmt}").write_text(content, encoding="utf-8")

    store.update(
        task_id,
        result_path=str(result_path),
        source={**store.get(task_id).source, "language": asr_result.language,
                "asr_backend": asr_result.backend, "asr_model": asr_result.model,
                "speaker_count": len(speakers)},
        status="done",
        stage="done",
        progress=100.0,
        message=f"完成：{len(rows)} 段文稿 / {len(speakers)} 位说话人",
        error=None,
    )


def _safe_stem(name: str) -> str:
    keep = "".join(ch for ch in (name or "transcript") if ch not in '\\/:*?"<>|\r\n\t').strip()
    return (keep or "transcript")[:80]


def _now_str() -> str:
    import datetime

    now = datetime.datetime.now()
    return f"{now.year}-{now.month:02d}-{now.day:02d} {now.hour:02d}:{now.minute:02d}:{now.second:02d}"


def _write_error_log(task: Task, detail: str) -> None:
    try:
        (task.workdir / "error.log").write_text(detail, encoding="utf-8")
    except OSError:
        pass


def cleanup_task_files(task: Task) -> None:
    """删除任务产生的媒体与音频，只保留文稿。"""
    for path in (task.media_path, task.audio_path):
        if path:
            p = Path(path)
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
    uploads = settings.uploads_dir / task.task_id
    if uploads.exists():
        shutil.rmtree(uploads, ignore_errors=True)
