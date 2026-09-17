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

---

## 1. 功能一览

| 能力 | 说明 |
| --- | --- |
| 链接解析 | 基于 yt-dlp，覆盖抖音、小红书、视频号、哔哩哔哩、快手、YouTube 等上千站点；支持 Cookie / 代理配置以应对登录可见内容 |
| 本地上传 | 直接上传 mp4 / mov / mkv / webm / mp3 / wav / m4a / flac 等，全程本地处理，素材不出本机 |
| 音频抽取 | ffmpeg 统一转成 16kHz 单声道 WAV，作为识别与说话人分离的标准输入 |
| 语音转文字 | 默认 **faster-whisper** 本地推理；可一键切换到任意 **OpenAI 兼容** 接口（OpenAI / Groq / SiliconFlow / 本地 vLLM 等） |
| 说话人分离 | **pyannote.audio 3.1** 计算说话人时间段，再与识别片段做时间重叠对齐，按首次出现顺序标注 A / B / C … |
| 文稿展示 | 时间轴 / 纯文稿双视图、按说话人筛选、全文搜索高亮、点击句子跳转播放对应位置 |
| 导出 | TXT（纯文稿，带说话人前缀）、SRT / VTT（标准字幕）、MD（含说话人统计的完整报告）、JSON（结构化原始数据） |
| 任务管理 | 进度分阶段实时回传（获取媒体 → 提取音频 → 转文字 → 说话人分离 → 对齐 → 落盘），结果落盘，进程重启后仍可查历史 |
| 演示模式 | `python run.py --mock` 不下载任何模型即可跑通前端 → 后端 → A/B/C 文稿 → 导出的完整链路 |

> 说话人分离的 A/B/C 标签按**首次出现顺序**分配，与"谁在镜头左边"无关，只表示"是不同的人"。

---

## 2. 目录结构

```
voxscript/
├─ run.py                     # 启动入口（含 --mock / --port / --reload）
├─ requirements.txt           # Python 依赖清单
├─ .env.example               # 配置模板（复制为 .env 后修改）
├─ README.md
├─ backend/
│  ├─ main.py                 # FastAPI 服务与全部接口
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
├─ frontend/
│  ├─ index.html              # 单页界面
│  ├─ styles.css              # 设计系统（深色录音棚风格 + 亮色主题）
│  └─ app.js                  # 交互逻辑（提交 / 轮询 / 渲染 / 导出）
└─ data/                      # 运行时生成：任务数据、音频、文稿（可随时删除）
```

---

## 3. 环境要求

| 组件 | 要求 |
| --- | --- |
| 操作系统 | Windows 10/11、macOS、Linux |
| Python | 3.9 – 3.12（推荐 3.11） |
| ffmpeg | **强烈建议安装**，用于抽音频与解析部分媒体流。未安装时会自动降级使用 `imageio-ffmpeg` 自带的二进制（已在 requirements 中，常见格式可用；冷门编码请装系统版 ffmpeg） |
| 显卡 | 可选。有 NVIDIA GPU 时 faster-whisper 与 pyannote 会自动使用 CUDA，速度提升 5–20 倍 |
| 内存 | 纯 CPU 跑 `small` 模型建议 ≥ 8 GB |

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

## 4. 配置（.env）

复制模板后按需修改，**所有项都有默认值，不配置也能跑**（说话人分离除外）：

```bash
# Windows
copy .env.example .env
# macOS / Linux
cp .env.example .env
```

### 4.1 服务

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VOXSCRIPT_HOST` | `127.0.0.1` | 监听地址。改为 `0.0.0.0` 可供局域网访问 |
| `VOXSCRIPT_PORT` | `8000` | 服务端口 |
| `VOXSCRIPT_DATA_DIR` | `./data` | 任务数据、音频与结果存放目录 |
| `MAX_WORKERS` | `1` | 同时处理的任务数。模型常驻显存，建议保持 1；纯远程接口可调大 |
| `MAX_UPLOAD_MB` | `800` | 单文件上传上限（MB） |

### 4.2 语音识别

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
> 国内网络可在 `.env` 中设置 `HF_ENDPOINT=https://hf-mirror.com` 走镜像。

### 4.3 说话人分离

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

把 Token 填进 `.env` 的 `HF_TOKEN=` 即可。首次运行会下载约 30 MB 模型。

### 4.4 下载（yt-dlp）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `YTDLP_COOKIES` | 空 | cookies.txt 的绝对路径（浏览器"导出 Cookie"扩展可生成） |
| `YTDLP_COOKIES_FROM_BROWSER` | 空 | 直接从浏览器读取 Cookie，如 `chrome` / `edge` / `firefox` |
| `YTDLP_PROXY` | 空 | 代理，如 `http://127.0.0.1:7890`，用于地区限制或网络受限环境 |
| `FFMPEG_BINARY` | 空 | ffmpeg 可执行文件路径（不在 PATH 时使用） |

> 抖音 / 小红书的部分内容需要登录态；视频号多为加密流，若解析失败请配置 Cookie 或改用"上传本地文件"。

---

## 5. 启动与使用

### 5.1 启动

```bash
# 常规启动（读取 .env）
python run.py

# 指定端口 / 开发热重载
python run.py --port 9000 --reload

# 零模型演示模式：不下载模型、不需要 HF Token，即可跑通「上传 → 转写 → A/B/C 分段 → 导出」
python run.py --mock
```

启动后浏览器打开 <http://127.0.0.1:8000> 即可使用。

> **一分钟自检**：`python run.py --mock` 启动后，切到「上传文件」标签随便传一段音频（或视频），几秒内就能看到带 A / B / C 说话人标签的分段时间轴，并能导出 TXT / SRT。
> 演示模式的文稿由本地假引擎生成，只用于验证链路是否通畅，**不是真实识别结果**；要得到真实文稿，去掉 `--mock`，按 §4.3 配置 `HF_TOKEN` 后正常启动即可。
> 说明：本地已是 16 kHz 单声道 WAV 时可直接识别；其他格式会先经过 ffmpeg（未装系统 ffmpeg 时用 imageio-ffmpeg 兜底）。

### 5.2 使用步骤

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

### 5.3 导出格式对照

| 格式 | 内容 | 典型用途 |
| --- | --- | --- |
| `txt` | `[时间戳] 说话人: 文本` 逐行文稿 + 末尾说话人统计 | 快速阅读、二次编辑 |
| `srt` | 标准字幕，整行前置 `[A]` 说话人标记 | 剪映 / Premiere / 播放器导入 |
| `vtt` | WebVTT，可选 `<v A>` 说话人标签 | 网页播放器、在线课程 |
| `md` | 标题 + 元信息 + 说话人统计表 + 时间轴文稿 | 归档、发布到知识库 |
| `json` | 结构化分段（含词级时间戳、原始说话人标签） | 二次开发、数据分析 |

---

## 6. 接口说明（后端）

服务启动后可访问 <http://127.0.0.1:8000/docs> 查看交互式 API 文档。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 服务状态、ffmpeg / GPU / 依赖检测与提示 |
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

---

## 7. 常见问题

**Q：页面右上角提示"服务未连接"？**
后端没起来。检查终端是否报错，以及 `python run.py` 是否在项目根目录执行。

**Q：提示"未检测到 ffmpeg"？**
按 §3.1 安装 ffmpeg，或在 `.env` 中设置 `FFMPEG_BINARY=D:\path\to\ffmpeg.exe`，然后重启服务。

**Q：说话人分离没生效，全部是 A？**
三种可能：① 未配置 `HF_TOKEN`；② 未同意 pyannote 两个模型的使用协议；③ 任务里把"说话人分离"设成了关闭。页面会在结果区显示具体原因（"降级说明"）。

**Q：链接解析失败 / 提示需要登录？**
在 `.env` 中配置 `YTDLP_COOKIES`（cookies.txt 路径）或 `YTDLP_COOKIES_FROM_BROWSER=chrome`；有地区限制时再配置 `YTDLP_PROXY`。视频号加密流建议下载后用"上传本地文件"处理。

**Q：识别速度很慢？**
CPU 上 `small` 处理 10 分钟音频约需 3–8 分钟。可换 `tiny` / `base`，或改用 `ASR_BACKEND=openai` 调用远程接口，或安装 CUDA 版 torch 启用 GPU。

**Q：识别有错别字、漏字？**
换更大的模型（`medium` / `large-v3`）、指定正确语言（不要用自动检测）、在"专有名词提示"里补上专有名词。

**Q：数据存在哪里？可以删吗？**
全部在 `data/` 目录（每个任务一个子目录：原始媒体、`audio_16k.wav`、`result.json`、`exports/`）。直接删目录即可清理，也可在页面上调 `DELETE /api/tasks/{id}`。

**Q：想换识别服务，比如国内的语音大模型？**
把 `ASR_BACKEND` 设为 `openai`，`OPENAI_BASE_URL` 指向该服务的 OpenAI 兼容地址（一般形如 `https://xxx/v1`），`OPENAI_API_KEY` 填你的 Key，`OPENAI_ASR_MODEL` 填模型名即可，代码无需改动。

---

## 8. 技术选型说明

| 环节 | 方案 | 理由 |
| --- | --- | --- |
| 取流 | yt-dlp | 覆盖平台最广、社区维护活跃；抖音/小红书/B站适配成熟 |
| 抽音频 | ffmpeg | 事实标准，格式兼容性最好；统一 16 kHz 单声道满足两套模型的输入要求 |
| 转写 | faster-whisper（CTranslate2 后端） | 同精度下比原版 whisper 快 4 倍以上、显存占用更低，CPU 上也能实用 |
| 说话人分离 | pyannote.audio 3.1 | 开源方案中准确率与稳定性最好，与 whisper 片段做时间重叠对齐即可得到 A/B/C 逐句标注 |
| 服务 | FastAPI + Uvicorn | 自带异步与 OpenAPI 文档，上传大文件与长任务进度回传实现简单 |
| 前端 | 原生 HTML/CSS/JS | 零构建、零依赖，`python run.py` 即用，便于部署与二次开发 |

---

## 9. 免责声明

请仅对你**有权处理**的音视频内容使用本工具（如自己的作品、已获授权的素材）。
下载与转写他人内容可能涉及平台服务条款与著作权限制，请自行确认合规性。本工具默认在本地处理，不上传任何素材到第三方（选用 `openai` 远程识别引擎时除外）。
*（内容由AI生成，仅供参考）*
