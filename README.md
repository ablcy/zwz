---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 0a9ed6357c9369e0c26fb6fb5f43e499_9f3555fab25211f1ab3f52540024e231
    ReservedCode1: ptBvR5bTFTIDJMyOxOtaNUBaDHTF3M8eFDU0Z6/WPUpOrGtS/wu3rIcshr2nwHlxbmZ78P8g+PnHFpwLCl/sFNpYd2M5gcS8cVs1BF5qcACdiCE5vSaaG7zYg6vat1Hnxf9SlDYB/RbaVOTp3dvg0YVThPfHcFG6f7t304clMIWEm2MVeUtshR5P3iE=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 0a9ed6357c9369e0c26fb6fb5f43e499_9f3555fab25211f1ab3f52540024e231
    ReservedCode2: ptBvR5bTFTIDJMyOxOtaNUBaDHTF3M8eFDU0Z6/WPUpOrGtS/wu3rIcshr2nwHlxbmZ78P8g+PnHFpwLCl/sFNpYd2M5gcS8cVs1BF5qcACdiCE5vSaaG7zYg6vat1Hnxf9SlDYB/RbaVOTp3dvg0YVThPfHcFG6f7t304clMIWEm2MVeUtshR5P3iE=
---

# 声刻 VoxScript · 视频口播 / 字幕转文字工具

把视频里说的话变成**可编辑、可检索、带时间轴**的文字，并且用 **A / B / C** 区分视频里有几个人在说话。

- 输入：抖音 / 小红书 / 微信视频号 / 哔哩哔哩 / 快手 / YouTube 的**视频链接**，或本地**视频 / 音频文件**
- 输出：逐句带时间戳的文稿、说话人标签（A/B/C）、可导出 **TXT / SRT / VTT / Markdown / JSON**
- 形态：**前端页面可放在 GitHub Pages 上（纯静态），语音识别由你自建的后端服务完成**

---

## 0. 先读这一节：页面放在哪、转写在哪跑

这是理解本项目部署方式的关键，一句话：

> **GitHub Pages 只能放"界面"，不能做语音识别；真正的转写必须在另一台能跑 Python / ffmpeg 的机器上（后端服务）完成。**

| | 前端页面（docs/） | 后端服务（backend/） |
| --- | --- | --- |
| 是什么 | 纯静态 HTML / CSS / JS | FastAPI 服务：下载视频、抽音频、Whisper 转写、说话人分离 |
| 部署到哪 | **GitHub Pages**（`main` 分支的 `/docs` 目录）<br>线上地址：<https://ablcy.github.io/zwz> | 任意能跑容器的平台：云服务器 / Render / Railway / Fly.io / Koyeb，或本机 `python run.py` |
| 需要数据库吗 | 不需要 | **不需要**（见 §9 常见问题第 1 条） |
| 能不能单独用 | 不能，只能展示界面 | 可以（它自己也托管一份页面，打开就是完整站点） |

**两者怎么连起来**：打开 Pages 页面 → 在页面顶部「后端服务」里填入你的后端地址 → 页面记住这个地址，之后所有转写请求都发往该后端。
未填地址或后端连不上时，页面会明确提示原因（不会静默失败）。详见 §5。

---

## 1. 功能一览

| 能力 | 说明 |
| --- | --- |
| 链接解析 | 基于 yt-dlp，覆盖抖音、小红书、视频号、哔哩哔哩、快手、YouTube 等上千站点；支持 Cookie / 代理配置以应对登录可见内容 |
| 本地上传 | 直接上传 mp4 / mov / mkv / webm / mp3 / wav / m4a / flac 等，素材由你自己的后端处理 |
| 音频抽取 | ffmpeg 统一转成 16kHz 单声道 WAV，作为识别与说话人分离的标准输入 |
| 语音转文字 | 默认 **faster-whisper** 本地推理；可一键切换到任意 **OpenAI 兼容** 接口（OpenAI / Groq / SiliconFlow / 本地 vLLM 等） |
| 说话人分离 | **pyannote.audio 3.1** 计算说话人时间段，再与识别片段做时间重叠对齐，按首次出现顺序标注 A / B / C … |
| 文稿展示 | 时间轴 / 纯文稿双视图、按说话人筛选、全文搜索高亮、点击句子跳转播放对应位置 |
| 导出 | TXT（纯文稿，带说话人前缀）、SRT / VTT（标准字幕）、MD（含说话人统计的完整报告）、JSON（结构化原始数据） |
| 任务管理 | 进度分阶段实时回传（获取媒体 → 提取音频 → 转文字 → 说话人分离 → 对齐 → 落盘），结果落盘，进程重启后仍可查历史 |
| 后端可选配 | 页面内置「后端服务」配置面板：默认同源，Pages 场景下可填任意后端地址并记住 |
| 演示模式 | `python run.py --mock` 不下载任何模型即可跑通前端 → 后端 → A/B/C 文稿 → 导出的完整链路 |

> 说话人分离的 A/B/C 标签按**首次出现顺序**分配，与"谁在镜头左边"无关，只表示"是不同的人"。

---

## 2. 目录结构

```
voxscript/
├─ run.py                     # 启动入口（含 --mock / --port / --reload）
├─ requirements.txt           # Python 依赖清单
├─ Dockerfile                 # 后端镜像（含 ffmpeg，可一键部署到容器平台）
├─ docker-compose.yml         # 本地 / 服务器一键起容器（可选）
├─ .dockerignore              # 构建镜像时排除密钥与数据
├─ .gitignore                 # 覆盖 .env、__pycache__、data/（任务数据）等
├─ .env.example               # 配置模板（复制为 .env 后修改）
├─ README.md
├─ docs/                      # ← 前端页面，同时是 GitHub Pages 的发布目录
│  ├─ index.html              # 单页界面
│  ├─ styles.css              # 设计系统（深色录音棚风格 + 亮色主题）
│  ├─ app.js                  # 交互逻辑（提交 / 轮询 / 渲染 / 导出 / 后端地址配置）
│  ├─ config.js               # 可选的"默认后端地址"（部署时可改）
│  └─ .nojekyll               # 让 GitHub Pages 跳过 Jekyll 处理
├─ backend/
│  ├─ main.py                 # FastAPI 服务与全部接口（同时按白名单托管 docs/ 页面）
│  ├─ config.py               # 配置读取（环境变量 / .env）
│  ├─ schemas.py              # 请求 / 响应数据模型
│  ├─ store.py                # 任务状态仓库（内存 + 磁盘双写）
│  ├─ pipeline.py             # 任务流水线编排
│  ├─ utils.py                # URL 安全校验、说话人配色、时间格式化
│  └─ services/
│     ├─ downloader.py        # yt-dlp 链接解析与下载
│     ├─ audio.py             # ffmpeg 抽取音频、时长探测
│     ├─ asr.py               # faster-whisper / OpenAI 兼容 / mock
│     ├─ diarization.py       # pyannote 说话人分离
│     ├─ align.py             # 文稿与说话人对齐、A/B/C 标注与统计
│     ├─ exporter.py          # TXT / SRT / VTT / MD / JSON 导出
│     └─ mock.py              # 假文稿引擎（演示与冒烟测试）
└─ data/                      # 运行时生成：任务数据、音频、文稿（可随时删除，已被 .gitignore 忽略）
```

> `docs/` 与 `backend/` 物理分离：网页根目录只暴露白名单里的几个静态文件，
> 后端源码、`.env`、任务数据都不会被当成静态资源下载（避免部署后拉取到源码）。

---

## 3. 环境要求

| 组件 | 要求 |
| --- | --- |
| 操作系统 | Windows 10/11、macOS、Linux（Docker 部署时无要求） |
| Python | 3.9 – 3.12（推荐 3.11） |
| ffmpeg | **强烈建议安装**，用于抽音频与解析部分媒体流。未安装时会自动降级使用 `imageio-ffmpeg` 自带的二进制（已在 requirements 中，常见格式可用；冷门编码请装系统版 ffmpeg）。Docker 镜像里已内置 |
| 显卡 | 可选。有 NVIDIA GPU 时 faster-whisper 与 pyannote 会自动使用 CUDA，速度提升 5–20 倍 |
| 内存 | 纯 CPU 跑 `small` 模型建议 ≥ 8 GB；容器平台选 2 GB 起（`tiny`/`base` 模型） |

### 3.1 安装 ffmpeg

```powershell
# Windows（任选其一）
winget install Gyan.FFmpeg
# 或 choco install ffmpeg

# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install -y ffmpeg
```

安装后执行 `ffmpeg -version` 能输出版本号即可。若不想装到系统 PATH，可安装 `imageio-ffmpeg`（已在 requirements 中）作为兜底，或在 `.env` 中用 `FFMPEG_BINARY` 指定 ffmpeg 可执行文件的绝对路径。

### 3.2 安装 Python 依赖

```bash
cd voxscript
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -U pip
pip install -r requirements.txt
```

**关于 PyTorch**：`torch` / `torchaudio` 在 requirements 中按默认源安装（CPU 版）。
需要 GPU 加速时，请按显卡驱动单独安装对应 CUDA 版本，例如：

```bash
# CUDA 12.1
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
# 仅 CPU
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

---

## 4. 本地运行（完整站点）

```bash
# 1) 准备配置（可全部留空，除说话人分离需要 HF_TOKEN）
copy .env.example .env      # Windows；macOS / Linux 用 cp .env.example .env

# 2) 常规启动
python run.py

# 指定端口 / 开发热重载
python run.py --port 9000 --reload

# 零模型演示模式：不下载模型、不需要 HF Token，即可跑通「上传 → 转写 → A/B/C 分段 → 导出」
python run.py --mock
```

浏览器打开 <http://127.0.0.1:8000> 即可使用 —— 这种情况下**前端与后端同源**，页面默认就用同源地址，无需任何配置。

> **一分钟自检**：`python run.py --mock` 启动后，切到「上传文件」标签随便传一段音频（或视频），几秒内就能看到带 A / B / C 说话人标签的分段时间轴，并能导出 TXT / SRT。
> 演示模式的文稿由本地假引擎生成，只用于验证链路是否通畅，**不是真实识别结果**；要得到真实文稿，去掉 `--mock`，按 §6.3 配置 `HF_TOKEN` 后正常启动即可。

### 4.1 使用步骤

1. **粘贴链接** 或 **上传本地文件**（两种方式二选一）
2. 需要精确控制时展开「高级选项」：识别引擎、模型大小、语言、推理设备、是否做说话人分离、说话人数、专有名词提示
   - 人名、品牌名、专业术语识别不准时，把它们填进"专有名词提示"能明显提升准确率
   - 已知是 2 人对话时，把"说话人数"设为 2 比自动判断更稳
3. 点击「开始转写」，页面会分阶段显示进度
4. 完成后：
   - 顶部统计卡显示时长、说话人数、段数、字数、识别语言
   - 通过说话人筛选按钮只看某一个人的发言
   - 搜索框支持全文关键词搜索并高亮
   - 时间轴视图下点击任意句子可跳转播放对应音频位置
5. 导出：TXT / SRT / VTT / MD / JSON，或「复制全文」只复制当前筛选结果

---

## 5. 部署 A：前端放到 GitHub Pages

### 5.1 一次性配置

1. 把本项目推到 GitHub 仓库 `ablcy/zwz`（`docs/` 目录必须一起提交）：

   ```bash
   git init
   git remote add origin https://github.com/ablcy/zwz.git
   git add .
   git commit -m "feat: VoxScript 前端 Pages 形态 + 后端容器化"
   git push -u origin main
   ```

   > `.gitignore` 已经排除了 `.env`、`__pycache__/`、`data/`（任务数据与模型）等，可以放心 `git add .`。

2. 打开仓库 **Settings → Pages**：
   - **Source** 选 `Deploy from a branch`
   - **Branch** 选 `main`，**Folder** 选 `/docs`，保存

3. 等 1 分钟左右，访问：**<https://ablcy.github.io/zwz>**

> `docs/.nojekyll` 的作用：让 Pages 跳过 Jekyll 构建，`_` 开头或特殊命名的资源不会被吞掉，静态文件按原样发布。
> 仓库名是 `zwz`，所以站点在子路径 `/zwz/` 下；`docs/index.html` 里的资源引用全部用了**相对路径**，因此本地直开和 Pages 子路径都能正常工作。

### 5.2 打开页面后要做什么

Pages 上只有静态页面，**首次访问时页面顶部会提示"未配置后端"**（这是预期行为）。此时：

1. 按 §6 部署好后端（Docker 或直接 `python run.py`），拿到它的公网地址，例如 `https://voxscript-api.example.com`
2. 回到 Pages 页面，在顶部「**后端服务**」输入框填入该地址
3. 点击「**保存并测试**」，看到右上角状态变为"**服务就绪**"即可正常使用

### 5.3 后端地址的优先级（页面如何决定请求发往哪里）

页面按以下顺序确定后端地址，**先命中先生效**：

| 优先级 | 来源 | 说明 |
| --- | --- | --- |
| 1 | URL 参数 `?api=https://xxx` | 临时指定，同时会写入本地存储，如 `https://ablcy.github.io/zwz/?api=https://voxscript-api.example.com` |
| 2 | 浏览器本地存储（localStorage） | 用户在「后端服务」面板里保存过的地址（留空表示"同源"，会被记住） |
| 3 | `docs/config.js` 里的 `window.VOXSCRIPT_API_BASE` | 改这一行可以让**所有访客**打开页面就默认连到你的后端 |
| 4 | 同源（空） | 默认值：前端由后端自己托管时（`python run.py`）用这一条 |

`docs/config.js` 内容：

```js
// 部署到 GitHub Pages 时，把这里改成你的后端公网地址，所有访客默认使用它
// 留空 = 与页面同源（本地 python run.py 时的默认行为）
window.VOXSCRIPT_API_BASE = "";
```

**强制要求**：Pages 是 HTTPS，浏览器会拦截 HTTPS 页面发往 HTTP 后端的请求（混合内容）。
所以你的后端必须是 **HTTPS**（容器平台一般自动给 https 域名，自建服务器请用 Nginx/Caddy 配证书）。

### 5.4 页面提示规则（不会静默失败）

| 情况 | 页面表现 |
| --- | --- |
| 静态托管 + 未配置后端 | 右上角状态变为"未配置后端"，配置面板下方给出红色说明，点击「开始转写」会被拦下并提示先填地址 |
| 后端连不上（地址错 / 服务没起 / 跨域被拦 / http-https 混用） | 状态变为"服务未连接"，并显示具体原因与排查建议（含 CORS 与混合内容提示） |
| 地址填的不是本后端（返回了 HTML 之类） | 明确提示"接口返回了非接口数据，通常说明地址填错了，或指向了一个纯静态站点" |
| 后端正常但有依赖缺失（如未装 ffmpeg） | 状态变为"服务就绪 · N 项提示"，并把后端返回的具体警告列在页面上 |

---

## 6. 部署 B：后端服务（容器平台）

后端提供者需要一个能跑 **Python + ffmpeg** 的环境。最省事的方式是 Docker —— 仓库里已带 `Dockerfile`。

### 6.1 用 Dockerfile 构建与运行

```bash
# 在项目根目录
docker build -t voxscript .

docker run -d --name voxscript \
  -p 8000:8000 \
  -e HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx \
  -e CORS_ORIGINS=https://ablcy.github.io \
  -v voxscript-data:/app/data \
  voxscript
```

打开 <http://localhost:8000> 可以看到完整站点（容器同时托管了 `docs/` 页面），
<http://localhost:8000/api/health> 是健康检查地址。

Dockerfile 的关键设计：

| 设计 | 原因 |
| --- | --- |
| 基于 `python:3.11-slim` 并 `apt install ffmpeg` | 抽音频、解析媒体流必需 |
| 默认装 **CPU 版 torch**（`--build-arg TORCH_INDEX=.../whl/cpu`） | 避免拉入数 GB 的 CUDA 依赖；有 GPU 时用 `--build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu121` 覆盖 |
| 用非 root 用户 `vox` 运行 | 降低容器逃逸风险 |
| 数据与模型缓存统一放在 `/app/data`（`VOLUME` 建议挂载） | 容器重建不用重新下载模型，任务数据可持久化 |
| 内置 `HEALTHCHECK`（`/api/health`） | 容器平台可自动判定服务是否健康 |
| 只 `COPY backend/ docs/ run.py requirements.txt` | 镜像里不含 `data/`、`.env`、`.git`（配合 `.dockerignore`） |

### 6.2 docker compose（本地或服务器一把起）

```bash
copy .env.example .env     # 先按需填好 HF_TOKEN 等
docker compose up -d --build
docker compose logs -f
```

`docker-compose.yml` 已预设：端口 `8000:8000`、`VOXSCRIPT_HOST=0.0.0.0`、数据卷 `voxscript-data:/app/data`、`CORS_ORIGINS=https://ablcy.github.io`。

### 6.3 托管到容器平台（Render / Railway / Fly.io / Koyeb / 云服务器）

各家控制台细节不同，但**要填的东西完全一样**：

| 配置项 | 值 |
| --- | --- |
| 构建方式 | Dockerfile（仓库根目录，无需自定义构建命令） |
| 暴露端口 | `8000`（平台一般用 `PORT` 变量注入时，把容器端口设为 8000 或映射即可） |
| 环境变量 | `VOXSCRIPT_HOST=0.0.0.0`、`VOXSCRIPT_DATA_DIR=/app/data`、`HF_TOKEN=...`、`CORS_ORIGINS=https://ablcy.github.io`、可选 `ASR_BACKEND` / `WHISPER_MODEL` / `YTDLP_PROXY` 等 |
| 持久化 | 挂载一个卷到 `/app/data`（存模型缓存与任务结果；不挂也能跑，只是每次重启重新下载模型） |
| 健康检查路径 | `/api/health` |
| 资源建议 | 2 vCPU / 2–4 GB 内存起步；纯 CPU 建议 `WHISPER_MODEL=base` 或 `small`，`WHISPER_DEVICE=cpu`、`WHISPER_COMPUTE_TYPE=int8` |
| 公网地址 | 平台给的 https 域名，填入 Pages 页面的「后端服务」输入框 |

> 想要更快、更省的方案：把 `ASR_BACKEND` 设为 `openai`，`OPENAI_BASE_URL` / `OPENAI_API_KEY` 指向云端语音识别服务，
> 后端就只做下载、切片与对齐，**1 核 1 GB 的小机器也能跑**，模型也不用下载（说话人分离仍建议保留 token 或关闭它）。

部署完成后自检：

```bash
curl https://你的后端域名/api/health
# {"status":"ok","ffmpeg":true,"asr_backend":"faster-whisper","warnings":[...]}
```

`warnings` 里如果有内容，按提示处理（例如未装 ffmpeg、未配 HF_TOKEN）。

### 6.4 前后端对接检查清单

- [ ] 后端公网可访问，`/api/health` 返回 200 且 `status=ok`
- [ ] 后端是 **https**（Pages 是 https，混用 http 会被浏览器拦）
- [ ] `CORS_ORIGINS` 包含 `https://ablcy.github.io`（或保持 `*`）
- [ ] Pages 页面「后端服务」填的地址**不带** `/#`、末尾斜杠可有可无（会自动规整）
- [ ] 点击「保存并测试」后状态显示"服务就绪"；若失败，页面会给出原因

---

## 7. 配置（.env）

复制模板后按需修改，**所有项都有默认值，不配置也能跑**（说话人分离除外）：

```bash
copy .env.example .env      # Windows
cp .env.example .env        # macOS / Linux
```

### 7.1 服务

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VOXSCRIPT_HOST` | `127.0.0.1` | 监听地址。容器 / 服务器部署必须改为 `0.0.0.0` |
| `VOXSCRIPT_PORT` | `8000` | 服务端口 |
| `VOXSCRIPT_DATA_DIR` | `./data` | 任务数据、音频与结果存放目录（容器内建议 `/app/data`） |
| `CORS_ORIGINS` | `*` | 允许跨域的来源，逗号分隔。默认放开任意来源（不携带 Cookie）；生产建议改成 `https://ablcy.github.io` |
| `MAX_WORKERS` | `1` | 同时处理的任务数。模型常驻显存，建议保持 1；纯远程接口可调大 |
| `MAX_UPLOAD_MB` | `800` | 单文件上传上限（MB） |

### 7.2 语音识别

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ASR_BACKEND` | `faster-whisper` | 识别引擎：`faster-whisper`（本地）/ `openai`（远程）/ `mock`（演示） |
| `WHISPER_MODEL` | `small` | 模型：`tiny` / `base` / `small` / `medium` / `large-v3`。越大越准、越慢 |
| `WHISPER_DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `WHISPER_COMPUTE_TYPE` | `auto` | `auto`（GPU 用 float16，CPU 用 int8）/ `int8` / `float16` / `float32` |
| `WHISPER_CACHE_DIR` | 空 | 模型下载缓存目录，默认在 `data/models` |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 任意 OpenAI 兼容服务的地址 |
| `OPENAI_API_KEY` | 空 | 远程识别所需的 API Key（**必须由你自己填写**） |
| `OPENAI_ASR_MODEL` | `whisper-1` | 远程识别模型名，如 `whisper-large-v3`、`FunAudioLLM/SenseVoiceSmall` |
| `OPENAI_TIMEOUT` | `300` | 远程接口超时（秒） |

> 首次使用本地引擎会自动下载模型（`small` 约 460 MB），请保证网络可访问 HuggingFace；
> 国内网络可在 `.env` 中设置 `HF_ENDPOINT=https://hf-mirror.com` 走镜像（容器里可加 `-e HF_ENDPOINT=...`）。

### 7.3 说话人分离

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DIARIZATION_ENABLED` | `true` | 总开关。关闭后全部文稿标为说话人 A |
| `HF_TOKEN` | 空 | **必需**。HuggingFace 访问令牌 |
| `DIARIZATION_MODEL` | `pyannote/speaker-diarization-3.1` | 分离模型 |
| `DIARIZATION_NUM_SPEAKERS` | `0` | 默认说话人数，`0` = 自动判断。也可在页面「高级选项」按任务指定 |
| `DIARIZATION_FALLBACK` | `true` | 分离失败时是否降级为单一说话人 A（不中断出稿） |

**获得 HF_TOKEN 的三步**（免费）：

1. 注册 / 登录 <https://huggingface.co>
2. 进入 <https://huggingface.co/settings/tokens> 新建一个 `read` 权限的 Token
3. 依次打开 <https://huggingface.co/pyannote/speaker-diarization-3.1> 与
   <https://huggingface.co/pyannote/segmentation-3.0>，点击 **Agree to access repository**

把 Token 填进 `.env` 的 `HF_TOKEN=`（容器则通过 `-e HF_TOKEN=...`）即可。首次运行会下载约 30 MB 模型。

### 7.4 下载（yt-dlp）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `YTDLP_COOKIES` | 空 | cookies.txt 的绝对路径（浏览器"导出 Cookie"扩展可生成） |
| `YTDLP_COOKIES_FROM_BROWSER` | 空 | 直接从浏览器读取 Cookie，如 `chrome` / `edge` / `firefox`（服务器上一般不可用） |
| `YTDLP_PROXY` | 空 | 代理，如 `http://127.0.0.1:7890`，用于地区限制或网络受限环境（**海外服务器跑国内平台时几乎必备**） |
| `FFMPEG_BINARY` | 空 | ffmpeg 可执行文件路径（不在 PATH 时使用） |

> 抖音 / 小红书的部分内容需要登录态；视频号多为加密流，若解析失败请配置 Cookie 或改用"上传本地文件"。

---

## 8. 接口说明（后端）

服务启动后可访问 `<后端地址>/docs` 查看交互式 API 文档。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 返回 `docs/index.html`（后端自托管页面） |
| GET | `/api/health` | 服务状态、ffmpeg / GPU / 依赖检测与提示（容器健康检查用） |
| GET | `/api/config` | 当前默认配置（不含密钥）与支持的平台列表 |
| POST | `/api/tasks` | `{ "url": "...", "options": {...} }` 创建链接任务 |
| POST | `/api/tasks/upload` | `multipart`：`file` + `options`(JSON 字符串) 创建上传任务 |
| GET | `/api/tasks` | 最近任务列表 |
| GET | `/api/tasks/{id}` | 任务进度与状态 |
| GET | `/api/tasks/{id}/result` | 转写结果（未完成时返回 202） |
| GET | `/api/tasks/{id}/media` | 抽取出的音频流（页面播放器） |
| GET | `/api/tasks/{id}/export?format=txt\|srt\|vtt\|md\|json` | 导出文稿 |
| DELETE | `/api/tasks/{id}` | 删除任务并清理其媒体文件 |

`options` 可选项（均为可选）：

```json
{
  "asr_backend": "faster-whisper",
  "model": "small",
  "language": "zh",
  "device": "auto",
  "diarization": true,
  "num_speakers": 0,
  "initial_prompt": "声刻, VoxScript, pyannote",
  "vad_filter": true,
  "word_timestamps": true
}
```

> 除 `/api/*` 外的路径只按白名单返回 `index.html`、`styles.css`、`app.js`、`config.js`、`favicon.svg`、`.nojekyll`，
> 其余一律 404 —— 后端源码、`.env`、任务数据不会通过 HTTP 暴露。

---

## 9. 常见问题

**Q1：这个工具需要数据库吗？**
**不需要。** 全项目零数据库依赖：任务状态由 `backend/store.py` 在内存中维护并同步写入磁盘 JSON，任务产物（原始媒体、`audio_16k.wav`、`result.json`、`exports/`）按任务 ID 分目录放在 `data/` 下，重启后通过扫描该目录恢复历史。这样部署最简单（一个容器 + 一个数据卷即可）。若将来要做多实例横向扩展，再考虑把状态换成 Redis / SQLite 即可，接口层不用动。

**Q2：Pages 页面打开后提示"未配置后端"，能用吗？**
不能直接转写。Pages 只托管界面，请按 §6 部署后端，把后端地址填进页面顶部「后端服务」并「保存并测试」。

**Q3：为什么页面报"无法连接后端服务"？**
按顺序排查：① 后端是否在运行（打开 `<后端地址>/api/health` 看有没有 JSON）；② 地址是否写错（不要带多余路径）；③ 是否 http / https 混用（Pages 是 https，后端也必须是 https）；④ `CORS_ORIGINS` 是否放开了 Pages 域名；⑤ 服务器防火墙 / 平台端口是否开放。

**Q4：提示"未检测到 ffmpeg"？**
按 §3.1 装系统 ffmpeg，或设 `FFMPEG_BINARY=D:\path\to\ffmpeg.exe`；用 Docker 部署则镜像里已内置，不会出现该提示。改完重启服务。

**Q5：说话人分离没生效，全部是 A？**
三种可能：① 未配置 `HF_TOKEN`；② 未同意 pyannote 两个模型的使用协议；③ 任务里把"说话人分离"设成了关闭。页面会在结果区显示具体原因（"降级说明"）。

**Q6：链接解析失败 / 提示需要登录？**
配置 `YTDLP_COOKIES`（cookies.txt 路径）或 `YTDLP_COOKIES_FROM_BROWSER=chrome`；海外服务器请配置 `YTDLP_PROXY`。视频号加密流建议下载后用"上传本地文件"处理。

**Q7：识别速度很慢？**
CPU 上 `small` 处理 10 分钟音频约需 3–8 分钟。可换 `tiny` / `base`，或改用 `ASR_BACKEND=openai` 调用远程接口，或安装 CUDA 版 torch 启用 GPU。

**Q8：识别有错别字、漏字？**
换更大的模型（`medium` / `large-v3`）、指定正确语言（不要用自动检测）、在"专有名词提示"里补上专有名词。

**Q9：数据存在哪里？可以删吗？**
全部在 `data/` 目录（每个任务一个子目录）。直接删目录即可清理（容器部署则删数据卷或容器内子目录），也可在页面调 `DELETE /api/tasks/{id}`。`data/` 与 `.env` 都已被 `.gitignore` / `.dockerignore` 排除，不会进仓库、不会进镜像。

**Q10：想换识别服务，比如国内的语音大模型？**
把 `ASR_BACKEND` 设为 `openai`，`OPENAI_BASE_URL` 指向该服务的 OpenAI 兼容地址（一般形如 `https://xxx/v1`），`OPENAI_API_KEY` 填你的 Key，`OPENAI_ASR_MODEL` 填模型名即可，代码无需改动。

**Q11：可以只部署前端，后端以后再补吗？**
可以。先把 `docs/` 推到 Pages，页面能正常打开、能看到完整界面（转写会被提示"未配置后端"）；后端部署好之后，在页面上填地址即可，无需改代码、无需重新发布。

---

## 10. 技术选型说明

| 环节 | 方案 | 理由 |
| --- | --- | --- |
| 取流 | yt-dlp | 覆盖平台最广、社区维护活跃；抖音/小红书/B站适配成熟 |
| 抽音频 | ffmpeg | 事实标准，格式兼容性最好；统一 16 kHz 单声道满足两套模型的输入要求 |
| 转写 | faster-whisper（CTranslate2 后端） | 同精度下比原版 whisper 快 4 倍以上、显存占用更低，CPU 上也能实用 |
| 说话人分离 | pyannote.audio 3.1 | 开源方案中准确率与稳定性最好，与 whisper 片段做时间重叠对齐即可得到 A/B/C 逐句标注 |
| 服务 | FastAPI + Uvicorn | 自带异步与 OpenAPI 文档，上传大文件与长任务进度回传实现简单 |
| 前端 | 原生 HTML/CSS/JS | 零构建、零依赖，`python run.py` 即用，且天然适配 GitHub Pages 静态托管 |
| 存储 | 文件系统（`data/`） | 单机单实例场景下最简单可靠，无需引入数据库；任务与产物直接可查可删 |
| 交付 | 前端 `docs/` + 后端 Dockerfile | 静态页面走 Pages（免费、全球 CDN），算力需求放在容器平台按需扩缩 |

---

## 11. 免责声明

请仅对你**有权处理**的音视频内容使用本工具（如自己的作品、已获授权的素材）。
下载与转写他人内容可能涉及平台服务条款与著作权限制，请自行确认合规性。
素材只会上传到你**自己部署的后端**（选用 `openai` 远程识别引擎时，音频片段会发送给对应的识别服务商）。
