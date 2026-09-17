# -*- coding: utf-8 -*-
"""通用小工具：URL 安全校验、时间格式化、说话人配色。"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# 说话人配色盘（A 起按顺序分配，超出后循环）
SPEAKER_PALETTE: list[str] = [
    "#6366f1",  # A 靛蓝
    "#06b6d4",  # B 青
    "#f59e0b",  # C 琥珀
    "#ec4899",  # D 品红
    "#10b981",  # E 翠绿
    "#8b5cf6",  # F 紫罗兰
    "#ef4444",  # G 红
    "#0ea5e9",  # H 天蓝
    "#84cc16",  # I 黄绿
    "#f97316",  # J 橙
]

SPEAKER_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

PLATFORM_HINTS: list[tuple[str, str]] = [
    ("v.douyin.com", "抖音"),
    ("douyin.com", "抖音"),
    ("iesdouyin.com", "抖音"),
    ("xiaohongshu.com", "小红书"),
    ("xhslink.com", "小红书"),
    ("channels.weixin.qq.com", "微信视频号"),
    ("weixin.qq.com", "微信视频号"),
    ("finder.video.qq.com", "视频号"),
    ("bilibili.com", "哔哩哔哩"),
    ("b23.tv", "哔哩哔哩"),
    ("kuaishou.com", "快手"),
    ("zhihu.com", "知乎"),
    ("youtube.com", "YouTube"),
    ("youtu.be", "YouTube"),
    ("twitter.com", "X"),
    ("x.com", "X"),
]


class UnsafeUrlError(ValueError):
    """URL 不安全（协议非法 / 指向内网地址）。"""


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for key, name in PLATFORM_HINTS:
        if host == key or host.endswith("." + key) or key in host:
            return name
    return "其他平台"


def speaker_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA。"""
    if index < 26:
        return SPEAKER_LETTERS[index]
    return SPEAKER_LETTERS[index // 26 - 1] + SPEAKER_LETTERS[index % 26]


def speaker_color(index: int) -> str:
    return SPEAKER_PALETTE[index % len(SPEAKER_PALETTE)]


def validate_remote_url(url: str) -> str:
    """校验用户提交的链接：仅允许 http/https，禁止内网/本机地址（防 SSRF）。"""
    url = (url or "").strip()
    if not url:
        raise UnsafeUrlError("链接不能为空")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("仅支持 http / https 链接")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("链接缺少有效域名")

    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise UnsafeUrlError("不允许访问本机地址")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"域名无法解析：{host}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeUrlError(f"不允许访问内网地址：{ip}")
    return url


def fmt_timestamp(seconds: float, with_ms: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if with_ms:
        millis = int(round((seconds - int(seconds)) * 1000))
        if millis == 1000:
            millis = 999
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def fmt_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 3600:
        minutes, secs = divmod(int(seconds), 60)
        return f"{minutes}分{secs:02d}秒"
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}小时{minutes:02d}分{secs:02d}秒"
