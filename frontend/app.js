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

  async function api(path, options) {
    const resp = await fetch(path, options);
    let payload = null;
    const text = await resp.text();
    if (text) {
      try { payload = JSON.parse(text); } catch (e) { payload = { detail: text }; }
    }
    if (!resp.ok && resp.status !== 202) {
      const detail = payload && (payload.detail || payload.message);
      throw new Error(detail || `请求失败（HTTP ${resp.status}）`);
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
  async function checkHealth() {
    const pill = $("#statusPill");
    const label = $("#statusText");
    try {
      const { payload } = await api("/api/health");
      const warns = (payload.warnings || []).length;
      pill.classList.add(warns ? "is-warn" : "is-ok");
      label.textContent = warns ? `服务就绪 · ${warns} 项提示` : "服务就绪";
      if (warns) {
        pill.title = payload.warnings.join("\n");
        toast(payload.warnings[0], "err");
      } else {
        const bits = [payload.asr_backend];
        if (payload.gpu) bits.push(payload.gpu);
        if (payload.diarization && payload.diarization.available) bits.push("说话人分离可用");
        pill.title = bits.join(" · ");
      }
    } catch (err) {
      pill.classList.add("is-bad");
      label.textContent = "服务未连接";
      pill.title = String(err.message);
    }
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
      bar.hidden = false;
      if (audio.dataset.src !== payload.media_url) {
        audio.src = payload.media_url;
        audio.dataset.src = payload.media_url;
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
    try {
      const resp = await fetch(`/api/tasks/${state.taskId}/export?format=${fmt}`);
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
      box.innerHTML = '<div class="history-empty">历史记录读取失败</div>';
    }
  }

  /* ---------------------------------------------------------------- 初始化 */
  function init() {
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

    checkHealth();
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
