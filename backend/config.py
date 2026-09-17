# -*- coding: utf-8 -*-
"""全局配置：优先读环境变量 / .env，全部提供可用默认值。

运行期参数（模型、语言、是否分离说话人等）走请求级 options，
这里只保存"默认值"和"服务级配置"。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """极简 .env 加载器（避免强依赖 python-dotenv 缺失时直接崩）。"""
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(env_file, override=False)
        return
    except Exception:
        pass
    # 退化实现
    for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class Settings:
    """服务配置。进程启动时读取一次。"""

    def __init__(self) -> None:
        # ---- 服务 ----
        self.host: str = os.getenv("VOXSCRIPT_HOST", "127.0.0.1")
        self.port: int = _int(os.getenv("VOXSCRIPT_PORT"), 8000)
        data_dir = os.getenv("VOXSCRIPT_DATA_DIR", "").strip()
        self.data_dir: Path = Path(data_dir).expanduser() if data_dir else (ROOT_DIR / "data")
        self.max_workers: int = max(1, _int(os.getenv("MAX_WORKERS"), 1))
        self.max_upload_mb: int = max(1, _int(os.getenv("MAX_UPLOAD_MB"), 800))

        # 前端静态资源目录：优先 docs/（GitHub Pages 的 /docs 发布目录），兼容旧版 frontend/
        docs_dir = ROOT_DIR / "docs"
        self.frontend_dir: Path = docs_dir if docs_dir.exists() else (ROOT_DIR / "frontend")

        # 允许跨域访问的来源（GitHub Pages 等静态站点调用本后端时必须放开）
        # 逗号分隔；默认 "*"（任意来源，不携带 Cookie）。生产可收紧为你的 Pages 域名。
        raw_origins = os.getenv("CORS_ORIGINS", "*").strip()
        self.cors_origins: list[str] = (
            ["*"] if raw_origins in {"", "*"} else [o.strip() for o in raw_origins.split(",") if o.strip()]
        )

        # ---- ASR ----
        self.asr_backend: str = os.getenv("ASR_BACKEND", "faster-whisper").strip().lower()
        self.whisper_model: str = os.getenv("WHISPER_MODEL", "small").strip()
        self.whisper_device: str = os.getenv("WHISPER_DEVICE", "auto").strip().lower()
        self.whisper_compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "auto").strip().lower()
        self.whisper_cache_dir: str = os.getenv("WHISPER_CACHE_DIR", "").strip()

        self.openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_asr_model: str = os.getenv("OPENAI_ASR_MODEL", "whisper-1").strip()
        self.openai_timeout: int = _int(os.getenv("OPENAI_TIMEOUT"), 300)

        # ---- 说话人分离 ----
        self.diarization_enabled: bool = _bool(os.getenv("DIARIZATION_ENABLED"), True)
        self.hf_token: str = os.getenv("HF_TOKEN", "").strip() or os.getenv("HUGGINGFACE_TOKEN", "").strip()
        self.diarization_model: str = os.getenv(
            "DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
        ).strip()
        self.diarization_num_speakers: int = _int(os.getenv("DIARIZATION_NUM_SPEAKERS"), 0)
        self.diarization_fallback: bool = _bool(os.getenv("DIARIZATION_FALLBACK"), True)

        # ---- 下载 ----
        self.ytdlp_cookies: str = os.getenv("YTDLP_COOKIES", "").strip()
        self.ytdlp_cookies_from_browser: str = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()
        self.ytdlp_proxy: str = os.getenv("YTDLP_PROXY", "").strip()
        self.ffmpeg_binary: str = os.getenv("FFMPEG_BINARY", "").strip()

    # ---------- 派生路径 ----------
    @property
    def tasks_dir(self) -> Path:
        return self.data_dir / "tasks"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def models_dir(self) -> Path:
        return Path(self.whisper_cache_dir) if self.whisper_cache_dir else (self.data_dir / "models")

    def task_dir(self, task_id: str) -> Path:
        return self.tasks_dir / task_id

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.tasks_dir, self.uploads_dir):
            path.mkdir(parents=True, exist_ok=True)

    # ---------- 对外快照（不含密钥）----------
    def public_snapshot(self) -> dict:
        return {
            "asr_backend": self.asr_backend,
            "whisper_model": self.whisper_model,
            "whisper_device": self.whisper_device,
            "openai_asr_model": self.openai_asr_model,
            "openai_base_url": self.openai_base_url,
            "openai_configured": bool(self.openai_api_key),
            "diarization_enabled": self.diarization_enabled,
            "diarization_model": self.diarization_model,
            "diarization_token_configured": bool(self.hf_token),
            "diarization_fallback": self.diarization_fallback,
            "max_upload_mb": self.max_upload_mb,
            "max_workers": self.max_workers,
        }


settings = Settings()
