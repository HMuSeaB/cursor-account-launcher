const $ = (id) => document.getElementById(id);
const api = () => window.pywebview?.api;

let accounts = [];
let activeAccountId = null;
let detailAccountId = null;
let modelUsageCache = {};
let sessions = [];
let autoKeepIds = new Set();
let keepReasons = {};
let localIdentity = { email: "", userId: "" };
let lastCursorStatus = null;
let guardConfig = {
  enabled: false,
  mode: "whitelist",
  intervalSeconds: 300,
  keepSessionIds: [],
};

const PREF_THEME = "cursorLauncher.theme";
const PREF_USAGE = "cursorLauncher.usageStyle";

function loadPrefs() {
  try {
    const theme = localStorage.getItem(PREF_THEME) || "light";
    const usage = localStorage.getItem(PREF_USAGE) || "ring";
    document.documentElement.setAttribute("data-theme", theme === "dark" ? "dark" : "light");
    document.documentElement.setAttribute("data-usage", usage === "bar" ? "bar" : "ring");
    syncPrefButtons();
  } catch {
    document.documentElement.setAttribute("data-theme", "light");
    document.documentElement.setAttribute("data-usage", "ring");
  }
}

function syncPrefButtons() {
  const theme = document.documentElement.getAttribute("data-theme") || "light";
  const usage = document.documentElement.getAttribute("data-usage") || "ring";
  const themeBtn = $("btnTheme");
  const usageBtn = $("btnUsageStyle");
  if (themeBtn) {
    const label = theme === "dark" ? "切换日间模式" : "切换夜间模式";
    themeBtn.title = label;
    themeBtn.setAttribute("aria-label", label);
  }
  if (usageBtn) {
    const label = usage === "bar" ? "切换为圆形额度" : "切换为条形额度";
    usageBtn.title = label;
    usageBtn.setAttribute("aria-label", label);
  }
}

function toggleTheme() {
  const next = (document.documentElement.getAttribute("data-theme") === "dark") ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem(PREF_THEME, next); } catch {}
  syncPrefButtons();
}

function toggleUsageStyle() {
  const next = (document.documentElement.getAttribute("data-usage") === "bar") ? "ring" : "bar";
  document.documentElement.setAttribute("data-usage", next);
  try { localStorage.setItem(PREF_USAGE, next); } catch {}
  syncPrefButtons();
  paintAccounts();
}

loadPrefs();

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 2600);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtTime(v) {
  if (!v) return "-";
  const n = Number(v);
  const d = Number.isFinite(n) && n > 0 ? new Date(n > 1e12 ? n : n * 1000) : new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString("zh-CN", { hour12: false });
}

function fmtDate(v) {
  if (!v) return "-";
  const n = Number(v);
  const d = new Date(n > 1e12 ? n : n * 1000);
  return Number.isNaN(d.getTime()) ? "-" : d.toLocaleDateString("zh-CN");
}

function relativeAge(v) {
  if (!v) return "";
  const n = Number(v);
  const ms = Number.isFinite(n) && n > 0 ? (n > 1e12 ? n : n * 1000) : Date.parse(v);
  if (!Number.isFinite(ms)) return "";
  const days = Math.floor((Date.now() - ms) / 86400000);
  if (days <= 0) return "今天";
  if (days === 1) return "1天前";
  return `${days}天前`;
}

function daysLeft(ms) {
  if (!ms) return "";
  const d = Math.ceil((ms - Date.now()) / 86400000);
  if (d < 0) return "已过期";
  return `${d}天后`;
}

function closeAddDialog() {
  $("addDialog").close();
  $("tokenInput").value = "";
  $("addEmail").value = "";
  $("addPassword").value = "";
  $("addGroup").value = "";
  $("addTags").value = "";
}

function displayEmail(a) {
  if (a.email && String(a.email).includes("@")) return a.email;
  if (a.label && String(a.label).includes("@")) return a.label;
  return a.email || a.label || a.id;
}

function membershipClass(mt) {
  const x = String(mt || "").toLowerCase();
  if (x.includes("ultra")) return "ultra";
  if (x.includes("pro")) return "pro";
  if (x.includes("trial")) return "trial";
  if (x.includes("free")) return "free";
  return "custom";
}

function membershipLabel(mt) {
  const x = String(mt || "").toLowerCase();
  if (!x) return "未知";
  if (x.includes("ultra")) return "Ultra";
  if (x.includes("pro")) return "Pro";
  if (x.includes("trial")) return "Trial";
  if (x.includes("free")) return "Free";
  return String(mt).slice(0, 12);
}

function pct(v) {
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? Math.min(100, Math.round(n)) : 0;
}

function fmtTokens(n) {
  const v = Number(n) || 0;
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(v);
}

function modelUsageRows(rows, mode) {
  if (!rows || !rows.length) {
    return `<p class="hint">暂无数据</p>`;
  }
  return rows.map((r) => {
    const p = pct(r.tokenPct);
    const meta = mode === "cost"
      ? `$${Number(r.costUsd || 0).toFixed(2)} · ${p}%`
      : `${fmtTokens(r.tokens)} tokens · ${p}%`;
    return `<div class="model-row">
      <div class="model-row-head"><span class="model-name" title="${esc(r.model)}">${esc(r.model)}</span><span class="model-meta">${meta}</span></div>
      <div class="progress-bar sm"><div class="progress-fill ${mode === "cost" ? "pink" : "green"}" style="width:${p}%"></div></div>
    </div>`;
  }).join("");
}

function modelUsageContent(mu) {
  if (!mu || (!mu.included && !mu.onDemand)) {
    return `<p class="hint">本周期暂无模型明细</p>`;
  }
  const range = mu.periodStartMs && mu.periodEndMs
    ? `${fmtDate(mu.periodStartMs)} ~ ${fmtDate(mu.periodEndMs)}`
    : "当前计费周期";
  const inc = mu.included || {};
  const od = mu.onDemand || {};
  const totalInc = fmtTokens(inc.totalTokens || 0);
  let html = `<p class="hint">${esc(range)} · 套餐内 ${totalInc} tokens</p>`;
  if ((inc.cursorModels || []).length) {
    html += `<h4 class="model-group-title">Cursor Models</h4>${modelUsageRows(inc.cursorModels, "tokens")}`;
  }
  if ((inc.otherModels || []).length) {
    html += `<h4 class="model-group-title">Other Models</h4>${modelUsageRows(inc.otherModels, "tokens")}`;
  }
  if ((od.models || []).length) {
    html += `<h4 class="model-group-title">On-Demand · $${Number(od.totalUsd || 0).toFixed(2)}</h4>${modelUsageRows(od.models, "cost")}`;
  }
  if (!(inc.cursorModels || []).length && !(inc.otherModels || []).length && !(od.models || []).length) {
    html = `<p class="hint">本周期暂无模型明细</p>`;
  }
  return html;
}

function modelUsageBlock() {
  return `<div class="detail-section model-usage">
    <div class="section-head"><h3>模型用量</h3><button type="button" class="btn sm" id="btnLoadModelUsage">查看</button></div>
    <div id="modelUsagePanel"><p class="hint">点击「查看」拉取当前周期各模型 token 统计（同 Cursor Billing）</p></div>
  </div>`;
}

function setModelUsageButton(loaded) {
  const btn = $("btnLoadModelUsage");
  if (!btn) return;
  btn.textContent = loaded ? "刷新" : "查看";
  btn.disabled = false;
}

function renderModelUsagePanel(mu) {
  const panel = $("modelUsagePanel");
  if (panel) panel.innerHTML = modelUsageContent(mu);
  setModelUsageButton(true);
}

async function loadModelUsage(force = false) {
  if (!detailAccountId) return;
  if (!force && modelUsageCache[detailAccountId]) {
    renderModelUsagePanel(modelUsageCache[detailAccountId]);
    return;
  }
  const btn = $("btnLoadModelUsage");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "加载中…";
  }
  const res = await api().fetch_account_model_usage(detailAccountId);
  if (!res.ok) {
    if (btn) setModelUsageButton(Boolean(modelUsageCache[detailAccountId]));
    const panel = $("modelUsagePanel");
    if (panel) panel.innerHTML = `<p class="hint">${esc(res.error || "加载失败")}</p>`;
    toast(res.error || "模型用量加载失败");
    return;
  }
  modelUsageCache[detailAccountId] = res.modelUsage;
  renderModelUsagePanel(res.modelUsage);
  toast("模型用量已加载");
}

function ringHtml(label, value, color) {
  const p = pct(value);
  const r = 22;
  const c = 2 * Math.PI * r;
  const off = c * (1 - p / 100);
  return `<div class="ring-item"><div class="ring"><svg width="52" height="52" viewBox="0 0 52 52"><circle class="ring-bg" cx="26" cy="26" r="${r}"></circle><circle class="ring-fg" cx="26" cy="26" r="${r}" stroke="${color}" stroke-dasharray="${c}" stroke-dashoffset="${off}"></circle></svg><div class="ring-val">${p >= 0 ? p : "—"}</div></div><div class="ring-label">${esc(label)}</div></div>`;
}

function barHtml(label, value, color) {
  const p = pct(value);
  return `<div class="usage-bar-row">
    <div class="usage-bar-head"><span class="name">${esc(label)}</span><span class="val">${p}%</span></div>
    <div class="usage-bar-track"><div class="usage-bar-fill" style="width:${p}%;background:${color}"></div></div>
  </div>`;
}

function usageBlock(apiPct, autoPct, botPct) {
  const style = document.documentElement.getAttribute("data-usage") || "ring";
  if (style === "bar") {
    return `<div class="usage-bars">
      ${barHtml("高级", apiPct, "#ef4444")}
      ${barHtml("Auto", autoPct, "#22c55e")}
      ${barHtml("Bot", botPct, "#f59e0b")}
    </div>`;
  }
  return `<div class="ring-row">
    ${ringHtml("高级", apiPct, "#ef4444")}
    ${ringHtml("Auto", autoPct, "#22c55e")}
    ${ringHtml("Bot", botPct, "#f59e0b")}
  </div>`;
}

function hasWsToken(a) {
  const t = a?.token || "";
  return a?.hasWsToken || t.includes("::") || t.toLowerCase().includes("%3a%3a");
}

function splitDisplayTokens(a) {
  const raw = String(a?.token || "").trim();
  let access = String(a?.accessToken || "").trim();
  let ws = String(a?.wsToken || "").trim();
  if (!access && raw) {
    const lower = raw.toLowerCase();
    if (raw.includes("::")) access = raw.slice(raw.indexOf("::") + 2);
    else if (lower.includes("%3a%3a")) access = raw.slice(lower.indexOf("%3a%3a") + 6);
    else access = raw;
  }
  if (!ws && hasWsToken(a) && a?.id && access) ws = `${a.id}::${access}`;
  return { accessToken: access, wsToken: ws };
}

function tokenBox(title, value, hint, warn) {
  const empty = !value;
  return `<div class="token-block">
    <div class="progress-head">
      <strong>${esc(title)}</strong>
      ${empty ? "<span class=\"hint\">无</span>" : `<button type="button" class="copy-link" data-copy="${esc(value)}">复制</button>`}
    </div>
    <textarea class="token-box" readonly spellcheck="false" rows="3" placeholder="尚未保存">${esc(value)}</textarea>
    ${hint ? `<p class="hint token-hint ${warn ? "warn" : ""}">${hint}</p>` : ""}
  </div>`;
}

function tokenDetailSection(a) {
  const { accessToken, wsToken } = splitDisplayTokens(a);
  return `<div class="detail-section token-section">
    ${tokenBox("Access Token", accessToken, "Cursor 登录用的 JWT（cursorAuth/accessToken）", false)}
    ${tokenBox(
      "WS Token",
      wsToken,
      wsToken
        ? "设备管理 / 踢设备推荐 user_xxx::eyJ… 格式"
        : "当前没有 WS Token。可点「同步本机 WS」，或先在 Cursor 网页完成登录",
      !wsToken,
    )}
  </div>`;
}

function progressBlock(title, used, max, percent, colorClass, legend) {
  const p = pct(percent);
  return `<div class="detail-section"><div class="progress-head"><strong>${esc(title)}</strong><span>${esc(used)}</span></div><div class="progress-bar"><div class="progress-fill ${colorClass}" style="width:${p}%"></div></div>${legend ? `<div class="progress-legend">${legend}</div>` : ""}</div>`;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制");
  } catch {
    toast("复制失败");
  }
}

function selectedAccountIds() {
  return [...document.querySelectorAll(".acc-check:checked")].map((el) => el.getAttribute("data-select")).filter(Boolean);
}

function setAllAccountChecks(checked) {
  document.querySelectorAll(".acc-check[data-select]").forEach((el) => {
    el.checked = checked;
  });
}

async function exportAccounts() {
  let ids = selectedAccountIds();
  if (!ids.length) {
    if (!confirm("未勾选账号，将导出列表中的全部账号。继续？")) return;
  }
  const includeSecrets = confirm("是否在导出文件中包含 Token 与密码？\n（敏感信息，请妥善保管）");
  toast("正在导出…");
  const res = await api().export_accounts(ids.length ? ids : null, includeSecrets, "json");
  if (res.cancelled) return;
  toast(res.ok ? `已导出 ${res.count} 个账号` : (res.error || "导出失败"));
}

function filteredAccounts() {
  const q = ($("searchInput").value || "").trim().toLowerCase();
  const group = $("filterGroup").value;
  const tag = $("filterTag").value;
  const plan = $("filterPlan").value;
  return accounts.filter((a) => {
    const hay = `${a.email || ""} ${a.label || ""} ${a.remark || ""} ${a.membershipType || ""}`.toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (group && (a.group || "未分组") !== group) return false;
    if (tag && !(a.tags || []).includes(tag)) return false;
    if (plan && !String(a.membershipType || "").toLowerCase().includes(plan)) return false;
    return true;
  });
}

function isLocalAccount(a) {
  if (localIdentity.userId && a.id === localIdentity.userId) return true;
  const email = (localIdentity.email || "").toLowerCase();
  if (email && displayEmail(a).toLowerCase() === email) return true;
  return false;
}

function ico(name) {
  const paths = {
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.3"/><path d="M21 3v6h-6"/>',
    devices: '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || ""}</svg>`;
}

function renderAccountCard(a) {
  const email = displayEmail(a);
  const initial = (email[0] || "?").toUpperCase();
  const mClass = membershipClass(a.membershipType);
  const local = isLocalAccount(a);
  const badges = [];
  if (local) badges.push('<span class="tag local">本机</span>');
  badges.push(`<span class="tag ${mClass}">${esc(membershipLabel(a.membershipType))}</span>`);
  if (hasWsToken(a)) badges.push('<span class="tag pro">WS</span>');
  else badges.push('<span class="tag custom">JWT</span>');
  (a.tags || []).forEach((t) => badges.push(`<span class="tag custom">${esc(t)}</span>`));
  if (a.hasPassword) badges.push('<span class="tag">密码</span>');
  const expiry = a.proExpiryMs ? `周期至 ${fmtDate(a.proExpiryMs)} · ${daysLeft(a.proExpiryMs)}` : "周期未知";
  const stats = `近30天 $${Number(a.periodCostUsd || 0).toFixed(2)} · ${a.requestCount30d || 0}次`;
  const apiPct = a.apiPercentUsed >= 0 ? a.apiPercentUsed : a.includedApiPct;
  const autoPct = a.autoPercentUsed >= 0 ? a.autoPercentUsed : a.includedTotalPct;
  const botPct = a.botPercent;
  const err = a.err ? `<div class="hint" style="color:var(--danger)">${esc(a.err)}</div>` : "";
  const switchAction = local ? "launch-here" : "switch";
  const switchLabel = local ? "启动" : "切换";
  const switchTitle = local ? "当前就是这个账号，直接启动 IDE" : "写入此账号并启动 IDE";

  return `<article class="acc-card${local ? " is-local" : ""}" data-id="${esc(a.id)}">
    <div class="acc-head">
      <input type="checkbox" class="acc-check" data-select="${esc(a.id)}" />
      <div class="acc-avatar">${esc(initial)}</div>
      <div class="acc-meta">
        <div class="acc-email" title="${esc(email)}">${esc(email)}</div>
        <div class="acc-badges">${badges.join("")}</div>
        <div class="acc-sub">${esc(expiry)}</div>
        <div class="acc-stats">${esc(stats)}</div>
      </div>
    </div>
    ${err}
    ${usageBlock(apiPct, autoPct, botPct)}
    <div class="acc-foot">
      <button class="icon-btn" data-action="copy-token" data-id="${esc(a.id)}" title="复制 Token">${ico("copy")}</button>
      <button class="icon-btn" data-action="detail" data-id="${esc(a.id)}" title="详情">${ico("info")}</button>
      <button class="icon-btn" data-action="refresh" data-id="${esc(a.id)}" title="刷新额度">${ico("refresh")}</button>
      <button class="icon-btn" data-action="devices" data-id="${esc(a.id)}" title="登录设备">${ico("devices")}</button>
      <button class="btn primary btn-switch" data-action="${switchAction}" data-id="${esc(a.id)}" title="${switchTitle}">${switchLabel}</button>
      <button class="icon-btn danger" data-action="remove" data-id="${esc(a.id)}" title="删除">${ico("trash")}</button>
    </div>
  </article>`;
}

async function renderAccounts() {
  accounts = await api().list_accounts();
  const filters = await api().list_account_filters();
  fillSelect($("filterGroup"), "全部分组", filters.groups || []);
  fillSelect($("filterTag"), "全部标签", filters.tags || []);
  paintAccounts();
}

function paintAccounts() {
  const rows = filteredAccounts();
  $("accGrid").innerHTML = rows.map(renderAccountCard).join("");
  $("emptyAccounts").hidden = rows.length > 0;
  const sub = $("brandSub");
  if (sub) sub.textContent = accounts.length ? `${accounts.length} 个账号` : "还没有账号";
}

function fillSelect(el, allLabel, items) {
  const cur = el.value;
  el.innerHTML = `<option value="">${allLabel}</option>` + items.map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
  if ([...el.options].some((o) => o.value === cur)) el.value = cur;
}

function paintSettingsMeta(status) {
  const el = $("settingsMeta");
  if (!el) return;
  const bits = [];
  const host = $("proxyHost")?.value;
  const port = $("proxyPort")?.value;
  const enabled = $("proxyEnabled")?.checked;
  if (enabled === false) bits.push("代理关");
  else if (host && port) bits.push(`${host}:${port}`);
  if (status?.version) bits.push(`v${status.version}`);
  el.textContent = bits.join(" · ");
}

function maybePaintLocalCards() {
  const nextKey = `${localIdentity.userId}|${(localIdentity.email || "").toLowerCase()}`;
  const prevKey = refreshCursorStatus._ident || "";
  refreshCursorStatus._ident = nextKey;
  if (accounts.length && prevKey !== nextKey) paintAccounts();
}

async function refreshCursorStatus(opts = {}) {
  const res = await api().cursor_status();
  lastCursorStatus = res;
  localIdentity = {
    email: res.localEmail || "",
    userId: res.localUserId || "",
  };
  const pill = $("loginPill");
  if (!res.ok) {
    pill.textContent = "未检测到 Cursor";
    pill.classList.remove("ok");
    pill.title = res.error || "请设置 Cursor 路径";
    if ($("cursorInfo")) $("cursorInfo").textContent = res.error || "请设置 Cursor 路径";
    paintSettingsMeta(res);
    if (opts.ctxwin) refreshCtxwin();
    maybePaintLocalCards();
    return;
  }
  const mem = res.running && res.memoryMb != null ? `${Math.round(res.memoryMb)}MB` : "";
  if (res.running) {
    pill.textContent = mem ? `运行中 · ${mem}` : "运行中";
    pill.classList.add("ok");
    pill.title = `${res.processCount || "?"} 个进程 · 点击削减内存`;
  } else {
    pill.textContent = "未运行";
    pill.classList.remove("ok");
    pill.title = "Cursor 未运行";
  }
  const pathInput = $("cursorPath");
  if (pathInput && document.activeElement !== pathInput) {
    pathInput.value = res.configuredPath || "";
    pathInput.placeholder = res.executable || "留空则自动检测 Cursor.exe";
  }
  if ($("cursorInfo")) {
    const loc = [res.executable, res.version ? `v${res.version}` : ""].filter(Boolean).join(" · ");
    const run = res.running
      ? `${res.processCount || "?"} 进程 · ${mem || "?"}`
      : "未运行";
    $("cursorInfo").textContent = `${loc}\n${run}`;
  }
  const compactBtn = $("btnCompactState");
  if (compactBtn) {
    compactBtn.classList.toggle("is-blocked", Boolean(res.running));
    compactBtn.title = res.running
      ? "目前 Cursor 正在运行，状态库被占用，无法压缩"
      : "压缩状态库（先关闭 IDE）";
  }
  paintSettingsMeta(res);
  if (opts.ctxwin) refreshCtxwin();
  maybePaintLocalCards();
}

async function loadProxy() {
  const res = await api().get_proxy();
  const cfg = res.saved || {};
  $("proxyEnabled").checked = cfg.enabled !== false;
  $("proxyOnLaunch").checked = cfg.apply_on_launch === true || cfg.applyOnLaunch === true;
  $("proxyType").value = cfg.proxy_type || cfg.proxyType || "http";
  $("proxyHost").value = cfg.host || "127.0.0.1";
  $("proxyPort").value = cfg.port || 7890;
  paintSettingsMeta(lastCursorStatus);
}

function paintCtxwin(res) {
  const info = $("ctxwinInfo");
  const applyBtn = $("btnCtxwinApply");
  const restoreBtn = $("btnCtxwinRestore");
  if (!info) return;
  if (!res || !res.ok) {
    info.textContent = res?.error || "无法检测补丁状态";
    if (applyBtn) applyBtn.classList.add("is-blocked");
    if (restoreBtn) restoreBtn.classList.add("is-blocked");
    return;
  }
  const lines = [
    res.patched ? "状态：已打上 500k" : "状态：官方 256k（未打补丁）",
    `窗口 ${res.from || 256000} → ${res.to || 500000}`,
    res.version ? `Cursor v${res.version}` : "",
    res.running ? "IDE 正在运行，改文件前请先关闭" : "IDE 未运行，可以改文件",
    res.node ? `Node ${res.node}` : "未找到 Node.js，无法打补丁",
  ].filter(Boolean);
  info.textContent = lines.join("\n");
  if (applyBtn) {
    applyBtn.classList.toggle("is-blocked", !res.canApply);
    applyBtn.title = res.running
      ? "请先关闭 IDE"
      : (!res.node ? "需要本机 Node.js" : "把 grok Extra High 窗口改成 500k");
  }
  if (restoreBtn) {
    restoreBtn.classList.toggle("is-blocked", !res.canRestore);
    restoreBtn.title = res.patched ? "去掉补丁，回到官方 256k" : "当前没有补丁";
  }
}

async function refreshCtxwin() {
  if (!api()?.ctxwin_status) return;
  try {
    paintCtxwin(await api().ctxwin_status());
  } catch (e) {
    paintCtxwin({ ok: false, error: String(e) });
  }
}

async function runCtxwin(kind) {
  const status = await api().ctxwin_status();
  if (kind === "apply" && !status.canApply) {
    paintCtxwin(status);
    return toast(status.running ? "请先关闭 IDE" : (status.error || "当前不能打补丁"));
  }
  if (kind === "restore" && !status.canRestore) {
    paintCtxwin(status);
    return toast(status.patched ? (status.running ? "请先关闭 IDE" : "无法还原") : "当前没有补丁");
  }
  const fn = kind === "restore" ? "ctxwin_restore" : "ctxwin_apply";
  const info = $("ctxwinInfo");
  if (info) info.textContent = kind === "restore" ? "正在还原…" : "正在打补丁…";
  const res = await api()[fn]();
  paintCtxwin(res);
  if (!res.ok) return toast(res.error || "失败");
  if (res.skipped) return toast(res.message || "无需还原");
  toast(kind === "restore" ? "已还原官方 256k，请再启动 IDE" : "已打上 500k，请再启动 IDE");
}

async function openDetail(accountId) {
  detailAccountId = accountId;
  const res = await api().get_account_detail(accountId);
  if (!res.ok) return toast(res.error || "加载失败");
  renderDetail(res.account);
  $("detailDialog").showModal();
}

function renderDetail(a) {
  const expiryDays = a.proExpiryMs ? daysLeft(a.proExpiryMs) : "";
  const body = $("detailBody");
  body.innerHTML = `
    <div class="detail-section">
      <div class="kv">
        <div class="k">邮箱</div><div class="v">${esc(displayEmail(a))}</div><button class="copy-link" data-copy="${esc(displayEmail(a))}">复制</button>
        <div class="k">User ID</div><div class="v">${esc(a.id)}</div><button class="copy-link" data-copy="${esc(a.id)}">复制</button>
        <div class="k">分组</div><div class="v"><input id="detailGroup" value="${esc(a.group || "未分组")}" /></div><span></span>
        <div class="k">标签</div><div class="v"><input id="detailTags" value="${esc((a.tags || []).join(","))}" placeholder="逗号分隔" /></div><span></span>
        <div class="k">备注</div><div class="v"><input id="detailRemark" value="${esc(a.remark || "")}" /></div><span></span>
        <div class="k">密码</div><div class="v"><input id="detailPassword" type="password" value="${esc(a.password || "")}" placeholder="本地加密保存" /></div><span></span>
        <div class="k">套餐</div><div class="v"><span class="tag ${membershipClass(a.membershipType)}">${esc(membershipLabel(a.membershipType))}</span> ${expiryDays ? `周期至 ${fmtDate(a.proExpiryMs)} · ${expiryDays}` : ""}</div><span></span>
        <div class="k">最近刷新</div><div class="v">${esc(fmtTime(a.lastRefreshed))}</div><span></span>
      </div>
    </div>
    ${tokenDetailSection(a)}
    ${progressBlock("费用概览（近30天）", `$${Number(a.periodCostUsd || 0).toFixed(2)}`, "", Math.min(100, (a.periodCostUsd || 0) * 4), "pink", `<span>${a.requestCount30d || 0} 次请求</span>`)}
    ${progressBlock("套餐额度", `$${Number(a.costUsd || 0).toFixed(2)} / $${Number(a.costMaxUsd || 0).toFixed(2)}`, "", a.usagePct >= 0 ? a.usagePct : pct((a.costUsd / Math.max(a.costMaxUsd, 0.01)) * 100), "green", `<span>Auto ${pct(a.autoPercentUsed)}%</span><span>API ${pct(a.apiPercentUsed)}%</span>${a.giftUsd ? `<span>赠送 $${a.giftUsd}</span>` : ""}`)}
    ${a.botPercent >= 0 ? progressBlock("Grok Bot 独立额度", `${pct(a.botPercent)}%`, "", a.botPercent, "teal", a.botResetMs ? `<span>重置于 ${fmtTime(a.botResetMs)}</span>` : "") : ""}
    <div class="detail-section"><h3>用量分类</h3><div class="usage-cards">
      <div class="usage-card"><h4>Auto 模式</h4><div>${pct(a.autoPercentUsed)}%</div><div class="progress-bar" style="margin-top:8px"><div class="progress-fill green" style="width:${pct(a.autoPercentUsed)}%"></div></div><div class="hint">${esc(a.autoModelMessage || "—")}</div></div>
      <div class="usage-card"><h4>高级模型</h4><div>${pct(a.apiPercentUsed)}%</div><div class="progress-bar" style="margin-top:8px"><div class="progress-fill purple" style="width:${pct(a.apiPercentUsed)}%"></div></div><div class="hint">${esc(a.namedModelMessage || "—")}</div></div>
    </div></div>
    ${modelUsageBlock()}
    ${a.onDemandUsd ? `<div class="detail-section"><div class="progress-head"><strong>按需用量</strong><span>$${Number(a.onDemandUsd).toFixed(2)}</span></div></div>` : ""}
  `;
  if (modelUsageCache[a.id]) {
    renderModelUsagePanel(modelUsageCache[a.id]);
  }
}

async function saveDetailMeta() {
  if (!detailAccountId) return;
  const tags = ($("detailTags").value || "").split(/[,，]/).map((s) => s.trim()).filter(Boolean);
  const res = await api().update_account(detailAccountId, {
    group: $("detailGroup").value,
    tags,
    remark: $("detailRemark").value,
    password: $("detailPassword").value,
  });
  toast(res.ok ? "已保存" : (res.error || "失败"));
  await renderAccounts();
}

async function refreshOne(accountId) {
  toast("正在刷新额度…");
  const res = await api().refresh_account(accountId);
  toast(res.ok ? "刷新成功" : (res.error || "失败"));
  await renderAccounts();
  if (detailAccountId === accountId && res.ok) {
    const detail = await api().get_account_detail(accountId);
    if (detail.ok) renderDetail(detail.account);
  }
}

async function launch(accountId, force = false, light = false) {
  if (!accountId && !force && !light) {
    const st = await api().cursor_status();
    if (st.running && !confirm("Cursor 已在运行，仍要启动新实例？")) return;
    force = st.running;
  }
  const machineMode = accountId ? "bind" : "none";
  if (light) toast("正在轻量启动（关 GPU、空工作区）…");
  else if (accountId) toast("正在切号并启动 IDE…");
  else toast("正在启动 IDE…");
  const res = await api().launch_ide(accountId || null, false, force, machineMode, light);
  if (res.alreadyRunning && !force) {
    if (confirm(res.error || "Cursor 已在运行，仍要启动新实例？")) {
      return launch(accountId, true, light);
    }
    return;
  }
  toast(res.ok
    ? (light ? "已轻量启动 Cursor" : (accountId ? "已切换并启动 Cursor（--classic）" : "已启动 Cursor（--classic）"))
    : (res.error || "失败"));
  await refreshCursorStatus();
}

async function closeIde() {
  if (!confirm("关闭 Cursor 以腾出内存？账号仍留在启动器里。")) return;
  toast("正在关闭 IDE…");
  const res = await api().close_ide();
  toast(res.ok ? (res.closed ? "已关闭 Cursor" : "Cursor 本来就没在运行") : (res.error || "关闭失败"));
  await refreshCursorStatus();
}

async function compactState() {
  const pre = await api().compact_precheck();
  if (!pre.ok) {
    toast(pre.error || "目前无法压缩");
    if ($("cursorInfo")) $("cursorInfo").textContent = pre.error || "无法压缩";
    showCompactBanner({
      pct: 0,
      phase: "blocked",
      message: pre.error || "目前 Cursor 正在运行，无法压缩",
    });
    return;
  }
  const size = pre.sizeMb ? `${pre.sizeMb}MB` : "";
  if (!confirm(`将压缩状态库${size ? "（约 " + size + "）" : ""}。\n压缩完成前请不要打开 Cursor。`)) return;
  showCompactBanner({ pct: 2, phase: "start", message: `准备压缩 ${size || "状态库"}…` });
  settleCompact._once = false;
  const res = await api().compact_start();
  if (!res.ok) {
    toast(res.error || "无法开始压缩");
    showCompactBanner({ pct: 0, phase: "error", message: res.error || "无法开始压缩" });
    return;
  }
  watchCompactProgress();
}

function showCompactBanner(p) {
  const bar = $("compactBanner");
  if (!bar) return;
  bar.hidden = false;
  const pct = Math.max(0, Math.min(100, Number(p.pct) || 0));
  if ($("compactFill")) $("compactFill").style.width = `${pct}%`;
  if ($("compactText")) $("compactText").textContent = p.message || "正在压缩…";
  if ($("compactPct")) $("compactPct").textContent = p.phase === "blocked" || p.phase === "error" ? "" : `${pct}%`;
  bar.classList.toggle("is-done", p.phase === "done");
  bar.classList.toggle("is-error", p.phase === "error" || p.phase === "blocked");
}

function hideCompactBannerLater() {
  clearTimeout(hideCompactBannerLater._t);
  hideCompactBannerLater._t = setTimeout(() => {
    const bar = $("compactBanner");
    if (bar) bar.hidden = true;
  }, 8000);
}

function settleCompact(p) {
  if (settleCompact._once) return;
  settleCompact._once = true;
  clearInterval(watchCompactProgress._t);
  if (p.phase === "done") toast("压缩完成，可以打开 Cursor 了");
  else if (p.phase === "error") toast(p.message || "压缩失败");
  hideCompactBannerLater();
}

function watchCompactProgress() {
  clearInterval(watchCompactProgress._t);
  watchCompactProgress._t = setInterval(async () => {
    try {
      const p = await api().compact_progress();
      if (!p) return;
      showCompactBanner(p);
      if (!p.busy) settleCompact(p);
    } catch {
      clearInterval(watchCompactProgress._t);
    }
  }, 400);
}

window.addEventListener("compact-progress", (ev) => {
  const p = ev.detail || {};
  showCompactBanner(p);
  if (!p.busy) settleCompact(p);
});

function updateGuardHint() {
  const mode = $("guardMode")?.value || guardConfig.mode || "whitelist";
  const enabled = $("guardEnabled")?.checked ?? guardConfig.enabled;
  if ($("guardHint")) {
    $("guardHint").textContent = enabled
      ? (mode === "auto_kick" ? "守卫已启用 · 自动踢新 Web（Desktop 不踢）" : "守卫已启用 · 踢未勾选的 Web（Desktop 保留）")
      : "「踢其它」只清 Web/其它端，Desktop 全部默认保留";
  }
  if ($("guardModeHint")) {
    $("guardModeHint").textContent = mode === "auto_kick"
      ? "保存后将以当前设备列表为基准；之后仅踢掉新出现的登录。"
      : "勾选下方设备为保留名单；定时踢掉未勾选的会话。";
  }
  const statusEl = $("guardStatus");
  if (statusEl) {
    statusEl.textContent = enabled ? "运行中" : "未启用";
    statusEl.classList.toggle("on", enabled);
  }
}

function collectKeepSessionIds() {
  const keep = new Set();
  document.querySelectorAll("[data-keep]").forEach((el) => {
    if (el.checked) keep.add(el.getAttribute("data-keep"));
  });
  for (const s of sessions) if (s.isCurrent) keep.add(s.id);
  return [...keep];
}

async function saveGuard() {
  if (!activeAccountId) return;
  const enabled = $("guardEnabled").checked;
  const mode = $("guardMode").value || "whitelist";
  const intervalSeconds = Math.max(60, Number($("guardInterval").value || 5) * 60);
  const keepIds = collectKeepSessionIds();
  const res = await api().save_session_guard(activeAccountId, enabled, keepIds, intervalSeconds, mode);
  if (!res.ok) return toast(res.error || "保存失败");
  guardConfig = res.guard || guardConfig;
  updateGuardHint();
  toast("守卫配置已保存");
}

async function runGuardNow() {
  if (!activeAccountId) return;
  toast("正在执行守卫巡检…");
  const res = await api().run_session_guard(activeAccountId);
  if (!res.ok) return toast(res.error || "巡检失败");
  const n = (res.revoked || []).length;
  toast(n ? `守卫已踢掉 ${n} 台设备` : "没有需要踢掉的设备");
  await loadSessions();
  await renderAccounts();
}

let devicesFromDetail = false;

async function openDevices(accountId, fromDetail = false) {
  activeAccountId = accountId;
  devicesFromDetail = fromDetail;
  $("devicesDialog").showModal();
  await loadSessions();
}

function closeDetailDialog() { $("detailDialog").close(); }
async function closeDevicesDialog({ reopenDetail = true } = {}) {
  $("devicesDialog").close();
  if (reopenDetail && devicesFromDetail && detailAccountId) {
    devicesFromDetail = false;
    await openDetail(detailAccountId);
    return;
  }
  devicesFromDetail = false;
}

async function loadSessions() {
  if (!activeAccountId) return;
  const errEl = $("sessionLoadError");
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = "";
  }
  const res = await api().list_sessions(activeAccountId);
  if (!res.ok) {
    sessions = [];
    $("sessionCount").textContent = "0";
    $("sessionBody").innerHTML = "";
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = res.error || "拉取设备失败";
    }
    updateKickSummary();
    toast(res.error || "拉取设备失败");
    return;
  }
  sessions = res.sessions || [];
  autoKeepIds = new Set(res.autoKeepIds || []);
  keepReasons = res.keepReasons || {};
  guardConfig = res.guard || guardConfig;
  if ($("guardEnabled")) $("guardEnabled").checked = Boolean(guardConfig.enabled);
  if ($("guardMode")) $("guardMode").value = guardConfig.mode || "whitelist";
  if ($("guardInterval")) {
    $("guardInterval").value = String(Math.max(1, Math.round((guardConfig.intervalSeconds || 300) / 60)));
  }
  updateGuardHint();
  renderSessions();
}

function renderSessions() {
  $("sessionCount").textContent = String(sessions.length);
  const keepSet = new Set(guardConfig.keepSessionIds || []);
  const body = $("sessionBody");
  if (!sessions.length) {
    body.innerHTML = '<p class="device-empty">暂无登录设备</p>';
    updateKickSummary();
    return;
  }
  body.innerHTML = sessions.map((s) => {
    const isDesktop = s.sessionType === "SESSION_TYPE_CLIENT";
    const protectedRow = s.isCurrent || autoKeepIds.has(s.id) || isDesktop;
    const keepChecked = protectedRow || keepSet.has(s.id);
    const canToggle = !protectedRow;
    const badge = s.isCurrent
      ? '<span class="tag">本机</span>'
      : (isDesktop ? '<span class="tag pro">保护</span>' : "");
    const when = s.createdAt
      ? `${fmtTime(s.createdAt)} · ${relativeAge(s.createdAt)}`
      : "";
    const reason = keepReasons[s.id] || "";
    return `<div class="device-item ${protectedRow ? "protected" : ""}">
      <input type="checkbox" data-keep="${esc(s.id)}" ${keepChecked ? "checked" : ""} ${canToggle ? "" : "disabled"} />
      <div>
        <strong>${esc(s.typeLabel)}</strong> ${badge}
        <div class="hint">${esc(when || "登录时间未知")}</div>
        ${reason ? `<div class="hint">${esc(reason)}</div>` : ""}
      </div>
      ${protectedRow ? "" : `<button class="btn sm danger" data-kick="${esc(s.id)}" data-type="${esc(s.sessionType || "")}">Revoke</button>`}
    </div>`;
  }).join("");
  updateKickSummary();
}

function updateKickSummary() {
  const keep = new Set(collectKeepSessionIds());
  // 与后端一致：Desktop 永不批量踢
  const kickTargets = sessions.filter(
    (s) => !keep.has(s.id) && !s.isCurrent && s.sessionType !== "SESSION_TYPE_CLIENT"
  );
  const kickCount = kickTargets.length;
  $("kickSummary").textContent = kickCount
    ? `将踢掉 ${kickCount} 台 Web/其它端，Desktop 全部保留`
    : "没有需要踢掉的设备（Desktop 已保护）";
  $("btnKickOthers").disabled = kickCount === 0;
}

async function kickOthers() {
  if (!activeAccountId) return;
  const keep = collectKeepSessionIds();
  const targets = sessions.filter(
    (s) => !keep.includes(s.id) && !s.isCurrent && s.sessionType !== "SESSION_TYPE_CLIENT"
  );
  if (!targets.length) return toast("没有可踢的设备");
  const preview = targets
    .slice(0, 8)
    .map((s) => `· ${s.typeLabel} ${fmtTime(s.createdAt)}`)
    .join("\n");
  const more = targets.length > 8 ? `\n…另有 ${targets.length - 8} 台` : "";
  if (!confirm(`将踢掉 ${targets.length} 台（不含任何 Desktop）：\n${preview}${more}\n\nDesktop 本机不会被踢。确定？`)) {
    return;
  }
  const res = await api().revoke_other_sessions(activeAccountId, keep);
  toast(res.ok ? `已踢 ${(res.revoked || []).length} 台` : (res.error || "失败"));
  await loadSessions();
  await renderAccounts();
}

$("sessionBody")?.addEventListener("change", (ev) => {
  if (ev.target.matches("[data-keep]")) updateKickSummary();
});

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("[data-action], [data-copy], [data-kick], .copy-link");
  if (!t) return;
  if (t.dataset.copy !== undefined) return copyText(t.dataset.copy);
  const id = t.dataset.id;
  const action = t.dataset.action;
  if (action === "detail") return openDetail(id);
  if (action === "copy-token") {
    const res = await api().get_account_detail(id);
    if (!res.ok || !res.account?.token) return toast(res.error || "无 Token");
    return copyText(res.account.token);
  }
  if (action === "refresh") return refreshOne(id);
  if (action === "devices") return openDevices(id);
  if (action === "switch") return launch(id);
  if (action === "launch-here") return launch(null);
  if (action === "remove") {
    if (!confirm("确定删除该账号？")) return;
    await api().remove_account(id);
    toast("已删除");
    await renderAccounts();
    return;
  }
  if (t.dataset.kick) {
    if (!confirm("确定踢掉该设备？")) return;
    const res = await api().revoke_session(activeAccountId, t.dataset.kick, t.dataset.type || null);
    toast(res.ok ? "已踢下线" : (res.error || "失败"));
    await loadSessions();
  }
});

$("searchInput").oninput = () => paintAccounts();
["filterGroup", "filterTag", "filterPlan"].forEach((id) => { $(id).onchange = () => paintAccounts(); });

$("btnAddOpen").onclick = () => $("addDialog").showModal();
$("btnAddCancel").onclick = closeAddDialog;
$("btnAddCancel2").onclick = closeAddDialog;
$("addDialog").addEventListener("cancel", (ev) => {
  ev.preventDefault();
  closeAddDialog();
});
$("btnAdd").onclick = async (ev) => {
  ev.preventDefault();
  const res = await api().import_text($("tokenInput").value);
  if (!res.added) return toast("未识别到 token");
  const added = res.accounts.slice(-res.added);
  for (const acct of added) {
    const tags = ($("addTags").value || "").split(/[,，]/).map((s) => s.trim()).filter(Boolean);
    await api().update_account(acct.id, {
      email: $("addEmail").value || undefined,
      password: $("addPassword").value || undefined,
      group: $("addGroup").value || undefined,
      tags: tags.length ? tags : undefined,
    });
    await api().refresh_account(acct.id);
  }
  $("tokenInput").value = "";
  closeAddDialog();
  toast(`已添加 ${res.added} 个账号`);
  await renderAccounts();
};
$("btnImport").onclick = async () => {
  const res = await api().import_files();
  toast(res.added ? `导入 ${res.added} 个` : "未选择文件");
  if (res.added) {
    for (const acct of res.accounts.slice(-res.added)) await api().refresh_account(acct.id);
    await renderAccounts();
  }
};
$("btnDetect").onclick = async () => {
  const res = await api().detect_local_account();
  if (!res.ok) {
    toast(res.error || "失败");
    return;
  }
  toast(`已探测 ${res.email || ""} ${res.hasWsToken ? "（含 WS Token，详情里可复制）" : "（仅 JWT，设备管理需 WS Token）"}`);
  if (res.id) await api().refresh_account(res.id);
  await renderAccounts();
};
$("btnRefreshAll").onclick = async () => {
  toast("正在刷新全部账号…");
  const res = await api().refresh_all_accounts();
  toast(`完成：${(res.refreshed || []).length} 成功，${(res.errors || []).length} 失败`);
  await renderAccounts();
};
$("btnLaunchLocal").onclick = () => launch(null);
$("btnLightLaunch").onclick = () => { closeIdeTools(); launch(null, true, true); };
$("btnTrimMemory").onclick = () => { closeIdeTools(); trimMemory(); };
$("btnCloseIde").onclick = () => { closeIdeTools(); closeIde(); };
$("btnCompactState").onclick = () => { closeIdeTools(); compactState(); };
$("loginPill").onclick = async () => {
  if (lastCursorStatus?.running) return trimMemory();
  await refreshCursorStatus();
};

function startStatusWatch() {
  clearInterval(startStatusWatch._t);
  startStatusWatch._t = setInterval(() => {
    if (document.hidden || !api()) return;
    refreshCursorStatus();
  }, 20000);
}

async function trimMemory() {
  toast("正在削减内存…");
  const res = await api().trim_memory();
  if (!res.ok) return toast(res.error || "削减失败");
  toast(res.message || "已削减");
  await refreshCursorStatus();
}

function closeIdeTools() {
  const el = $("ideTools");
  if (el) el.classList.remove("open");
  const menu = $("btnIdeMenu");
  if (menu) menu.setAttribute("aria-expanded", "false");
  const tray = $("ideTray");
  if (tray) tray.setAttribute("aria-hidden", "true");
}
function toggleIdeTools(ev) {
  ev.stopPropagation();
  const el = $("ideTools");
  const open = !el.classList.contains("open");
  el.classList.toggle("open", open);
  $("btnIdeMenu").setAttribute("aria-expanded", open ? "true" : "false");
  $("ideTray").setAttribute("aria-hidden", open ? "false" : "true");
}
$("btnIdeMenu").onclick = toggleIdeTools;
document.addEventListener("click", (ev) => {
  const el = $("ideTools");
  if (el && !el.contains(ev.target)) closeIdeTools();
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closeIdeTools();
});
$("btnDetectProxy").onclick = async () => {
  toast("正在检测本机代理…");
  $("proxyDetectInfo").textContent = "检测中…";
  try {
    const res = await api().detect_proxy(true);
    if (!res.ok) {
      $("proxyDetectInfo").textContent = res.error || "检测失败";
      return toast(res.error || "检测失败");
    }
    const rec = res.recommended;
    const lines = (res.candidates || []).map((c) => {
      const ms = c.probe && c.probe.latencyMs != null ? `${c.probe.latencyMs}ms` : "";
      const mark = c.reachable ? "✓" : (c.open ? "○" : "×");
      return `${mark} ${c.proxy_type}://${c.host}:${c.port}  ${ms}  ${c.label || ""}`;
    });
    if (rec) {
      $("proxyEnabled").checked = true;
      $("proxyType").value = rec.proxy_type || "http";
      $("proxyHost").value = rec.host || "127.0.0.1";
      $("proxyPort").value = rec.port || 7890;
      const ms = rec.probe && rec.probe.latencyMs != null ? ` · ${rec.probe.latencyMs}ms` : "";
      $("proxyDetectInfo").textContent =
        `已填入推荐：${rec.proxy_type}://${rec.host}:${rec.port}${ms}（${rec.label || ""}）\n` +
        (res.hint || "") + "\n" + lines.join("\n");
      toast(`已填入 ${rec.proxy_type}://${rec.host}:${rec.port}${ms}，请点「保存并注入」`);
    } else {
      $("proxyDetectInfo").textContent =
        "未发现可用本地代理。请先打开 Clash / v2rayN 等。\n" + (res.hint || "") + "\n" + lines.join("\n");
      toast("未发现可用代理");
    }
  } catch (e) {
    $("proxyDetectInfo").textContent = String(e);
    toast("检测失败：" + String(e));
  }
};
$("btnTestLatency").onclick = async () => {
  toast("正在测延迟…");
  $("proxyDetectInfo").textContent = "测延迟中…";
  try {
    const res = await api().test_proxy_latency(
      $("proxyType").value,
      $("proxyHost").value,
      Number($("proxyPort").value || 7890),
      $("proxyEnabled").checked
    );
    if (!res.ok && res.error && res.latencyMs == null) {
      $("proxyDetectInfo").textContent = res.error;
      return toast(res.error || "测延迟失败");
    }
    const mode = res.mode === "direct" ? "直连" : `${res.proxy_type || "http"}://${res.host}:${res.port}`;
    if (res.ok || res.status) {
      const grade = res.latencyMs < 400 ? "很快" : (res.latencyMs < 900 ? "一般" : "偏慢");
      $("proxyDetectInfo").textContent = `${mode}\n延迟 ${res.latencyMs}ms（${grade}） · HTTP ${res.status || "?"}`;
      toast(`${mode} · ${res.latencyMs}ms`);
    } else {
      $("proxyDetectInfo").textContent = `${mode}\n失败（约 ${res.latencyMs || "?"}ms）\n${res.error || ""}`;
      toast("测延迟失败：" + (res.error || "未知"));
    }
  } catch (e) {
    $("proxyDetectInfo").textContent = String(e);
    toast("测延迟失败：" + String(e));
  }
};
$("btnTheme").onclick = () => toggleTheme();
$("btnUsageStyle").onclick = () => toggleUsageStyle();
$("btnSaveProxy").onclick = async () => {
  const res = await api().save_proxy({
    enabled: $("proxyEnabled").checked,
    apply_on_launch: $("proxyOnLaunch").checked,
    proxy_type: $("proxyType").value,
    host: $("proxyHost").value,
    port: Number($("proxyPort").value || 7890),
    strict_ssl: false,
  });
  toast(res.ok ? "代理已保存" : (res.error || "失败"));
  paintSettingsMeta(lastCursorStatus);
};
$("btnSavePath").onclick = async () => {
  const res = await api().set_cursor_path($("cursorPath").value);
  toast(res.ok ? "路径已保存" : (res.error || "失败"));
  await refreshCursorStatus({ ctxwin: true });
};
$("btnCtxwinApply").onclick = () => runCtxwin("apply");
$("btnCtxwinRestore").onclick = () => runCtxwin("restore");
$("btnCtxwinRefresh").onclick = () => refreshCtxwin();
document.querySelector(".settings-fold")?.addEventListener("toggle", (ev) => {
  if (ev.target.open) refreshCtxwin();
});
$("detailBody").addEventListener("click", (ev) => {
  if (ev.target.id === "btnLoadModelUsage") {
    ev.preventDefault();
    loadModelUsage(ev.target.textContent === "刷新");
  }
});
$("detailClose").onclick = closeDetailDialog;
$("detailBack").onclick = closeDetailDialog;
$("detailBack2").onclick = closeDetailDialog;
$("devicesClose").onclick = () => closeDevicesDialog({ reopenDetail: false });
$("devicesBack").onclick = () => closeDevicesDialog({ reopenDetail: true });
$("devicesBack2").onclick = () => closeDevicesDialog({ reopenDetail: true });
async function syncDetailWs() {
  if (!detailAccountId) return;
  toast("正在从本机同步 WS Token…");
  const res = await api().sync_ws_token(detailAccountId);
  if (!res.ok) return toast(res.error || "同步失败");
  toast("WS Token 已同步");
  renderDetail(res.account);
  await renderAccounts();
}

$("btnDetailSyncWs").onclick = () => syncDetailWs();
$("btnDetailSave").onclick = () => saveDetailMeta();
$("btnDetailRefresh").onclick = () => detailAccountId && refreshOne(detailAccountId);
$("btnDetailSwitch").onclick = () => detailAccountId && launch(detailAccountId);
$("btnDetailDevices").onclick = () => {
  $("detailDialog").close();
  if (detailAccountId) openDevices(detailAccountId, true);
};
$("btnRefreshSessions").onclick = () => loadSessions();
$("btnKickOthers").onclick = () => kickOthers();
$("btnSaveGuard").onclick = () => saveGuard();
$("btnRunGuard").onclick = () => runGuardNow();
$("guardEnabled").onchange = () => updateGuardHint();
$("guardMode").onchange = () => updateGuardHint();
$("btnSelectAll").onclick = () => {
  const boxes = [...document.querySelectorAll(".acc-check[data-select]")];
  const allChecked = boxes.length && boxes.every((el) => el.checked);
  setAllAccountChecks(!allChecked);
};
$("btnExport").onclick = () => exportAccounts();

window.addEventListener("guard-event", (ev) => {
  const d = ev.detail || {};
  if (d.type === "guard_run") {
    const n = (d.revoked || []).length;
    if (n) toast(`守卫巡检：已踢 ${n} 台`);
  } else if (d.type === "guard_disabled") {
    toast("会话守卫已自动关闭（连续失败）");
    guardConfig.enabled = false;
    if ($("guardEnabled")) $("guardEnabled").checked = false;
    updateGuardHint();
  }
});

async function boot() {
  if (!api()) {
    const pill = $("loginPill");
    if (pill && boot._tries > 40) pill.textContent = "API 未就绪";
    boot._tries = (boot._tries || 0) + 1;
    return setTimeout(boot, 120);
  }
  try {
    await Promise.all([refreshCursorStatus({ ctxwin: true }), loadProxy(), renderAccounts()]);
    paintSettingsMeta(lastCursorStatus);
    startStatusWatch();
  } catch (e) {
    const pill = $("loginPill");
    if (pill) pill.textContent = "启动失败";
    toast("界面初始化失败：" + String(e));
  }
}
boot._tries = 0;
boot();
