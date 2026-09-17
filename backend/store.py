# -*- coding: utf-8 -*-
"""任务状态仓库：内存 + 磁盘双写，进程重启后仍可查历史结果。"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from .config import settings

STAGE_LABELS: dict[str, str] = {
    "queued": "排队中",
    "downloading": "解析视频 / 下载媒体",
    "extracting": "提取音频轨",
    "transcribing": "语音转文字",
    "diarizing": "说话人分离",
    "aligning": "对齐文稿与说话人",
    "exporting": "生成导出文件",
    "done": "已完成",
    "failed": "失败",
    "canceled": "已取消",
}

TERMINAL_STATES = {"done", "failed", "canceled"}


@dataclass
class Task:
    task_id: str
    source_type: str  # url | upload
    source: dict[str, Any] = field(default_factory=dict)      # {url / filename, title, duration, platform}
    options: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"          # queued | running | done | failed | canceled
    stage: str = "queued"
    progress: float = 0.0           # 0-100
    message: str = "任务已创建，等待执行"
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    media_path: Optional[str] = None
    audio_path: Optional[str] = None
    result_path: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def workdir(self) -> Path:
        return settings.task_dir(self.task_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stage_label"] = STAGE_LABELS.get(self.stage, self.stage)
        data["created_at_iso"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.created_at))
        data["elapsed"] = round(max(0.0, self.updated_at - self.created_at), 1)
        data["finished"] = self.status in TERMINAL_STATES
        return data


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()

    # ---------- 生命周期 ----------
    def create(self, source_type: str, source: dict, options: dict) -> Task:
        task_id = uuid.uuid4().hex[:16]
        task = Task(task_id=task_id, source_type=source_type, source=source, options=options)
        task.workdir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._tasks[task_id] = task
        self._persist(task)
        return task

    def get(self, task_id: str) -> Optional[Task]:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is not None:
            return task
        return self._load_from_disk(task_id)

    def list_recent(self, limit: int = 20) -> list[Task]:
        with self._lock:
            tasks = list(self._tasks.values())
        if not tasks and settings.tasks_dir.exists():
            for child in sorted(settings.tasks_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
                loaded = self._load_from_disk(child.name)
                if loaded:
                    tasks.append(loaded)
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    # ---------- 状态更新 ----------
    def update(self, task_id: str, **fields: Any) -> Optional[Task]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            for key, value in fields.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            task.updated_at = time.time()
        self._persist(task)
        return task

    def progress(self, task_id: str, *, stage: str | None = None, percent: float | None = None,
                 message: str | None = None) -> None:
        """进度回调：只更新传入的字段，进度只增不减。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status == "canceled":
                return
            if stage:
                task.stage = stage
            if percent is not None:
                task.progress = round(max(task.progress, min(100.0, float(percent))), 1)
            if message:
                task.message = message
            task.status = "running"
            task.updated_at = time.time()
        self._persist(task)

    def add_note(self, task_id: str, note: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            if note not in task.notes:
                task.notes.append(note)
        self._persist(task)

    def deactivate(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)

    # ---------- 落盘 ----------
    def _persist(self, task: Task) -> None:
        try:
            task.workdir.mkdir(parents=True, exist_ok=True)
            tmp = task.workdir / "task.json.tmp"
            tmp.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(task.workdir / "task.json")
        except OSError:
            pass

    def _load_from_disk(self, task_id: str) -> Optional[Task]:
        meta_file = settings.task_dir(task_id) / "task.json"
        if not meta_file.exists():
            return None
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        task = Task(
            task_id=data.get("task_id", task_id),
            source_type=data.get("source_type", "upload"),
            source=data.get("source", {}),
            options=data.get("options", {}),
            status=data.get("status", "failed"),
            stage=data.get("stage", "failed"),
            progress=float(data.get("progress", 0.0)),
            message=data.get("message", ""),
            error=data.get("error"),
            notes=data.get("notes", []),
            media_path=data.get("media_path"),
            audio_path=data.get("audio_path"),
            result_path=data.get("result_path"),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )
        with self._lock:
            self._tasks[task_id] = task
        return task


store = TaskStore()
