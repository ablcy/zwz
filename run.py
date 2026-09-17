#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""VoxScript 启动入口。

用法：
    python run.py                 # 默认 127.0.0.1:8000
    python run.py --port 9000     # 指定端口
    python run.py --reload        # 开发模式（热重载）
    python run.py --mock          # 强制使用假数据引擎，无需下载模型即可预览界面
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

BANNER = r"""
 __      __         ____  _       _      _
 \ \    / /__ __ __/ ___|| |_ _ __(_) ___| |_
  \ \  / / _ \ \/ /\___ \| __| '__| |/ __| __|
   \ \/ / (_) >  <  ___) | |_| |  | | (__| |_
    \/   \___/_/\_\|____/ \__|_|  |_|\___|\__|
 声刻 VoxScript · 视频口播/字幕转文字（说话人分离）
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="VoxScript 声刻 · 视频转文字工具")
    parser.add_argument("--host", default=None, help="监听地址，默认取 .env 的 VOXSCRIPT_HOST")
    parser.add_argument("--port", type=int, default=None, help="监听端口，默认取 .env 的 VOXSCRIPT_PORT")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码热重载")
    parser.add_argument("--mock", action="store_true", help="强制使用 mock 引擎（无需模型，快速预览界面）")
    args = parser.parse_args()

    if args.mock:
        os.environ["ASR_BACKEND"] = "mock"
        # mock 模式下说话人分段同样走演示数据，保证 A/B/C 全链路可预览
        os.environ["DIARIZATION_ENABLED"] = "true"

    from backend.config import settings  # noqa: E402  必须在设置环境变量之后导入

    host = args.host or settings.host
    port = args.port or settings.port
    settings.ensure_dirs()

    print(BANNER)
    print(f"  识别引擎    : {settings.asr_backend}")
    print(f"  说话人分离  : {'开启' if settings.diarization_enabled else '关闭'}")
    print(f"  数据目录    : {settings.data_dir}")
    print(f"  访问地址    : http://{host}:{port}")
    print("  按 Ctrl+C 停止服务\n")

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
