# -*- coding: utf-8 -*-
"""请求 / 响应数据结构。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class TranscribeOptions(BaseModel):
    """单次任务的运行参数（缺省时回落到 .env 默认值）。"""

    asr_backend: Optional[Literal["faster-whisper", "openai", "mock"]] = Field(
        default=None, description="识别引擎；不填用服务默认值"
    )
    model: Optional[str] = Field(default=None, description="faster-whisper 模型名，如 small / medium / large-v3")
    language: Optional[str] = Field(default=None, description="语言代码：zh / en / ja …；auto 表示自动检测")
    device: Optional[Literal["auto", "cpu", "cuda"]] = Field(default=None, description="推理设备")
    diarization: Optional[bool] = Field(default=None, description="是否做说话人分离")
    num_speakers: Optional[int] = Field(default=None, ge=0, le=20, description="说话人数；0 = 自动判断")
    initial_prompt: Optional[str] = Field(default=None, max_length=1000, description="提示词：可填入专有名词提升准确率")
    vad_filter: bool = Field(default=True, description="是否启用 VAD 静音切分")
    word_timestamps: bool = Field(default=True, description="是否输出词级时间戳（用于精修 SRT）")

    @field_validator("language")
    @classmethod
    def _norm_language(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v or v.lower() in {"auto", "自动", "自动检测"}:
            return None
        return v


class UrlTaskRequest(BaseModel):
    """粘贴链接创建任务。"""

    url: str = Field(..., min_length=6, max_length=2048)
    options: TranscribeOptions = Field(default_factory=TranscribeOptions)


class TaskCreatedResponse(BaseModel):
    task_id: str
    status: str
    stage: str


class SpeakerInfo(BaseModel):
    id: str
    label: str
    color: str
    seconds: float
    percent: float
    segment_count: int


class Segment(BaseModel):
    index: int
    start: float
    end: float
    text: str
    speaker: str
    speaker_label: str
    words: list[dict] = Field(default_factory=list)


class TaskResult(BaseModel):
    task_id: str
    media_url: Optional[str] = None
    source: dict = Field(default_factory=dict)
    stats: dict = Field(default_factory=dict)
    speakers: list[SpeakerInfo] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
