# -*- coding: utf-8 -*-
"""视频链接解析与下载（yt-dlp）。

支持抖音 / 小红书 / 视频号 / 哔哩哔哩 / 快手 / YouTube 等 yt-dlp 覆盖的平台。
对需要登录的内容，可通过 .env 配置 YTDLP_COOKIES / YTDLP_COOKIES_FROM_BROWSER。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..config import settings
from ..utils import detect_platform, validate_remote_url

ProgressCallback = Callable[[float, str], None]


class DownloadError(RuntimeError):
    """下载 / 解析失败。"""


@dataclass
class DownloadedMedia:
    path: Path
    title: str = ""
    duration: float = 0.0
    uploader: str = ""
    webpage_url: str = ""
    extractor: str = ""
    platform: str = ""
    extra: dict = field(default_factory=dict)


def _sanitize(name: str, fallback: str = "media") -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (name or "").strip())
    name = name.strip(" .")
    return name[:120] or fallback


def _build_ydl_opts(workdir: Path, use_ffmpeg: bool) -> dict:
    opts: dict = {
        "outtmpl": str(workdir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,
        "restrictfilenames": False,
        "windowsfilenames": True,
        # 优先纯音频流，省带宽；没有再退回含视频的最佳流
        "format": "bestaudio[ext=m4a]/bestaudio/best[height<=720]/best",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    }
    if use_ffmpeg:
        opts["final_ext"] = "m4a"
    if settings.ytdlp_proxy:
        opts["proxy"] = settings.ytdlp_proxy
    if settings.ytdlp_cookies and Path(settings.ytdlp_cookies).exists():
        opts["cookiefile"] = settings.ytdlp_cookies
    elif settings.ytdlp_cookies_from_browser:
        browser = settings.ytdlp_cookies_from_browser
        opts["cookiesfrombrowser"] = (browser.split(":")[0],) + tuple(browser.split(":")[1:])
    # 部分平台（抖音/小红书）需要移动端 UA 才能拿到无水印直链
    opts["http_headers"] = {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    return opts


def download(url: str, workdir: str | Path, on_progress: Optional[ProgressCallback] = None) -> DownloadedMedia:
    """下载链接对应媒体的最佳音轨，返回本地文件路径与元信息。"""
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise DownloadError("未安装 yt-dlp，请执行：pip install yt-dlp") from exc

    url = validate_remote_url(url)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    from .audio import ffmpeg_available

    use_ffmpeg = ffmpeg_available()

    def hook(payload: dict) -> None:
        if on_progress is None or payload.get("status") != "downloading":
            return
        total = payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0
        got = payload.get("downloaded_bytes") or 0
        if total:
            on_progress(min(99.0, got * 100.0 / total), "正在下载媒体流…")
        else:
            on_progress(50.0, f"已下载 {got / 1048576:.1f} MB …")

    opts = _build_ydl_opts(workdir, use_ffmpeg)
    opts["progress_hooks"] = [hook]

    if on_progress:
        on_progress(1.0, "正在解析链接…")

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise DownloadError(_friendly_error(str(exc))) from exc

    if info is None:
        raise DownloadError("链接解析失败，未获取到媒体信息")
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise DownloadError("该链接下没有可下载的内容")
        info = entries[0]

    media_path = _locate_file(info, workdir)
    if media_path is None or not media_path.exists():
        raise DownloadError("下载完成但未找到媒体文件，请检查 ffmpeg 是否可用")

    if on_progress:
        on_progress(100.0, "下载完成")

    return DownloadedMedia(
        path=media_path,
        title=info.get("title") or media_path.stem,
        duration=float(info.get("duration") or 0.0),
        uploader=info.get("uploader") or info.get("channel") or info.get("nickname") or "",
        webpage_url=info.get("webpage_url") or url,
        extractor=info.get("extractor_key") or info.get("extractor") or "",
        platform=detect_platform(url),
        extra={
            "view_count": info.get("view_count"),
            "upload_date": info.get("upload_date"),
            "description": (info.get("description") or "")[:500],
        },
    )


def _locate_file(info: dict, workdir: Path) -> Optional[Path]:
    """yt-dlp 返回信息里找最终落盘路径，找不到就扫目录。"""
    for key in ("requested_downloads", "requested_formats"):
        for item in info.get(key) or []:
            candidate = item.get("filepath") or item.get("_filename")
            if candidate and Path(candidate).exists():
                return Path(candidate)
    for key in ("filepath", "_filename"):
        candidate = info.get(key)
        if candidate and Path(candidate).exists():
            return Path(candidate)

    prepared = Path(info.get("__files_to_move", {}) and "")
    if prepared and prepared.exists():  # pragma: no cover - 兼容旧版本字段
        return prepared

    # 目录扫描：排除我们自己产出的中间文件
    candidates = [
        p for p in workdir.iterdir()
        if p.is_file()
        and not p.name.startswith("audio_")
        and p.suffix.lower() not in {".json", ".txt", ".part", ".ytdl", ".tmp"}
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
    return candidates[0]


def _friendly_error(raw: str) -> str:
    """把 yt-dlp 的英文报错翻译成用户能读懂的提示。"""
    text = raw.strip()
    low = text.lower()
    if "unsupported url" in low:
        return "该链接暂不被支持，请确认是完整的视频分享链接（含 http/https）。"
    if "private video" in low or "login" in low or "sign in" in low or "cookies" in low:
        return (
            "该视频需要登录才能访问。请在 .env 中配置 YTDLP_COOKIES（浏览器导出的 cookies.txt）"
            "或 YTDLP_COOKIES_FROM_BROWSER=chrome 后重试。"
        )
    if "video unavailable" in low or "not found" in low or "404" in low:
        return "视频不存在或已被删除，请检查链接是否有效。"
    if "geo" in low and "restrict" in low:
        return "该视频有地区限制，可配置 YTDLP_PROXY 代理后重试。"
    if "timed out" in low or "timeout" in low:
        return "网络超时，请检查网络或配置 YTDLP_PROXY 后重试。"
    if "ffmpeg" in low:
        return "缺少 ffmpeg，无法处理媒体流，请先安装 ffmpeg。"
    return f"链接解析失败：{text[:300]}"
