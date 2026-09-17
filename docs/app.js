/* ==========================================================================
   声刻 VoxScript · 前端交互
   纯原生 JS，无构建步骤。负责：任务提交 / 进度轮询 / 结果渲染 / 导出
   ========================================================================== */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const FALLBACK_PALETTE = [
    "#6366f1", "#06b6d4", "#f59e0b", "#ec4899", "#10b981",
    "#8b5cf6", "#ef4444", "#0ea5e9", "#84cc16", "#f97316",
  ];

  const state = {
    apiBase: "",
    taskId: null,
    result: null,
    pollTimer: null,
    speaker: "all",
    view: "timeline",
    query: "",
    activeIndex: -1,
    speakerColors: {},
    duration: 0,
  };

  /* ------------------------------------------------------------------ 工具 */
  function toast(message, kind) {
    const wrap = $("#toastWrap");
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "");
    el.textContent = message;
    wrap.appendChild(el);
    setTimeout(() => {
      el.classList.add("out");
      setTimeout(() => el.remove(), 300);
    }, kind === "err" ? 5200 : 3200);
  }

  function clock(seconds, withMs) {
    const s = Math.max(0, Number(seconds) || 0);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = Math.floor(s % 60);
    const pad = (n) => String(n).padStart(2, "0");
    const base = (h > 0 ? pad(h) + ":" : "") + pad(m) + ":" + pad(sec);
    if (!withMs) return base;
    return base + "." + String(Math.floor((s % 1) * 10));
  }

  function shortClock(seconds) {
    const s = Math.max(0, Number(seconds) || 0);
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return (m > 0 ? m + "分" : "") + sec + "秒";
  }

  function humanSize(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0, n = bytes;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return n.toFixed(n >= 10 || i === 0 ? 0 : 1) + " " + units[i];
  }

  function escapeHtml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ------------------------------------------------------- 后端地址解析 */
  const API_BASE_KEY = "voxscript-api-base";

  // 纯静态托管判定：这类域名（或 file:// 本地打开）上不存在后端服务
  const IS_STATIC_HOST =
    location.protocol === "file:" ||
    /(^|\.)(github|gitee|gitlab|netlify|vercel|pages\.dev)\.(io|app|dev)$/i.test(location.hostname) ||
    /\.github\.io$/i.test(location.hostname);

  function normalizeBase(value) {
    let base = String(value == null ? "" : value).trim();
    if (!base || base === "/") return "";
    if (!/^https?:\/\//i.test(base)) base = "https://" + base.replace(/^\/+/, "");
    return base.replace(/\/+$/, "");
  }

  function resolveApiBase() {
    let query = null;
    try { query = new URLSearchParams(location.search).get("api"); } catch (e) { query = null; }
    if (query !== null && isVideoShareLink(query)) {
      // 分享的链接里误把视频地址写成了 api 参数：忽略且不落盘，避免污染本地后端配置
      rejectedApiQuery = query;
    } else if (query !== null) {
      const base = normalizeBase(query);
      try { localStorage.setItem(API_BASE_KEY, base); } catch (e) { /* 忽略存储失败 */ }
      return base;
    }
    let stored = null;
    try { stored = localStorage.getItem(API_BASE_KEY); } catch (e) { stored = null; }
    if (stored !== null) return normalizeBase(stored);          // 用户显式设置过（含"留空=同源"）
    return normalizeBase(window.VOXSCRIPT_API_BASE || "");      // 回落到 config.js 里的全站默认值
  }

  function apiUrl(path) {
    const p = String(path || "");
    const suffix = p.startsWith("/") ? p : "/" + p;
    return state.apiBase ? state.apiBase + suffix : suffix;
  }

  function baseHostLabel() {
    if (!state.apiBase) return "同源";
    try { return new URL(state.apiBase).host; } catch (e) { return state.apiBase; }
  }

  /* ------------------------------- 视频链接防呆（后端地址框误填视频分享链接） */
  // 已知视频平台域名（含分享短链域）：命中即判定"明显是视频分享链接"
  const VIDEO_SHARE_DOMAINS = [
    "douyin.com", "iesdouyin.com", "tiktok.com",            // 抖音 / TikTok
    "xhslink.com", "xiaohongshu.com",                       // 小红书
    "b23.tv", "bilibili.com", "acg.tv",                     // 哔哩哔哩
    "kuaishou.com", "gifshow.com",                          // 快手
    "youtube.com", "youtu.be",                              // YouTube
    "weibo.com", "weibo.cn", "ixigua.com", "v.qq.com",      // 微博 / 西瓜 / 腾讯视频
    "youku.com", "iqiyi.com", "channels.weixin.qq.com"      // 优酷 / 爱奇艺 / 视频号
  ];
  const VIDEO_LINK_HINT = "这是视频链接，请填到上方的视频链接输入框；此处需填写后端 API 地址";

  // 「?api=」里被判定为视频链接的地址：忽略后仍要给用户提示
  let rejectedApiQuery = null;

  function isVideoShareLink(value) {
    const raw = String(value == null ? "" : value).trim();
    if (!raw) return false;
    let host = "";
    try {
      const url = new URL(/^https?:\/\//i.test(raw) ? raw : "https://" + raw.replace(/^\/+/, ""));
      host = url.hostname.toLowerCase().replace(/^www\./, "");
    } catch (e) {
      return false;
    }
    return VIDEO_SHARE_DOMAINS.some((d) => host === d || host.endsWith("." + d));
  }

  // 引导用户回到正确的「视频链接」输入框：切回链接页签 + 聚焦 + 短暂高亮
  function focusVideoLinkInput() {
    const tabBtn = $('.seg-btn[data-tab="link"]');
    if (tabBtn && !tabBtn.classList.contains("is-active")) tabBtn.click();
    const urlInput = $("#urlInput");
    if (!urlInput) return;
    urlInput.focus();
    const wrap = urlInput.closest(".input-wrap") || urlInput;
    wrap.classList.add("is-flash");
    setTimeout(() => wrap.classList.remove("is-flash"), 1600);
  }

  // 后端地址框里填的是视频链接：不保存该值，清空输入框，提示并引导到视频链接框
  function rejectVideoLinkInApiInput() {
    const input = $("#apiBaseInput");
    if (input) input.value = "";
    renderApiNotice("error", VIDEO_LINK_HINT);
    toast(VIDEO_LINK_HINT, "err");
    focusVideoLinkInput();
  }

  /* 把"连不上后端"翻译成用户能看懂、能照做的提示（不静默失败） */
  function connectionHint(url) {
    if (!state.apiBase) {
      if (IS_STATIC_HOST) {
        return "当前页面运行在静态托管（GitHub Pages）上，没有可用的后端服务。" +
          "请在上方「后端服务」中填写你自建后端的公网地址后重试；页面本身只能展示界面，无法完成转写。";
      }
      return `无法连接后端服务（${url}）：请确认后端已启动（python run.py），且端口与当前页面一致。`;
    }
    return `无法连接后端服务（${state.apiBase}）：请确认地址可公网访问、后端已启动，` +
      "且后端允许跨域（CORS_ORIGINS 默认 *，若已收紧请把本站域名加入白名单；" +
      "另外 http 页面访问 https 后端会被浏览器拦截）。";
  }

  async function api(path, options) {
    const url = apiUrl(path);
    let resp;
    try {
      resp = await fetch(url, options);
    } catch (err) {
      throw new Error(connectionHint(url));
    }

    const text = await resp.text();
    let payload = null;
    if (text) {
      try { payload = JSON.parse(text); } catch (e) { payload = null; }
    }

    if (!resp.ok && resp.status !== 202) {
      const detail = payload && (payload.detail || payload.message);
      if (detail) throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      if (!payload) {
        throw new Error(
          `接口返回了非接口数据（HTTP ${resp.status}，${url}）。` +
          "通常说明「后端服务」地址填错了，或者指向的是一个纯静态站点。"
        );
      }
      throw new Error(`请求失败（HTTP ${resp.status}）`);
    }

    if (payload === null && text) {
      throw new Error(
        `接口返回的不是数据（${url}）。请检查「后端服务」地址是否指向正在运行的后端服务。`
      );
    }
    return { resp, payload };
  }

  /* ------------------------------------------------------------------ 主题 */
  function initTheme() {
    const saved = localStorage.getItem("voxscript-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    $("#themeBtn").addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("voxscript-theme", next);
    });
  }

  /* ------------------------------------------------------------ 服务状态 */
  function renderApiNotice(kind, message) {
    const box = $("#apiAlert");
    if (!box) return;
    if (!message) { box.hidden = true; box.textContent = ""; return; }
    box.hidden = false;
    box.className = kind === "error" ? "alert" : "alert soft";
    box.textContent = message;
  }

  function renderApiState(kind, text) {
    const badge = $("#apiState");
    if (!badge) return;
    badge.textContent = text;
    badge.className = "api-state" + (kind ? " is-" + kind : "");
  }

  function paintApiState() {
    if (state.apiBase) {
      renderApiState("", "自定义：" + baseHostLabel());
    } else if (IS_STATIC_HOST) {
      renderApiState("warn", "未配置（静态托管）");
    } else {
      renderApiState("", "同源");
    }
  }

  async function checkHealth() {
    const pill = $("#statusPill");
    const label = $("#statusText");
    pill.classList.remove("is-ok", "is-warn", "is-bad");

    // 纯静态托管 + 未配置后端：不发请求（必然失败），直接给出可读提示
    if (!state.apiBase && IS_STATIC_HOST) {
      pill.classList.add("is-warn");
      label.textContent = "未配置后端";
      pill.title = "本页运行在静态托管上，需先填写后端 API 地址";
      renderApiState("warn", "未配置（静态托管）");
      renderApiNotice(
        "warn",
        "当前页面部署在静态托管（GitHub Pages）上，只能展示界面，无法直接完成转写。" +
        "请在上方填入你自建后端的公网地址（例如 https://your-backend.example.com）并点击「保存并测试」。"
      );
      return false;
    }

    try {
      const { payload } = await api("/api/health");
      const warns = (payload.warnings || []).length;
      pill.classList.add(warns ? "is-warn" : "is-ok");
      label.textContent = warns ? `服务就绪 · ${warns} 项提示` : "服务就绪";
      if (warns) {
        pill.title = payload.warnings.join("\n");
        renderApiNotice("warn", "后端已连接，但有需要留意的提示：" + payload.warnings.join("；"));
      } else {
        renderApiNotice("", "");
      }
      if (!warns) {
        const bits = [payload.asr_backend];
        if (payload.gpu) bits.push(payload.gpu);
        if (payload.diarization && payload.diarization.available) bits.push("说话人分离可用");
        pill.title = bits.filter(Boolean).join(" · ");
      }
      renderApiState("ok", state.apiBase ? "已连接：" + baseHostLabel() : "同源已连接");
      return true;
    } catch (err) {
      pill.classList.add("is-bad");
      label.textContent = "服务未连接";
      pill.title = String(err.message);
      renderApiState("bad", "连接失败");
      renderApiNotice("error", String(err.message));
      return false;
    }
  }

  /* --------------------------------------------------- 后端地址设置面板 */
  function applyApiBase(next, options) {
    state.apiBase = normalizeBase(next);
    try { localStorage.setItem(API_BASE_KEY, state.apiBase); } catch (e) { /* 忽略存储失败 */ }
    const input = $("#apiBaseInput");
    if (input) input.value = state.apiBase;
    paintApiState();
    if (!state.apiBase && IS_STATIC_HOST) {
      // 清空配置后又回到"静态托管无后端"状态，立即给出提示
      checkHealth();
      return;
    }
    renderApiNotice("", "");
    checkHealth().then((ok) => {
      if (ok) {
        if (options && options.toast) toast(`已连接后端 ${baseHostLabel()}`, "ok");
        loadConfig();
        loadHistory();
      }
    });
  }

  function initApiPanel() {
    state.apiBase = resolveApiBase();
    const input = $("#apiBaseInput");
    input.value = state.apiBase;
    paintApiState();

    $("#apiSaveBtn").addEventListener("click", () => {
      const raw = input.value.trim();
      if (isVideoShareLink(raw)) {
        // 误把视频分享链接当后端地址：不保存、清空、提示并引导到「视频链接」输入框
        rejectVideoLinkInApiInput();
        return;
      }
      if (raw && !/^https?:\/\//i.test(raw) && !/^[\w.-]+(:\d+)?(\/|$)/.test(raw)) {
        toast("地址格式看起来不对，请填完整地址，例如 https://api.example.com", "err");
        return;
      }
      const next = normalizeBase(raw);
      if (raw && next !== raw) input.value = next;
      applyApiBase(next, { toast: true });
    });

    $("#apiResetBtn").addEventListener("click", () => {
      applyApiBase("", { toast: true });
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); $("#apiSaveBtn").click(); }
    });
  }

  /* 需要后端才能进行的操作，先确认后端可用，避免用户在静态站点上提交后毫无反应 */
  async function ensureBackend() {
    if (!state.apiBase && IS_STATIC_HOST) {
      renderApiNotice(
        "warn",
        "当前页面部署在静态托管（GitHub Pages）上，只能展示界面，无法直接完成转写。" +
        "请在上方「后端服务」中填入你自建后端的公网地址后重试。"
      );
      toast("未配置后端地址，无法提交任务", "err");
      $("#apiBaseInput").focus();
      return false;
    }
    return true;
  }

  async function loadConfig() {
    try {
      const { payload } = await api("/api/config");
      $("#maxSize").textContent = payload.max_upload_mb;
      updateAdvSummary(payload);
      const backend = $("#optBackend");
      const model = $("#optModel");
      if (payload.asr_backend) backend.dataset.default = payload.asr_backend;
      if (payload.whisper_model) model.dataset.default = payload.whisper_model;
      $$("option[value='']", backend).forEach((o) => {
        o.textContent = `跟随服务默认（${payload.asr_backend}）`;
      });
      $$("option[value='']", model).forEach((o) => {
        o.textContent = `跟随服务默认（${payload.whisper_model}）`;
      });
      if (!payload.diarization_available && payload.diarization_enabled) {
        state.diarHint = payload.diarization_reason;
      }
    } catch (err) {
      /* 配置读取失败不影响使用 */
    }
  }

  function updateAdvSummary(config) {
    const backend = $("#optBackend").value || (config && config.asr_backend) || "faster-whisper";
    const model = $("#optModel").value || (config && config.whisper_model) || "small";
    const lang = $("#optLanguage").value === "" ? "自动检测语言" : `语言 ${$("#optLanguage").value}`;
    const diar = $("#optDiar").value === "false" ? "说话人分离关闭" : "说话人分离开启";
    $("#advSummary").textContent = `${backend} · ${model} · ${lang} · ${diar}`;
  }

  /* -------------------------------------------------------------- Tab 切换 */
  function initTabs() {
    const thumb = $(".seg-thumb");
    const buttons = $$(".seg-btn");

    function place(btn) {
      thumb.style.width = btn.offsetWidth + "px";
      thumb.style.transform = `translateX(${btn.offsetLeft - 4}px)`;
    }

    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        buttons.forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        place(btn);
        $$(".tab-pane").forEach((pane) => {
          pane.classList.toggle("is-active", pane.dataset.pane === btn.dataset.tab);
        });
      });
    });
    window.addEventListener("resize", () => place($(".seg-btn.is-active")));
    place(buttons[0]);
  }

  /* -------------------------------------------------------------- 链接输入 */
  function initLinkPane() {
    const input = $("#urlInput");

    $("#pasteBtn").addEventListener("click", async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text) { input.value = text.trim(); input.focus(); }
        else toast("剪贴板为空");
      } catch (err) {
        toast("浏览器未授权读取剪贴板，请手动粘贴（Ctrl+V）", "err");
        input.focus();
      }
    });

    $("#clearBtn").addEventListener("click", () => { input.value = ""; input.focus(); });

    $$("#platformChips .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        if (!input.value.trim()) input.value = chip.dataset.hint;
        input.focus();
      });
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") startLinkTask();
    });

    $("#startLinkBtn").addEventListener("click", startLinkTask);
  }

  function extractUrls(text) {
    const matches = String(text || "").match(/https?:\/\/[^\s"'<>]+/g);
    if (matches && matches.length) {
      return matches.map((u) => u.replace(/[，。、；）】,"')\]]+$/, ""));
    }
    const plain = String(text || "").trim();
    return plain ? [plain] : [];
  }

  async function startLinkTask() {
    const raw = $("#urlInput").value;
    const urls = extractUrls(raw);
    if (!urls.length) { toast("请先粘贴视频链接", "err"); return; }
    if (urls.length > 1) { toast("一次只能处理一个链接，已使用第一个", "err"); }
    if (!(await ensureBackend())) return;

    const btn = $("#startLinkBtn");
    setBusy(btn, true);
    try {
      const { payload } = await api("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urls[0], options: collectOptions() }),
      });
      beginTask(payload.task_id);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusy(btn, false);
    }
  }

  /* ------------------------------------------------------------ 文件上传 */
  function initFilePane() {
    const dz = $("#dropzone");
    const input = $("#fileInput");
    let picked = null;

    function showFile(file) {
      picked = file;
      $("#fileName").textContent = file.name;
      $("#fileInfo").textContent = `${humanSize(file.size)} · ${(file.name.split(".").pop() || "").toUpperCase()}`;
      $("#fileIcon").textContent = /\.(mp4|mov|mkv|avi|flv|webm|m4v|ts)$/i.test(file.name) ? "🎬" : "🎵";
      $("#dzFile").hidden = false;
      $("#startFileBtn").disabled = false;
    }

    function clearFile() {
      picked = null;
      input.value = "";
      $("#dzFile").hidden = true;
      $("#startFileBtn").disabled = true;
    }

    dz.addEventListener("click", (e) => {
      if (e.target.closest("#fileRemove")) return;
      input.click();
    });
    dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });

    ["dragenter", "dragover"].forEach((evt) =>
      dz.addEventListener(evt, (e) => { e.preventDefault(); dz.classList.add("is-drag"); })
    );
    ["dragleave", "drop"].forEach((evt) =>
      dz.addEventListener(evt, (e) => { e.preventDefault(); dz.classList.remove("is-drag"); })
    );
    dz.addEventListener("drop", (e) => {
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) showFile(file);
    });

    input.addEventListener("change", () => { if (input.files[0]) showFile(input.files[0]); });
    $("#fileRemove").addEventListener("click", (e) => { e.stopPropagation(); clearFile(); });
    $("#startFileBtn").addEventListener("click", () => startFileTask(picked));
  }

  async function startFileTask(file) {
    if (!file) { toast("请先选择视频或音频文件", "err"); return; }
    if (!(await ensureBackend())) return;
    const btn = $("#startFileBtn");
    setBusy(btn, true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("options", JSON.stringify(collectOptions()));
      const { payload } = await api("/api/tasks/upload", { method: "POST", body: form });
      beginTask(payload.task_id);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusy(btn, false);
    }
  }

  function setBusy(btn, busy) {
    if (!btn) return;
    btn.disabled = busy;
    const label = $(".btn-label", btn);
    if (label) label.textContent = busy ? "提交中…" : "开始转写";
  }

  /* ------------------------------------------------------------ 选项收集 */
  function collectOptions() {
    const opts = {};
    const backend = $("#optBackend").value;
    const model = $("#optModel").value;
    const language = $("#optLanguage").value;
    const device = $("#optDevice").value;
    const diar = $("#optDiar").value;
    const speakers = $("#optSpeakers").value;
    const prompt = $("#optPrompt").value.trim();

    if (backend) opts.asr_backend = backend;
    if (model) opts.model = model;
    if (language) opts.language = language;
    if (device) opts.device = device;
    if (diar) opts.diarization = diar === "true";
    if (speakers && speakers !== "0") opts.num_speakers = Number(speakers);
    if (prompt) opts.initial_prompt = prompt;
    return opts;
  }

  /* ------------------------------------------------------------ 任务与轮询 */
  function beginTask(taskId) {
    state.taskId = taskId;
    $("#progressPanel").hidden = false;
    $("#resultWrap").hidden = true;
    resetProgress();
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(() => pollTask(taskId), 1200);
    pollTask(taskId);
    $("#progressPanel").scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function resetProgress() {
    $("#progPct").textContent = "0%";
    $("#progBar").style.width = "0%";
    $("#progStage").textContent = "准备中";
    $("#progMsg").textContent = "任务已创建，等待执行";
    $("#progError").hidden = true;
    $$("#steps li").forEach((li) => li.classList.remove("is-active", "is-done"));
  }

  const STAGE_ORDER = ["downloading", "extracting", "transcribing", "diarizing", "aligning", "exporting", "done"];

  async function pollTask(taskId) {
    try {
      const { payload } = await api(`/api/tasks/${taskId}`);
      renderProgress(payload);
      if (payload.status === "done") {
        stopPolling();
        await loadResult(taskId);
        loadHistory();
      } else if (payload.status === "failed") {
        stopPolling();
        toast("处理失败：" + (payload.error || "未知错误"), "err");
      }
    } catch (err) {
      stopPolling();
      toast(err.message, "err");
    }
  }

  function stopPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  function renderProgress(task) {
    const pct = Math.max(0, Math.min(100, Number(task.progress) || 0));
    $("#progBar").style.width = pct + "%";
    $("#progPct").textContent = pct.toFixed(0) + "%";
    $("#progStage").textContent = task.stage_label || task.stage || "处理中";
    $("#progMsg").textContent = task.message || "";

    const currentIdx = STAGE_ORDER.indexOf(task.stage);
    $$("#steps li").forEach((li) => {
      const idx = STAGE_ORDER.indexOf(li.dataset.stage);
      li.classList.toggle("is-done", task.status === "done" || (currentIdx > -1 && idx < currentIdx));
      li.classList.toggle("is-active", task.status !== "done" && idx === currentIdx);
    });

    const errBox = $("#progError");
    if (task.status === "failed" && task.error) {
      errBox.hidden = false;
      errBox.textContent = "失败原因：" + task.error;
      $("#progStage").textContent = "任务失败";
    } else if (task.notes && task.notes.length) {
      errBox.hidden = false;
      errBox.className = "alert soft";
      errBox.textContent = task.notes.join(" ");
    } else {
      errBox.hidden = true;
    }
  }

  /* ------------------------------------------------------------ 结果渲染 */
  async function loadResult(taskId) {
    const { payload } = await api(`/api/tasks/${taskId}/result`);
    if (!payload || !payload.segments) {
      toast("结果尚未生成，请稍后重试", "err");
      return;
    }
    state.result = payload;
    state.speaker = "all";
    state.query = "";
    state.activeIndex = -1;
    state.duration = (payload.stats && payload.stats.duration) || 0;

    state.speakerColors = {};
    (payload.speakers || []).forEach((sp, i) => {
      state.speakerColors[sp.label || sp.id] = sp.color || FALLBACK_PALETTE[i % FALLBACK_PALETTE.length];
    });

    renderMeta(payload);
    renderSpeakerFilter(payload);
    renderTranscript(payload);
    setupAudio(payload);

    $("#resultWrap").hidden = false;
    $("#resultWrap").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderMeta(payload) {
    const meta = payload.meta || {};
    const stats = payload.stats || {};
    const title = meta.title || (payload.source && payload.source.title) || "转写结果";
    $("#resTitle").textContent = title;

    const bits = [];
    const platform = (payload.source && payload.source.platform) || meta.platform;
    if (platform) bits.push(platform);
    if (payload.source && payload.source.uploader) bits.push("作者：" + payload.source.uploader);
    if (meta.asr_model) bits.push(`${meta.asr_backend || "ASR"} · ${meta.asr_model}`);
    if (payload.source && payload.source.url) bits.push(payload.source.url);
    if (meta.built_at) bits.push("生成于 " + meta.built_at);
    $("#resSub").textContent = bits.join("  |  ");

    $("#statDuration").textContent = stats.duration_text || shortClock(stats.duration);
    $("#statSpeakers").textContent = (stats.speaker_count || 1) + " 位";
    $("#statSegments").textContent = (stats.segment_count || 0) + " 段";
    $("#statChars").textContent = (stats.char_count || 0) + " 字";
    $("#statLang").textContent = stats.language || "—";

    const notes = payload.notes || [];
    const noteBox = $("#resNotes");
    if (notes.length) {
      noteBox.hidden = false;
      noteBox.textContent = notes.join(" ");
    } else {
      noteBox.hidden = true;
    }
  }

  function renderSpeakerFilter(payload) {
    const box = $("#speakerFilter");
    box.innerHTML = "";
    const speakers = payload.speakers || [];

    const all = document.createElement("button");
    all.className = "sp-chip is-active";
    all.dataset.speaker = "all";
    all.textContent = "全部";
    box.appendChild(all);

    speakers.forEach((sp, i) => {
      const label = sp.label || sp.id;
      const color = state.speakerColors[label] || FALLBACK_PALETTE[i % FALLBACK_PALETTE.length];
      const btn = document.createElement("button");
      btn.className = "sp-chip";
      btn.dataset.speaker = label;
      btn.style.setProperty("--spk", color);
      btn.innerHTML = `<span class="sp-dot"></span>说话人 ${escapeHtml(label)}` +
        `<span style="opacity:.7;font-weight:400">${sp.segment_count || 0} 段</span>`;
      box.appendChild(btn);
    });

    box.onclick = (e) => {
      const btn = e.target.closest(".sp-chip");
      if (!btn) return;
      $$(".sp-chip", box).forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.speaker = btn.dataset.speaker;
      applyFilter();
    };
  }

  function renderSpeakerLegend(payload) {
    const box = $("#speakerLegend");
    box.innerHTML = "";
    (payload.speakers || []).forEach((sp, i) => {
      const label = sp.label || sp.id;
      const color = state.speakerColors[label] || FALLBACK_PALETTE[i % FALLBACK_PALETTE.length];
      const item = document.createElement("div");
      item.className = "lg-item";
      item.innerHTML = `<span class="lg-bar" style="--spk:${color}"></span>` +
        `<b style="color:${color}">说话人 ${escapeHtml(label)}</b>` +
        `<em>${sp.segment_count || 0} 段 · ${shortClock(sp.seconds)} · ${sp.percent || 0}%</em>`;
      box.appendChild(item);
    });
    box.hidden = (payload.speakers || []).length === 0;
  }

  function renderTranscript(payload) {
    const box = $("#transcript");
    box.innerHTML = "";
    const speakers = payload.speakers || [];
    const multi = speakers.length > 1;

    (payload.segments || []).forEach((seg, i) => {
      const speaker = seg.speaker || "A";
      const color = state.speakerColors[speaker] || FALLBACK_PALETTE[0];
      const row = document.createElement("div");
      row.className = "tx-seg";
      row.dataset.speaker = speaker;
      row.dataset.index = String(i);
      row.dataset.text = (seg.text || "").toLowerCase();
      row.style.setProperty("--spk", color);
      row.innerHTML =
        `<div class="tx-time">${clock(seg.start, true)}<em>→ ${clock(seg.end, true)}</em></div>` +
        `<div class="tx-body">` +
          `<div class="tx-meta">` +
            (multi ? `<span class="tx-speaker">${escapeHtml(speaker)}</span>` : "") +
            `<span class="tx-idx">#${String(seg.index != null ? seg.index + 1 : i + 1).padStart(3, "0")}</span>` +
          `</div>` +
          `<p class="tx-text">${escapeHtml(seg.text)}</p>` +
        `</div>`;
      row.addEventListener("click", () => seekTo(seg.start));
      box.appendChild(row);
    });

    renderSpeakerLegend(payload);
    applyFilter();
    box.scrollTop = 0;
  }

  function applyFilter() {
    const rows = $$("#transcript .tx-seg");
    const query = state.query.trim().toLowerCase();
    let visible = 0;

    rows.forEach((row) => {
      const speakerOk = state.speaker === "all" || row.dataset.speaker === state.speaker;
      const textOk = !query || row.dataset.text.indexOf(query) > -1;
      const show = speakerOk && textOk;
      row.classList.toggle("is-hidden", !show);
      if (show) visible++;

      const target = $(".tx-text", row);
      const raw = target.dataset.raw || target.textContent;
      target.dataset.raw = raw;
      if (query) {
        const idx = raw.toLowerCase().indexOf(query);
        if (idx > -1) {
          target.innerHTML = escapeHtml(raw.slice(0, idx)) +
            "<mark>" + escapeHtml(raw.slice(idx, idx + query.length)) + "</mark>" +
            escapeHtml(raw.slice(idx + query.length));
        } else {
          target.textContent = raw;
        }
      } else {
        target.textContent = raw;
      }
    });

    $("#transcriptEmpty").hidden = visible > 0;
  }

  /* ------------------------------------------------------------ 播放器联动 */
  function setupAudio(payload) {
    const bar = $("#audioBar");
    const audio = $("#audioPlayer");
    if (payload.media_url) {
      // 后端返回的媒体地址可能是相对路径，需补上配置的后端地址
      const src = /^https?:\/\//i.test(payload.media_url) ? payload.media_url : apiUrl(payload.media_url);
      bar.hidden = false;
      if (audio.dataset.src !== src) {
        audio.src = src;
        audio.dataset.src = src;
      }
      audio.ontimeupdate = () => syncActive(audio.currentTime);
    } else {
      bar.hidden = true;
      audio.removeAttribute("src");
      delete audio.dataset.src;
    }
  }

  function seekTo(seconds) {
    const audio = $("#audioPlayer");
    if (!audio.src) {
      toast("本次任务没有可播放的音频");
      return;
    }
    audio.currentTime = Math.max(0, Number(seconds) || 0);
    audio.play().catch(() => {});
  }

  function syncActive(time) {
    const payload = state.result;
    if (!payload) return;
    const segs = payload.segments || [];
    let idx = -1;
    for (let i = 0; i < segs.length; i++) {
      if (time >= segs[i].start && time < segs[i].end) { idx = i; break; }
    }
    if (idx === state.activeIndex) return;
    state.activeIndex = idx;

    $$("#transcript .tx-seg").forEach((row) => {
      const on = Number(row.dataset.index) === idx;
      row.classList.toggle("is-active", on);
      if (on && !row.classList.contains("is-hidden")) {
        row.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  }

  /* ---------------------------------------------------------------- 导出 */
  async function exportAs(fmt) {
    if (!state.taskId || !state.result) { toast("还没有可导出的结果", "err"); return; }
    if (!(await ensureBackend())) return;
    const exportUrl = apiUrl(`/api/tasks/${state.taskId}/export?format=${fmt}`);
    try {
      let resp;
      try {
        resp = await fetch(exportUrl);
      } catch (netErr) {
        throw new Error(connectionHint(exportUrl));
      }
      if (!resp.ok) {
        let detail = "";
        try { detail = (await resp.json()).detail || ""; } catch (e) { /* ignore */ }
        throw new Error(detail || `导出失败（HTTP ${resp.status}）`);
      }
      const blob = await resp.blob();
      const header = resp.headers.get("X-Filename");
      const fallback = ($("#resTitle").textContent || "transcript").replace(/[\\/:*?"<>|]/g, "_").slice(0, 60);
      const filename = header ? decodeURIComponent(header) : `${fallback}.${fmt}`;

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      toast(`已导出 ${filename}`, "ok");
    } catch (err) {
      toast(err.message, "err");
    }
  }

  async function copyAll() {
    if (!state.result) return;
    const rows = $$("#transcript .tx-seg:not(.is-hidden)");
    const multi = (state.result.speakers || []).length > 1;
    const lines = rows.map((row) => {
      const text = $(".tx-text", row).dataset.raw || $(".tx-text", row).textContent;
      const speaker = row.dataset.speaker;
      const time = $(".tx-time", row).textContent.replace(/→.*/, "").trim();
      return `[${time}]${multi ? " " + speaker + ":" : ""} ${text}`;
    });
    const body = `${$("#resTitle").textContent}\n\n${lines.join("\n")}`;
    try {
      await navigator.clipboard.writeText(body);
      toast("已复制当前筛选下的文稿", "ok");
    } catch (err) {
      toast("复制失败，请手动选择文本", "err");
    }
  }

  /* ---------------------------------------------------------------- 历史 */
  async function loadHistory() {
    const box = $("#historyList");
    if (!state.apiBase && IS_STATIC_HOST) {
      box.innerHTML = '<div class="history-empty">未配置后端地址，暂无历史任务</div>';
      return;
    }
    try {
      const { payload } = await api("/api/tasks?limit=12");
      const tasks = payload.tasks || [];
      if (!tasks.length) {
        box.innerHTML = '<div class="history-empty">暂无历史任务</div>';
        return;
      }
      box.innerHTML = "";
      tasks.forEach((task) => {
        const item = document.createElement("div");
        item.className = "history-item";
        const title = (task.source && (task.source.title || task.source.filename)) ||
          (task.source && task.source.url) || task.task_id;
        const stateClass = task.status === "done" ? "done" : task.status === "failed" ? "failed" : "running";
        const badge = task.status === "done" ? "已完成" : task.status === "failed" ? "失败" : (task.stage_label || "进行中");
        item.innerHTML =
          `<span class="hi-main">` +
            `<span class="hi-title">${escapeHtml(title)}</span>` +
            `<span class="hi-sub">${escapeHtml(task.created_at_iso || "")} · ${escapeHtml(task.source_type === "url" ? (task.source.platform || "链接") : "本地文件")}</span>` +
          `</span>` +
          `<span class="hi-state ${stateClass}">${escapeHtml(badge)}</span>` +
          `<button class="mini-btn hi-open">查看</button>`;
        $(".hi-open", item).addEventListener("click", () => {
          if (task.status === "done") {
            state.taskId = task.task_id;
            $("#progressPanel").hidden = true;
            loadResult(task.task_id);
          } else if (task.status === "failed") {
            toast("该任务已失败：" + (task.error || "未知原因"), "err");
          } else {
            beginTask(task.task_id);
          }
        });
        box.appendChild(item);
      });
    } catch (err) {
      box.innerHTML = '<div class="history-empty">历史记录读取失败：' +
        escapeHtml(String(err.message)) + "</div>";
    }
  }

  /* ---------------------------------------------------------------- 初始化 */
  function init() {
    initApiPanel();
    initTheme();
    initTabs();
    initLinkPane();
    initFilePane();

    $("#viewToggle").addEventListener("click", (e) => {
      const btn = e.target.closest(".vt-btn");
      if (!btn) return;
      $$(".vt-btn").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.view = btn.dataset.view;
      $("#transcript").classList.toggle("view-plain", state.view === "plain");
    });

    let searchTimer = null;
    $("#searchInput").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      const value = e.target.value;
      searchTimer = setTimeout(() => { state.query = value; applyFilter(); }, 180);
    });

    $("#copyBtn").addEventListener("click", copyAll);
    $("#exportTxtBtn").addEventListener("click", () => exportAs("txt"));
    $("#exportSrtBtn").addEventListener("click", () => exportAs("srt"));
    $("#exportVttBtn").addEventListener("click", () => exportAs("vtt"));
    $("#exportMdBtn").addEventListener("click", () => exportAs("md"));
    $("#exportJsonBtn").addEventListener("click", () => exportAs("json"));
    $("#refreshHistory").addEventListener("click", loadHistory);

    $("#cancelVisualBtn").addEventListener("click", () => {
      $("#progressPanel").hidden = true;
      toast("已收起进度面板，任务仍在后台继续");
    });

    ["optBackend", "optModel", "optLanguage", "optDiar"].forEach((id) => {
      $("#" + id).addEventListener("change", () => updateAdvSummary(null));
    });

    checkHealth().then(() => {
      // 「?api=」被判为视频链接而忽略时，在连通性检查之后落提示，避免被健康检查结果覆盖
      if (rejectedApiQuery) renderApiNotice("error", VIDEO_LINK_HINT);
    });
    loadConfig();
    loadHistory();
    setInterval(checkHealth, 60000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
