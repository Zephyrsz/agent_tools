const state = {
  video: null,
  settings: null,
  tasks: [],
  toastTimer: null,
};

const els = {};

document.addEventListener("DOMContentLoaded", () => {
  Object.assign(els, {
    parseForm: document.querySelector("#parse-form"),
    parseButton: document.querySelector("#parse-button"),
    videoUrl: document.querySelector("#video-url"),
    urlError: document.querySelector("#url-error"),
    parseError: document.querySelector("#parse-error"),
    configureCookies: document.querySelector("#configure-cookies"),
    parseEmpty: document.querySelector("#parse-empty"),
    parseLoading: document.querySelector("#parse-loading"),
    videoResult: document.querySelector("#video-result"),
    thumbnail: document.querySelector("#video-thumbnail"),
    duration: document.querySelector("#video-duration"),
    channel: document.querySelector("#video-channel"),
    title: document.querySelector("#video-title"),
    formatCount: document.querySelector("#format-count"),
    formatList: document.querySelector("#format-list"),
    selectedNote: document.querySelector("#selected-format-note"),
    queueButton: document.querySelector("#queue-button"),
    queueCount: document.querySelector("#queue-count"),
    queueEmpty: document.querySelector("#queue-empty"),
    taskList: document.querySelector("#task-list"),
    settingsForm: document.querySelector("#settings-form"),
    connections: document.querySelector("#connections"),
    sleepMin: document.querySelector("#sleep-min"),
    sleepMax: document.querySelector("#sleep-max"),
    downloadDir: document.querySelector("#download-dir"),
    cookiesPath: document.querySelector("#cookies-path"),
    cookieSource: document.querySelector("#cookie-source"),
    cookieSourceGroup: document.querySelector("#cookie-source-group"),
    cookieUploadGroup: document.querySelector("#cookie-upload-group"),
    cookiePathGroup: document.querySelector("#cookie-path-group"),
    cookieFile: document.querySelector("#cookie-file"),
    cookieFileStatus: document.querySelector("#cookie-file-status"),
    uploadCookie: document.querySelector("#upload-cookie"),
    clearCookie: document.querySelector("#clear-cookie"),
    proxyUrl: document.querySelector("#proxy-url"),
    clearProxy: document.querySelector("#clear-proxy"),
    clearProxyWrap: document.querySelector("#clear-proxy-wrap"),
    cookieState: document.querySelector("#cookie-state"),
    proxyState: document.querySelector("#proxy-state"),
    connectionSummary: document.querySelector("#connection-summary"),
    sleepSummary: document.querySelector("#sleep-summary"),
    dependencyList: document.querySelector("#dependency-list"),
    refreshHealth: document.querySelector("#refresh-health"),
    toast: document.querySelector("#toast"),
  });

  els.parseForm.addEventListener("submit", parseVideo);
  els.queueButton.addEventListener("click", addToQueue);
  els.settingsForm.addEventListener("submit", saveSettings);
  els.cookieSource.addEventListener("change", updateCookieSource);
  els.cookieFile.addEventListener("change", updateCookieFileStatus);
  els.uploadCookie.addEventListener("click", uploadCookieFile);
  els.clearCookie.addEventListener("click", clearCookieConfig);
  els.configureCookies.addEventListener("click", focusCookieSettings);
  els.refreshHealth.addEventListener("click", loadHealth);
  els.formatList.addEventListener("change", updateSelectedFormat);
  els.taskList.addEventListener("click", handleTaskAction);
  document.querySelectorAll("[data-step]").forEach((button) => {
    button.addEventListener("click", () => stepConnections(Number(button.dataset.step)));
  });
  [els.sleepMin, els.sleepMax].forEach((input) => input.addEventListener("input", updateRiskSummary));

  refreshIcons();
  Promise.all([loadSettings(), loadHealth(), loadTasks()]);
  window.setInterval(loadTasks, 2000);
});

function refreshIcons() {
  if (window.lucide) {
    window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
  }
}

async function api(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    headers: { ...(isFormData ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) },
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch (_) {
      // Preserve the HTTP fallback when the response is not JSON.
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function parseVideo(event) {
  event.preventDefault();
  const url = els.videoUrl.value.trim();
  setParseError("");
  if (!url) {
    setParseError("请输入 YouTube 视频链接");
    els.videoUrl.focus();
    return;
  }

  setParseLoading(true);
  try {
    state.video = await api("/api/parse", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    renderVideo(state.video);
  } catch (error) {
    state.video = null;
    setParseError(error.message, /Cookie|身份|登录/.test(error.message));
    els.parseEmpty.hidden = false;
    showToast(error.message, true);
  } finally {
    setParseLoading(false);
  }
}

function setParseError(message, showCookieAction = false) {
  els.urlError.textContent = message;
  els.parseError.hidden = !message;
  els.configureCookies.hidden = !showCookieAction;
  if (message) refreshIcons();
}

function focusCookieSettings() {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  els.cookieSourceGroup.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
  els.cookieSource.focus({ preventScroll: true });
}

function setParseLoading(active) {
  els.parseButton.disabled = active;
  els.parseButton.querySelector("span").textContent = active ? "正在解析" : "解析视频";
  els.parseLoading.hidden = !active;
  els.parseEmpty.hidden = active || Boolean(state.video);
  els.videoResult.hidden = active || !state.video;
}

function renderVideo(video) {
  els.thumbnail.src = video.thumbnail;
  els.thumbnail.alt = `${video.title} 的视频缩略图`;
  els.duration.textContent = formatDuration(video.duration);
  els.duration.hidden = !video.duration;
  els.channel.textContent = video.channel;
  els.title.textContent = video.title;
  els.formatCount.textContent = `${video.formats.length} 种格式`;
  els.formatList.innerHTML = video.formats.map((format, index) => `
    <label class="format-option">
      <input type="radio" name="format" value="${escapeHtml(format.id)}" ${index === 0 ? "checked" : ""}>
      <span class="format-option__quality">${escapeHtml(format.label)}</span>
      <span class="format-option__meta">${escapeHtml(format.container)}${format.fps ? ` · ${format.fps} fps` : ""}</span>
      <span class="format-option__size">${formatBytes(format.size)}</span>
      ${format.needs_merge ? '<span class="merge-chip">需合流</span>' : '<span></span>'}
    </label>
  `).join("");
  els.videoResult.hidden = false;
  els.parseEmpty.hidden = true;
  updateSelectedFormat();
}

function updateSelectedFormat() {
  const format = selectedFormat();
  if (!format) return;
  els.selectedNote.textContent = format.needs_merge
    ? `${format.label} 将在下载后由 ffmpeg 本地合流`
    : `${format.label} 可直接保存到本地目录`;
}

function selectedFormat() {
  const selected = els.formatList.querySelector('input[name="format"]:checked');
  return state.video?.formats.find((item) => item.id === selected?.value) || null;
}

async function addToQueue() {
  const format = selectedFormat();
  if (!state.video || !format) return;
  els.queueButton.disabled = true;
  try {
    await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        url: state.video.url,
        title: state.video.title,
        format_id: format.id,
        format_label: `${format.label} ${format.container}`,
      }),
    });
    showToast("已加入下载队列");
    await loadTasks();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    els.queueButton.disabled = false;
  }
}

async function loadTasks() {
  try {
    state.tasks = await api("/api/tasks");
    renderTasks();
  } catch (_) {
    // Polling recovers automatically when the local server is available again.
  }
}

function renderTasks() {
  els.queueCount.textContent = `${state.tasks.length} 个任务`;
  els.queueEmpty.hidden = state.tasks.length > 0;
  els.taskList.innerHTML = state.tasks.map((task) => {
    const active = ["queued", "downloading", "merging"].includes(task.status);
    const detail = task.error || [task.detail, task.speed, task.eta ? `剩余 ${task.eta}` : ""].filter(Boolean).join(" · ");
    return `
      <article class="task-item" data-task-id="${task.id}">
        <div class="task-item__top">
          <p class="task-item__title" title="${escapeHtml(task.title)}">${escapeHtml(task.title)} · ${escapeHtml(task.format_label)}</p>
          <span class="task-status task-status--${task.status}">${statusLabel(task.status)}</span>
        </div>
        <div class="task-progress" role="progressbar" aria-label="下载进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(task.progress)}">
          <span style="width:${Math.max(active && task.status === "queued" ? 2 : 0, task.progress)}%"></span>
        </div>
        <div class="task-item__bottom">
          <p class="task-item__detail">${escapeHtml(detail || "等待状态更新")}</p>
          <div class="task-actions">
            ${task.ready ? `<a class="button button--primary" href="/api/files/${task.id}"><i data-lucide="file-down"></i>领取文件</a>` : ""}
            ${active ? `<button class="button button--danger-ghost" type="button" data-action="cancel"><i data-lucide="square"></i>取消</button>` : ""}
            ${!active ? `<button class="icon-button" type="button" data-action="delete" aria-label="删除任务" title="删除任务"><i data-lucide="trash-2"></i></button>` : ""}
          </div>
        </div>
      </article>
    `;
  }).join("");
  refreshIcons();
}

async function handleTaskAction(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const task = button.closest("[data-task-id]");
  const id = task?.dataset.taskId;
  if (!id) return;
  button.disabled = true;
  try {
    if (button.dataset.action === "cancel") {
      await api(`/api/tasks/${id}/cancel`, { method: "POST" });
      showToast("任务已取消");
    } else {
      await api(`/api/tasks/${id}`, { method: "DELETE" });
      showToast("任务与本地文件已清理");
    }
    await loadTasks();
  } catch (error) {
    button.disabled = false;
    showToast(error.message, true);
  }
}

async function loadSettings() {
  try {
    state.settings = await api("/api/settings");
    els.connections.value = state.settings.connections;
    els.sleepMin.value = state.settings.sleep_min;
    els.sleepMax.value = state.settings.sleep_max;
    els.downloadDir.value = state.settings.download_dir;
    els.cookiesPath.value = state.settings.cookies_path || "";
    els.cookieSource.value = state.settings.cookies_browser
      || (state.settings.cookies_managed ? "upload" : state.settings.cookies_path ? "path" : "");
    updateCookieSource();
    els.cookieState.textContent = state.settings.cookies_configured ? "已就绪" : "未配置";
    els.cookieState.classList.toggle("mini-state--ok", state.settings.cookies_configured);
    els.clearCookie.hidden = !state.settings.cookies_configured;
    els.proxyState.textContent = state.settings.proxy_configured ? "已保存" : "未配置";
    els.proxyState.classList.toggle("mini-state--ok", state.settings.proxy_configured);
    els.clearProxyWrap.hidden = !state.settings.proxy_configured;
    updateRiskSummary();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const button = document.querySelector("#save-settings");
  const min = Number(els.sleepMin.value);
  const max = Number(els.sleepMax.value);
  if (max < min) {
    showToast("最长等待不能小于最短等待", true);
    els.sleepMax.focus();
    return;
  }
  let proxy = els.proxyUrl.value.trim();
  if (state.settings?.proxy_configured && !proxy && !els.clearProxy.checked) proxy = null;
  if (els.clearProxy.checked) proxy = "";

  button.disabled = true;
  try {
    state.settings = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        download_dir: els.downloadDir.value.trim(),
        connections: Number(els.connections.value),
        sleep_min: min,
        sleep_max: max,
        cookies_path: els.cookieSource.value === "path"
          ? els.cookiesPath.value.trim()
          : els.cookieSource.value === "upload" && state.settings?.cookies_managed
            ? state.settings.cookies_path
            : "",
        cookies_browser: ["", "upload", "path"].includes(els.cookieSource.value) ? "" : els.cookieSource.value,
        proxy_url: proxy,
      }),
    });
    els.proxyUrl.value = "";
    els.clearProxy.checked = false;
    await loadSettings();
    showToast("配置已保存");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function updateCookieSource() {
  const source = els.cookieSource.value;
  els.cookieUploadGroup.hidden = source !== "upload";
  els.cookiePathGroup.hidden = source !== "path";
  const browserOption = els.cookieSource.selectedOptions[0]?.textContent;
  const uploadReady = source === "upload" && state.settings?.cookies_managed;
  const pathReady = source === "path" && Boolean(els.cookiesPath.value.trim());
  const browserReady = !["", "upload", "path"].includes(source);
  els.cookieState.textContent = uploadReady
    ? "已加载"
    : source === "upload"
      ? "等待文件"
      : source === "path"
        ? (pathReady ? "本地路径" : "未配置")
        : source
          ? browserOption
          : "未配置";
  els.cookieState.classList.toggle("mini-state--ok", uploadReady || pathReady || browserReady);
}

function updateCookieFileStatus() {
  const file = els.cookieFile.files[0];
  els.cookieFileStatus.textContent = file ? `${file.name} · ${formatBytes(file.size)}` : "最大 2 MB";
}

async function uploadCookieFile() {
  const file = els.cookieFile.files[0];
  if (!file) {
    showToast("请先选择 Cookie 文件", true);
    els.cookieFile.focus();
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    showToast("Cookie 文件不能超过 2 MB", true);
    return;
  }
  const form = new FormData();
  form.append("file", file, file.name);
  els.uploadCookie.disabled = true;
  try {
    state.settings = await api("/api/cookies/upload", { method: "POST", body: form });
    els.cookieFile.value = "";
    await loadSettings();
    els.cookieFileStatus.textContent = `${state.settings.cookies_file_name} · 已安全加载`;
    showToast("Cookie 文件已加载");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    els.uploadCookie.disabled = false;
  }
}

async function clearCookieConfig() {
  els.clearCookie.disabled = true;
  try {
    await api("/api/cookies", { method: "DELETE" });
    await loadSettings();
    els.cookieFile.value = "";
    els.cookieFileStatus.textContent = "最大 2 MB";
    showToast("Cookie 配置已清除");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    els.clearCookie.disabled = false;
  }
}

function stepConnections(delta) {
  els.connections.value = Math.min(4, Math.max(1, Number(els.connections.value) + delta));
  updateRiskSummary();
}

function updateRiskSummary() {
  els.connectionSummary.textContent = els.connections.value;
  els.sleepSummary.textContent = `${els.sleepMin.value}–${els.sleepMax.value} 秒`;
}

async function loadHealth() {
  els.refreshHealth.disabled = true;
  try {
    const health = await api("/api/health");
    els.dependencyList.innerHTML = Object.values(health.dependencies).map((item) => `
      <li>
        <span class="dependency-state"><span class="dependency-dot dependency-dot--${item.ok ? "ok" : "error"}"></span>${escapeHtml(item.label)}</span>
        <span class="dependency-version">${item.ok ? "可用" : "缺失"}</span>
      </li>
    `).join("");
  } catch (error) {
    els.dependencyList.innerHTML = `<li><span class="dependency-state"><span class="dependency-dot dependency-dot--error"></span>服务异常</span></li>`;
    showToast(error.message, true);
  } finally {
    els.refreshHealth.disabled = false;
  }
}

function showToast(message, isError = false) {
  window.clearTimeout(state.toastTimer);
  els.toast.textContent = message;
  els.toast.classList.toggle("toast--error", isError);
  els.toast.hidden = false;
  state.toastTimer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, isError ? 6000 : 3200);
}

function statusLabel(status) {
  return {
    queued: "等待",
    downloading: "下载中",
    merging: "合流中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  }[status] || status;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}

function formatBytes(bytes) {
  if (!bytes) return "大小未知";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
