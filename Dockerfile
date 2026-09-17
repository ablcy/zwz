# ==============================================================================
#  VoxScript 声刻 · 后端服务镜像
#
#  构建（在项目根目录执行）：
#      docker build -t voxscript .
#  运行：
#      docker run -d --name voxscript -p 8000:8000 \
#        -e HF_TOKEN=hf_xxx \
#        -v voxscript-data:/app/data \
#        voxscript
#
#  说明：
#  - 镜像内已装 ffmpeg（抽取音频必需），容器内同时托管 docs/ 页面，
#    因此这个容器既能当纯后端（供 GitHub Pages 调用），也能独立跑完整站点；
#  - 默认 CPU 版 torch（体积小、无需显卡）；如有 GPU，把 TORCH_INDEX/TORCH_VERSION
#    换成对应 CUDA 版本即可，例如 --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu121；
#  - 模型与任务数据都落在 /app/data，挂载卷可避免每次重建都重新下载模型。
# ==============================================================================
FROM python:3.11-slim

ARG TORCH_VERSION=2.2.2
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    VOXSCRIPT_HOST=0.0.0.0 \
    VOXSCRIPT_PORT=8000 \
    VOXSCRIPT_DATA_DIR=/app/data \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8 \
    HF_HOME=/app/data/hf \
    HF_HUB_DISABLE_TELEMETRY=1

# ffmpeg：从视频中抽取音频；curl：容器健康检查用
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖，充分利用镜像层缓存
COPY requirements.txt ./

# torch 单独安装：默认走 CPU 轮子（约几百 MB，而不是 CUDA 版的数 GB）
RUN pip install --upgrade pip \
 && pip install "torch==${TORCH_VERSION}+cpu" "torchaudio==${TORCH_VERSION}+cpu" \
      --extra-index-url "${TORCH_INDEX}" \
 && pip install -r requirements.txt

COPY backend/ ./backend/
COPY docs/ ./docs/
COPY run.py ./

# 非 root 运行；/app/data 用于持久化任务数据与模型
RUN mkdir -p /app/data \
 && useradd -m -u 10001 vox \
 && chown -R vox:vox /app
USER vox

VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
