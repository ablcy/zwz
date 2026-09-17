# -*- coding: utf-8 -*-
"""VoxScript 后端服务（FastAPI）。

接口一览：
    GET    /api/health                 服务与依赖状态
    GET    /api/config                 当前默认配置（不含密钥）
    POST   /api/tasks                  粘贴链接创建任务
    POST   /api/tasks/upload           上传本地音视频创建任务
    GET    /api/tasks                  最近任务列表
    GET    /api/tasks/{id}             任务进度
    GET    /api/tasks/{id}/result      转写结果（分段文稿 + 说话人统计）
    GET    /api/tasks/{id}/media       音频流（供页面播放器使用）
    GET    /api/tasks/{id}/export      导出 TXT / SRT / VTT / MD / JSON
    DELETE /api/tasks/{id}             删除任务及其本地文件
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import settings
from .pipeline import cleanup_task_files, submit
from .schemas import TaskCreatedResponse, TranscribeOptions, UrlTaskRequest
from .services import audio as audio_service
from .services import diarization as diar_service
from .services import exporter
from .services.align import AlignedSegment
from .store import store
from .utils import UnsafeUrlError, detect_platform, fmt_duration, validate_remote_url

app = FastAPI(
    title="VoxScript 声刻 API",
    description="视频口播 / 字幕转文字，支持说话人分离（A/B/C 区分）",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.ensure_dirs()


# ==========================================================================
#  基础信息
# ==========================================================================
@app.get("/api/health")
def health() -> dict:
    diar_ok, diar_reason = diar_service.available()
    ffmpeg_ok = audio_service.ffmpeg_available()

    gpu = None
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            gpu = torch.cuda.get_device_name(0)
    except Exception:
        gpu = None

    warnings: list[str] = []
    if not ffmpeg_ok:
        warnings.append("未检测到 ffmpeg，无法抽取音频与解析媒体流，请先安装 ffmpeg。")
    if settings.asr_backend == "faster-whisper":
        try:
            import faster_whisper  # type: ignore  # noqa: F401
        except ImportError:
            warnings.append("未安装 faster-whisper，本地识别不可用（pip install faster-whisper）。")
    if settings.asr_backend == "openai" and not settings.openai_api_key:
        warnings.append("识别引擎设为 openai 但未配置 OPENAI_API_KEY。")
    if settings.diarization_enabled and not diar_ok:
        warnings.append(f"说话人分离不可用：{diar_reason}")

    return {
        "status": "ok",
        "version": __version__,
        "ffmpeg": ffmpeg_ok,
        "gpu": gpu,
        "asr_backend": settings.asr_backend,
        "diarization": {"available": diar_ok, "reason": diar_reason},
        "warnings": warnings,
    }


@app.get("/api/config")
def get_config() -> dict:
    diar_ok, diar_reason = diar_service.available()
    return {
        **settings.public_snapshot(),
        "diarization_available": diar_ok,
        "diarization_reason": diar_reason,
        "export_formats": list(exporter.EXPORT_FORMATS),
        "platforms": ["抖音", "小红书", "微信视频号", "哔哩哔哩", "快手", "YouTube"],
    }


# ==========================================================================
#  创建任务
# ==========================================================================
@app.post("/api/tasks", response_model=TaskCreatedResponse)
def create_task(payload: UrlTaskRequest) -> TaskCreatedResponse:
    try:
        url = validate_remote_url(payload.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    options = payload.options.model_dump()
    task = store.create(
        source_type="url",
        source={"url": url, "platform": detect_platform(url)},
        options=options,
    )
    submit(task)
    return TaskCreatedResponse(task_id=task.task_id, status=task.status, stage=task.stage)


@app.post("/api/tasks/upload", response_model=TaskCreatedResponse)
async def create_task_from_upload(
    file: UploadFile = File(..., description="本地视频或音频文件"),
    options: str = Form("{}", description="TranscribeOptions 的 JSON 字符串"),
) -> TaskCreatedResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if not audio_service.is_media_file(file.filename or ""):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {suffix or '(无扩展名)'}，请上传常见音视频文件（mp4/mov/mkv/mp3/wav/m4a 等）",
        )

    try:
        raw_options = json.loads(options or "{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="options 不是合法 JSON") from exc
    try:
        parsed = TranscribeOptions(**raw_options).model_dump()
    except Exception as exc:  # pydantic 校验错误
        raise HTTPException(status_code=400, detail=f"options 参数非法：{exc}") from exc

    max_bytes = settings.max_upload_mb * 1024 * 1024
    tmp_dir = settings.uploads_dir
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid.uuid4().hex}{suffix}"

    written = 0
    try:
        with tmp_path.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过上限 {settings.max_upload_mb} MB，可在 .env 中调整 MAX_UPLOAD_MB",
                    )
                fh.write(chunk)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"文件保存失败：{exc}") from exc
    finally:
        await file.close()

    if written == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="上传的文件为空")

    task = store.create(
        source_type="upload",
        source={
            "filename": file.filename,
            "platform": "本地文件",
            "title": Path(file.filename or "本地文件").stem,
            "size": written,
        },
        options=parsed,
    )
    target = task.workdir / f"source{suffix}"
    shutil.move(str(tmp_path), str(target))
    store.update(task.task_id, source={**task.source, "local_path": str(target)}, media_path=str(target))

    submit(store.get(task.task_id))
    return TaskCreatedResponse(task_id=task.task_id, status="queued", stage="queued")


# ==========================================================================
#  任务查询
# ==========================================================================
def _require_task(task_id: str):
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或已被删除")
    return task


@app.get("/api/tasks")
def list_tasks(limit: int = Query(20, ge=1, le=100)) -> dict:
    tasks = store.list_recent(limit)
    return {"total": len(tasks), "tasks": [t.to_dict() for t in tasks]}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    return _require_task(task_id).to_dict()


@app.get("/api/tasks/{task_id}/result")
def get_result(task_id: str) -> dict:
    task = _require_task(task_id)
    if task.status == "failed":
        raise HTTPException(status_code=400, detail=task.error or "任务失败")
    if task.status != "done" or not task.result_path:
        return JSONResponse(status_code=202, content={"task_id": task_id, "status": task.status,
                                                     "stage": task.stage, "progress": task.progress,
                                                     "message": task.message})

    payload = json.loads(Path(task.result_path).read_text(encoding="utf-8"))
    speaker_count = len(payload.get("speakers", []))
    segments = payload.get("segments", [])

    # 补充页面展示需要的派生字段
    payload["stats"] = {
        "segment_count": len(segments),
        "speaker_count": speaker_count,
        "duration": payload.get("meta", {}).get("duration", 0),
        "duration_text": fmt_duration(payload.get("meta", {}).get("duration", 0)),
        "language": payload.get("meta", {}).get("language", ""),
        "char_count": sum(len(s.get("text", "")) for s in segments),
    }
    payload["media_url"] = f"/api/tasks/{task_id}/media" if task.audio_path else None
    payload["notes"] = task.notes
    payload["source"] = task.source
    return payload


@app.get("/api/tasks/{task_id}/media")
def get_media(task_id: str):
    task = _require_task(task_id)
    for path in (task.audio_path, task.media_path):
        if path and Path(path).exists():
            return FileResponse(path, media_type="audio/wav", filename=Path(path).name)
    raise HTTPException(status_code=404, detail="音频文件不存在或已被清理")


@app.get("/api/tasks/{task_id}/export")
def export_result(
    task_id: str,
    format: str = Query("txt", pattern="^(txt|srt|vtt|md|json)$"),
):
    task = _require_task(task_id)
    if task.status != "done" or not task.result_path:
        raise HTTPException(status_code=400, detail="任务尚未完成，无法导出")

    payload = json.loads(Path(task.result_path).read_text(encoding="utf-8"))
    rows = [
        AlignedSegment(
            index=item.get("index", i),
            start=float(item.get("start", 0.0)),
            end=float(item.get("end", 0.0)),
            text=item.get("text", ""),
            speaker=item.get("speaker", "A"),
            speaker_raw=item.get("speaker_raw", ""),
            words=item.get("words", []),
        )
        for i, item in enumerate(payload.get("segments", []))
    ]
    meta = payload.get("meta", {})
    content = exporter.export(format, rows, len(payload.get("speakers", [])), meta)

    stem = _download_stem(meta.get("title") or task_id)
    filename = f"{stem}.{format}"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{_url_quote(filename)}",
        "X-Filename": _url_quote(filename),
    }
    return PlainTextResponse(content, media_type=exporter.MIME_TYPES.get(format, "text/plain; charset=utf-8"),
                             headers=headers)


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str) -> dict:
    task = _require_task(task_id)
    workdir = task.workdir.resolve()
    data_root = settings.data_dir.resolve()
    if data_root not in workdir.parents:
        raise HTTPException(status_code=400, detail="拒绝操作：目标目录不在数据目录内")

    cleanup_task_files(task)
    shutil.rmtree(workdir, ignore_errors=True)
    store.deactivate(task_id)
    return {"task_id": task_id, "deleted": True}


# ==========================================================================
#  工具
# ==========================================================================
def _download_stem(name: str) -> str:
    keep = "".join(ch for ch in name if ch not in '\\/:*?"<>|\r\n\t').strip()
    return (keep or "transcript")[:80]


def _url_quote(text: str) -> str:
    from urllib.parse import quote

    return quote(text, safe="")


# ==========================================================================
#  前端静态资源（放在最后，避免抢占 /api 路由）
# ==========================================================================
if settings.frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
else:  # pragma: no cover
    @app.get("/")
    def _missing_frontend() -> dict:
        return {"error": "frontend 目录不存在，请确认项目完整性"}
