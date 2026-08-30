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
let lastAccountId = "";
let lastWbDiag = null;
let pendingWbNext = null;
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
  const rows = accounts.filter((a) => {
    const hay = `${a.email || ""} ${a.label || ""} ${a.remark || ""} ${a.membershipType || ""}`.toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (group && (a.group || "未分组") !== group) return false;
    if (tag && !(a.tags || []).includes(tag)) return false;
    if (plan && !String(a.membershipType || "").toLowerCase().includes(plan)) return false;
    return true;
  });
  rows.sort((a, b) => accountRank(a) - accountRank(b));
  return rows;
}

function accountRank(a) {
  if (isLocalAccount(a)) return 0;
  if (lastAccountId && a.id === lastAccountId) return 1;
  return 2;
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

function paintUpdateStatus(st) {
  const info = $("updateInfo");
  const box = $("disableAutoUpdate");
  if (!info) return;
  if (!st || !st.ok) {
    info.textContent = st?.error || "无法检测更新设置";
    return;
  }
  if (box) box.checked = st.disableAutoUpdate !== false;
  const lines = [
    st.settingsBlocked ? "settings：已禁用自动更新" : `settings：update.mode=${st.updateMode ?? "默认"}`,
    st.innoUpdaterDisabled ? "inno_updater：已重命名禁用" : "inno_updater：仍可运行（需关 IDE 后点「立即应用」）",
    st.updaterDirBlocked ? "cursor-updater：已只读拦截" : "cursor-updater：未拦截",
  ];
  info.textContent = lines.join("\n");
}

async function refreshUpdateStatus() {
  if (!api()?.get_update_status) return;
  try {
    paintUpdateStatus(await api().get_update_status());
  } catch (e) {
    paintUpdateStatus({ ok: false, error: String(e) });
  }
}

function paintSettingsMeta(status) {
  const el = $("settingsMeta");
  if (!el) return;
  const bits = [];
  if (status?.running) bits.push("IDE开着·补丁已锁");
  else if (status?.ok) bits.push("IDE已关·可改补丁");
  const enabled = $("proxyEnabled")?.checked;
  if (enabled === false) bits.push("代理关");
  else {
    const route = $("proxyRoute")?.value === "gateway" ? "网关" : "官方";
    bits.push(route);
    const host = $("proxyHost")?.value;
    const port = $("proxyPort")?.value;
    if (host && port) bits.push(`${host}:${port}`);
  }
  if (status?.version) bits.push(`v${status.version}`);
  el.textContent = bits.join(" · ");
  syncIdeGate(Boolean(status?.running));
}

function syncIdeGate(running) {
  const gate = $("ideGate");
  const title = $("ideGateTitle");
  const hint = $("ideGateHint");
  const closeBtn = $("btnIdeGateClose");
  const nextBtn = $("btnWbNext");
  const grid = $("settingsGrid");
  const step = pendingWbNext;

  let state = running ? "locked" : "open";
  if (!running && step && step.id !== "ready" && step.id !== "launch") state = "ready";
  if (gate) gate.dataset.state = state;

  if (title) {
    if (running) title.textContent = "Cursor 还在跑 — 补丁按钮已锁";
    else if (step?.id === "ready" || step?.id === "launch") title.textContent = "日常组合已就绪";
    else if (step) title.textContent = `下一步：${step.label}`;
    else title.textContent = "Cursor 已关闭 — 可以改补丁";
  }
  if (hint) {
    if (running) {
      hint.textContent = step && step.needsClosed
        ? `要「${step.label}」：先点右边关 IDE，关掉后会自动继续。`
        : "现在只能看状态、记代理偏好。改补丁前先关 IDE。";
    } else if (step?.hint) {
      hint.textContent = step.hint;
    } else {
      hint.textContent = "灰掉的按钮现在不能按。高级危险区平时别开。";
    }
  }
  if (closeBtn) closeBtn.hidden = !running;
  if (nextBtn) {
    const showNext = !running && step && step.id !== "ready" && typeof step.run === "function";
    nextBtn.hidden = !showNext;
    if (showNext) {
      nextBtn.textContent = step.label;
      nextBtn.className = step.primary === false ? "btn" : "btn primary";
      nextBtn.disabled = false;
    }
  }
  if (grid) grid.classList.toggle("is-ide-locked", running);

  document.querySelectorAll("[data-needs-closed]").forEach((btn) => {
    if (running) {
      btn.disabled = true;
      btn.setAttribute("aria-disabled", "true");
      if (!btn.dataset.gateTitle) {
        btn.dataset.gateTitle = btn.title || "";
        btn.title = "请先关闭 IDE";
      }
    } else {
      btn.disabled = btn.classList.contains("is-blocked");
      if (btn.disabled) btn.setAttribute("aria-disabled", "true");
      else btn.removeAttribute("aria-disabled");
      if (btn.dataset.gateTitle != null) {
        btn.title = btn.dataset.gateTitle;
        delete btn.dataset.gateTitle;
      }
    }
  });

  const saveBtn = $("btnSaveProxy");
  if (saveBtn) {
    saveBtn.textContent = running ? "保存偏好（不改文件）" : "保存代理写入";
    saveBtn.title = running
      ? "IDE 开着：只写入启动器 proxy.json，不碰 Cursor"
      : "IDE 已关：会写入 settings/argv（网关原生不改 workbench）";
  }
}

/** 改补丁前总闸。autoContinue=true 时关 IDE 后返回 true，让当前操作接着做。 */
async function requireIdeClosed(actionLabel, { autoContinue = true } = {}) {
  const running = Boolean(lastCursorStatus?.running);
  if (!running) return true;
  const go = confirm(
    autoContinue
      ? `Cursor 还在运行。\n\n确定关闭 IDE，然后自动${actionLabel || "继续"}？`
      : `Cursor 还在运行，不能${actionLabel || "改补丁"}。\n\n点「确定」先关闭 IDE，再重新点一次按钮。`
  );
  if (!go) {
    toast("已取消 — 请先关 IDE 再操作");
    return false;
  }
  await closeIde({ skipConfirm: true });
  await refreshCursorStatus();
  if (lastCursorStatus?.running) {
    toast("IDE 仍在运行，请手动完全退出后再试");
    return false;
  }
  syncIdeGate(false);
  if (!autoContinue) {
    toast("IDE 已关，请再点一次刚才的按钮");
    return false;
  }
  toast(`IDE 已关，正在${actionLabel || "继续"}…`);
  return true;
}

function computeWbNext(res) {
  if (!res || !res.ok) {
    return { id: "refresh", label: "刷新诊断", hint: "诊断失败，先刷新看看。", needsClosed: false, run: () => refreshWbDiag() };
  }
  const layers = res.layers || {};
  const mu = res.modelUnlock || {};
  const ctx = res.ctxwin || {};
  const pref = (res.proxy && res.proxy.preference) || {};
  const live = (res.proxy && res.proxy.live) || {};
  const running = !!res.cursorRunning;

  if (mu.corrupted) {
    return {
      id: "repair",
      label: "修复黑屏",
      hint: "检测到异常会员补丁，先修 workbench。",
      needsClosed: true,
      run: () => repairModelUnlock(),
    };
  }
  if (!(layers.gateway > 0)) {
    return {
      id: "gateway",
      label: "去装网关插件",
      hint: "workbench 里还没有网关补丁；这步在启动器外完成。",
      needsClosed: false,
      primary: false,
      run: null,
    };
  }
  if (!mu.maxOnly && !mu.installed) {
    return {
      id: "max",
      label: "仅解锁 MAX",
      hint: "关 IDE 后点下一步，只打 hideMaxToggle。",
      needsClosed: true,
      run: () => runModelUnlock("applyMax"),
    };
  }
  if (!ctx.patched) {
    return {
      id: "ctxwin",
      label: "启用 500k",
      hint: "关 IDE 后点下一步，挂钩扩展宿主回包。",
      needsClosed: true,
      run: () => runCtxwin("apply"),
    };
  }
  if (!pref.enabled) {
    return {
      id: "proxy",
      label: running ? "保存代理偏好" : "保存并写入代理",
      hint: running
        ? "先保存偏好；真正写入要关 IDE 后再保存一次，或用启动器启动。"
        : "勾选已开代理时，保存会写 settings/argv（网关原生不改 workbench）。",
      needsClosed: false,
      run: async () => {
        if ($("proxyEnabled") && !$("proxyEnabled").checked) $("proxyEnabled").checked = true;
        if ($("proxyRoute")) $("proxyRoute").value = "gateway";
        $("btnSaveProxy")?.click();
        await refreshWbDiag();
      },
    };
  }
  if (pref.enabled && !live.argvProxyServer && !live.httpProxy && !running) {
    return {
      id: "proxy-write",
      label: "写入代理到 Cursor",
      hint: "偏好已开但文件还没写上，再保存一次。",
      needsClosed: false,
      run: async () => {
        $("btnSaveProxy")?.click();
        await refreshWbDiag();
      },
    };
  }
  return {
    id: "launch",
    label: "用启动器启动 IDE",
    hint: "网关 + MAX + 500k + 代理都齐了。以后用启动器开 Cursor。",
    needsClosed: false,
    run: () => launch(null),
  };
}

function paintWbChecklist(res) {
  const el = $("wbChecklist");
  if (!el || !res?.ok) {
    if (el) el.innerHTML = "";
    return;
  }
  const layers = res.layers || {};
  const mu = res.modelUnlock || {};
  const ctx = res.ctxwin || {};
  const pref = (res.proxy && res.proxy.preference) || {};
  const live = (res.proxy && res.proxy.live) || {};
  const step = pendingWbNext;

  const items = [
    {
      id: "gateway",
      ok: layers.gateway > 0,
      label: "网关原生",
      meta: layers.gateway > 0 ? `${layers.gateway} 处补丁` : "未检测到",
    },
    {
      id: "max",
      ok: !!(mu.maxOnly || (mu.installed && !mu.corrupted)),
      warn: !!mu.corrupted,
      label: "MAX 开关",
      meta: mu.corrupted ? "异常，需修复" : (mu.maxOnly ? "仅 MAX 已开" : (mu.installed ? "已解锁" : "未开")),
    },
    {
      id: "ctxwin",
      ok: !!ctx.patched,
      label: "500k 回包",
      meta: ctx.patched ? "已启用" : "未启用",
    },
    {
      id: "proxy",
      ok: !!pref.enabled && !pref.bypass_gateway,
      warn: !!pref.enabled && !!pref.bypass_gateway,
      label: "代理",
      meta: pref.enabled
        ? (pref.bypass_gateway ? "改回官方（危险）" : (live.argvProxyServer || live.httpProxy ? "网关原生 · 已写入" : "网关原生 · 仅偏好"))
        : (live.argvProxyServer ? "argv 有残留" : "未开"),
    },
  ];

  el.innerHTML = items.map((it) => {
    const tone = it.warn ? "critical" : (it.ok ? "ok" : "warn");
    const mark = it.warn ? "!" : (it.ok ? "✓" : "○");
    const isNext = step && (
      (step.id === "gateway" && it.id === "gateway") ||
      (step.id === "max" && it.id === "max") ||
      (step.id === "ctxwin" && it.id === "ctxwin") ||
      ((step.id === "proxy" || step.id === "proxy-write") && it.id === "proxy") ||
      (step.id === "repair" && it.id === "max")
    );
    return `<li class="wb-check ${tone}${isNext ? " is-next" : ""}"><span class="mark">${mark}</span><span>${it.label}</span><span class="meta">${it.meta}</span></li>`;
  }).join("");
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
  if (res.lastAccountId) lastAccountId = res.lastAccountId;
  const pill = $("loginPill");
  if (!res.ok) {
    pill.textContent = "未检测到 Cursor";
    pill.classList.remove("ok");
    pill.title = res.error || "请设置 Cursor 路径";
    if ($("cursorInfo")) $("cursorInfo").textContent = res.error || "请设置 Cursor 路径";
    paintSettingsMeta(res);
    if (opts.ctxwin) refreshCtxwin();
    if (opts.modelUnlock) refreshModelUnlock();
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
  if (lastWbDiag?.ok) {
    lastWbDiag = { ...lastWbDiag, cursorRunning: !!res.running };
    pendingWbNext = computeWbNext(lastWbDiag);
    paintWbChecklist(lastWbDiag);
    const hint = $("wbNextHint");
    if (hint && pendingWbNext) {
      hint.textContent = res.running && pendingWbNext.needsClosed
        ? `卡在「${pendingWbNext.label}」— 先关 IDE`
        : (pendingWbNext.hint || pendingWbNext.label);
    }
    syncIdeGate(!!res.running);
  }
  if (opts.ctxwin) refreshCtxwin();
  if (opts.modelUnlock) refreshModelUnlock();
  if (opts.update !== false) refreshUpdateStatus();
  maybePaintLocalCards();
}

function formatProxyStatus(res) {
  const st = res.processProxyStatus || {};
  const patch = res.patchStatus || {};
  const bak = res.proxyBackup || {};
  const route = $("proxyRoute")?.value;
  const lines = [
    `网关补丁：${patch.patched ? "有" : "无"}${patch.hits ? `（${patch.hits} 处）` : ""}${patch.hasBackup ? " · 有备份可还原" : ""}`,
    `进程 DLL：${st.installed ? "已写入" : "未写入"}${st.hasBackup ? " · 有备份可还原" : ""}`,
    `代理快照：${bak.hasBackup ? `有（可一键还原）${bak.savedAt ? " · " + String(bak.savedAt).slice(0, 19) : ""}` : "无（成功写入后才会生成）"}`,
  ];
  if (res.cursorRunning) {
    lines.push("Cursor 开着：点保存只记偏好，不改 Cursor 文件");
  }
  if (route === "gateway" && !patch.patched && !patch.hasBackup) {
    lines.push("⚠ 没检测到补丁：请先在网关插件里打补丁，或改选「没打网关补丁」");
  } else if (route === "clash" && patch.patched) {
    lines.push("保存后会改回官方 API（去掉 43111 路由）——易搞坏，慎用");
  } else if (route === "gateway") {
    lines.push("网关原生：不改 workbench；启动时由启动器带代理参数");
  } else {
    lines.push("保存前会确认；写入前自动备份");
  }
  if (st.installed) lines.push("若黑屏：点「一键还原误触」或「删除 DLL」");
  else if (bak.hasBackup) lines.push("误触了就点「一键还原误触」");
  else lines.push("进程 DLL 非必要别写（有闪退风险）");
  return lines.join("\n");
}

async function loadProxy() {
  const res = await api().get_proxy();
  const cfg = res.saved || {};
  $("proxyEnabled").checked = cfg.enabled === true || cfg.enabled === "true";
  if ($("proxyRoute")) {
    const clash = cfg.bypass_gateway !== false && cfg.bypassGateway !== false;
    $("proxyRoute").value = clash ? "clash" : "gateway";
  }
  $("proxyType").value = cfg.proxy_type || cfg.proxyType || "socks5";
  $("proxyHost").value = cfg.host || "127.0.0.1";
  $("proxyPort").value = cfg.port || 7891;
  if ($("proxyDetectInfo")) $("proxyDetectInfo").textContent = formatProxyStatus(res);
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
    res.patched ? "状态：已启用回包改写（500k）" : "状态：未启用（官方 256k）",
    `覆盖：AvailableModels + GetServerConfig + Agent · ${res.from || 256000} → ${res.to || 500000}`,
    res.version ? `Cursor v${res.version}` : "",
    res.running ? "IDE 正在运行，改文件前请先关闭" : "IDE 未运行，可以改文件",
    res.node ? `Node ${res.node}` : "未找到 Node.js，无法启用",
  ].filter(Boolean);
  info.textContent = lines.join("\n");
  if (applyBtn) {
    applyBtn.classList.toggle("is-blocked", !res.canApply);
    applyBtn.title = res.running
      ? "请先关闭 IDE"
      : (!res.node ? "需要本机 Node.js" : "挂钩扩展宿主，改写模型目录与配置回包");
  }
  if (restoreBtn) {
    restoreBtn.classList.toggle("is-blocked", !res.canRestore);
    restoreBtn.title = res.patched ? "去掉挂钩，回到官方响应" : "当前没有补丁";
  }
  syncIdeGate(Boolean(lastCursorStatus?.running || res.running));
}

async function refreshCtxwin() {
  if (!api()?.ctxwin_status) return;
  try {
    paintCtxwin(await api().ctxwin_status());
  } catch (e) {
    paintCtxwin({ ok: false, error: String(e) });
  }
}

function _wbChip(label, tone) {
  return `<span class="wb-chip ${tone || "info"}">${label}</span>`;
}

function paintWbDiag(res) {
  const chips = $("wbDiagChips");
  const recs = $("wbDiagRecs");
  const info = $("wbDiagInfo");
  const hint = $("wbNextHint");
  const fix500 = $("btnWbDiagFix500k");
  const restoreBtn = $("btnWbDiagRestore");
  if (!info) return;

  lastWbDiag = res;
  if (!res || !res.ok) {
    pendingWbNext = computeWbNext(res);
    paintWbChecklist(null);
    if (chips) chips.innerHTML = _wbChip("诊断失败", "critical");
    if (recs) recs.innerHTML = "";
    if (hint) hint.textContent = res?.error || "无法读取诊断，点刷新重试";
    info.textContent = res?.error || "无法读取诊断";
    syncIdeGate(Boolean(lastCursorStatus?.running));
    return;
  }

  pendingWbNext = computeWbNext(res);
  paintWbChecklist(res);
  if (hint) {
    const step = pendingWbNext;
    if (res.cursorRunning && step?.needsClosed) {
      hint.textContent = `卡在「${step.label}」— 先关 IDE，关掉后点顶栏「${step.label}」或会自动继续。`;
    } else if (step?.id === "launch") {
      hint.textContent = "四项都齐了。用启动器开 Cursor 即可。";
    } else if (step) {
      hint.textContent = step.hint || `下一步：${step.label}`;
    }
  }

  const layers = res.layers || {};
  const mu = res.modelUnlock || {};
  const ctx = res.ctxwin || {};
  const pref = (res.proxy && res.proxy.preference) || {};
  const live = (res.proxy && res.proxy.live) || {};

  if (chips) {
    const bits = [];
    bits.push(_wbChip(res.healthy ? "健康" : "需处理", res.healthy ? "ok" : "warn"));
    bits.push(_wbChip(res.cursorRunning ? "IDE 运行中" : "IDE 已关", res.cursorRunning ? "info" : "ok"));
    bits.push(_wbChip(layers.gateway > 0 ? `网关×${layers.gateway}` : "无网关", layers.gateway > 0 ? "ok" : "warn"));
    bits.push(_wbChip(mu.maxOnly ? "仅 MAX" : (mu.installed ? "完整解锁" : "无 MAX"), mu.corrupted ? "critical" : (mu.maxOnly || mu.installed ? "ok" : "warn")));
    bits.push(_wbChip(ctx.patched ? "500k" : "无 500k", ctx.patched ? "ok" : "warn"));
    bits.push(_wbChip(pref.enabled ? (pref.bypass_gateway ? "代理·官方" : "代理·原生") : (live.argvProxyServer ? "argv残留" : "代理关"), pref.enabled && !pref.bypass_gateway ? "ok" : "info"));
    chips.innerHTML = bits.join("");
  }

  if (recs) {
    const list = res.recommendations || [];
    recs.innerHTML = list.map((r) => {
      const sev = r.severity || "info";
      const detail = r.detail ? `<small>${r.detail}</small>` : "";
      return `<li class="wb-diag-rec ${sev}"><strong>${r.title || ""}</strong>${r.action || ""}${detail ? "<br>" + detail : ""}</li>`;
    }).join("");
  }

  if (fix500) {
    fix500.hidden = !!ctx.patched;
    fix500.classList.toggle("is-blocked", !!ctx.patched || !!res.cursorRunning);
    fix500.title = ctx.patched ? "500k 已启用" : (res.cursorRunning ? "请先关闭 IDE" : "启用回包改写");
  }
  if (restoreBtn) {
    restoreBtn.classList.toggle("is-blocked", !!res.cursorRunning);
    restoreBtn.title = res.cursorRunning ? "请先关闭 IDE" : "从统一备份还原 workbench";
  }

  const bak = res.backup || {};
  info.textContent = [
    `v${res.version || "?"} · ${res.installRoot || ""}`,
    `备份：official=${bak.hasOfficial ? "有" : "无"} · 快照×${bak.snapshotCount || 0}`,
    bak.hasLegacyBajie ? "legacy bajie 备份可用" : "",
  ].filter(Boolean).join("\n");
  syncIdeGate(Boolean(lastCursorStatus?.running || res.cursorRunning));
}

async function runWbNext() {
  const step = pendingWbNext;
  if (!step) return refreshWbDiag();
  if (step.id === "gateway") {
    return toast("请在启动器外安装/确认网关插件补丁");
  }
  if (typeof step.run !== "function") {
    return toast(step.hint || "没有可执行的下一步");
  }
  if (step.needsClosed && !(await requireIdeClosed(step.label))) return;
  await step.run();
  await refreshWbDiag();
}

async function refreshWbDiag() {
  if (!api()?.workbench_diagnostic) return;
  const info = $("wbDiagInfo");
  if (info) info.textContent = "正在扫描…";
  try {
    const res = await api().workbench_diagnostic();
    paintWbDiag(res);
    paintHealthBanner(res);
  } catch (e) {
    paintWbDiag({ ok: false, error: String(e) });
    paintHealthBanner({ ok: false, error: String(e) });
  }
  refreshLauncherUpdate();
}

function paintHealthBanner(res) {
  const banner = $("healthBanner");
  const title = $("healthTitle");
  const hint = $("healthHint");
  const fixBtn = $("btnAutofix");
  if (!banner) return;
  banner.hidden = false;
  if (!res?.ok) {
    banner.dataset.state = "critical";
    if (title) title.textContent = "补丁自检失败";
    if (hint) hint.textContent = res?.error || "无法诊断";
    if (fixBtn) fixBtn.hidden = true;
    return;
  }
  const af = res.autofix || {};
  const steps = (af.steps || []).filter((s) => !s.manual);
  const upgrade = res.cursorUpgrade || {};
  let state = "ok";
  if (res.modelUnlock?.corrupted) state = "critical";
  else if (!af.ready || upgrade.needsRepatch) state = "warn";
  banner.dataset.state = state;

  if (title) {
    if (af.ready && !upgrade.needsRepatch) {
      title.textContent = `补丁就绪 · Cursor v${res.version || "?"} · 启动器 v${res.launcherVersion || "?"}`;
    } else if (upgrade.needsRepatch) {
      title.textContent = `Cursor 已升级到 v${res.version} — 建议重打补丁`;
    } else {
      title.textContent = `待补齐 ${steps.length} 项`;
    }
  }
  if (hint) {
    if (af.ready && !upgrade.needsRepatch) {
      hint.textContent = res.profile || "网关原生 + MAX + 500k + 代理";
    } else {
      const labels = steps.map((s) => s.label).join(" → ");
      hint.textContent = (labels || "有事项待处理") + (res.cursorRunning ? "（需先关 IDE）" : "");
    }
  }
  if (fixBtn) {
    const need = steps.length > 0 || upgrade.needsRepatch;
    fixBtn.hidden = !need;
    fixBtn.textContent = res.cursorRunning ? "关 IDE 并一键补齐" : "一键补齐";
    fixBtn.disabled = false;
  }
}

async function runAutofix() {
  if (!api()?.patch_autofix) return toast("当前版本不支持一键补齐");
  const running = !!lastCursorStatus?.running;
  const tip = running
    ? "将关闭 Cursor，然后自动：仅 MAX → 500k → 网关原生代理写入。\n确定？"
    : "将自动补齐：仅 MAX → 500k → 网关原生代理写入。\n确定？";
  if (!confirm(tip)) return;
  toast(running ? "正在关 IDE 并补齐…" : "正在一键补齐…");
  const res = await api().patch_autofix(running);
  toast(res.ok ? (res.message || "已补齐") : (res.error || res.message || "补齐失败"));
  await refreshWbDiag();
  await refreshCtxwin();
  await refreshModelUnlock();
  await loadProxy();
}

async function refreshLauncherUpdate() {
  const link = $("btnLauncherUpdate");
  if (!link || !api()?.check_launcher_update) return;
  link.hidden = true;
  try {
    const res = await api().check_launcher_update();
    // 仅当远端明确更新时显示；已是最新或网络失败都隐藏
    if (res?.ok && res.newer && res.latest && res.url) {
      link.hidden = false;
      link.href = res.url;
      link.textContent = `启动器有更新 v${res.latest}`;
      link.title = `当前 v${res.current || "?"} → GitHub v${res.latest}（点开下载）`;
    }
  } catch {
    link.hidden = true;
  }
}

async function runWbDiagFix500k() {
  if (!api()?.ctxwin_apply) return;
  await runCtxwin("apply");
  await refreshWbDiag();
  await refreshCtxwin();
}

async function runWbDiagRestore() {
  if (!api()?.restore_workbench_unified) return;
  if (!(await requireIdeClosed("还原 workbench"))) return;
  if (!confirm("将从统一备份还原 workbench（优先 official 基线）。确定？")) return;
  const info = $("wbDiagInfo");
  if (info) info.textContent = "正在还原 workbench…";
  try {
    const res = await api().restore_workbench_unified("auto");
    if (!res.ok) {
      toast(res.error || "还原失败");
      paintWbDiag(await api().workbench_diagnostic());
      return;
    }
    toast(res.message || "已还原 workbench");
    await refreshWbDiag();
    await refreshModelUnlock();
  } catch (e) {
    toast(String(e));
  }
}

async function runCtxwin(kind) {
  if (!(await requireIdeClosed(kind === "restore" ? "还原回包改写" : "启用回包改写"))) return;
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
  if (info) info.textContent = kind === "restore" ? "正在还原…" : "正在启用回包改写…";
  const res = await api()[fn]();
  paintCtxwin(res);
  if (!res.ok) return toast(res.error || "失败");
  if (res.skipped) return toast(res.message || "无需还原");
  toast(kind === "restore" ? "已还原官方回包，请再启动 IDE" : "已启用回包改写，请再启动 IDE");
  refreshWbDiag();
}

function paintModelUnlock(res) {
  const info = $("modelUnlockInfo");
  const applyBtn = $("btnModelUnlockApply");
  const applyMaxBtn = $("btnModelUnlockApplyMax");
  const restoreBtn = $("btnModelUnlockRestore");
  const repairBtn = $("btnModelUnlockRepair");
  const syncBtn = $("btnModelUnlockSyncStorage");
  const select = $("modelUnlockMembership");
  if (!info) return;
  if (!res || !res.ok) {
    info.textContent = res?.error || "无法检测解锁状态";
    if (applyBtn) applyBtn.classList.add("is-blocked");
    if (applyMaxBtn) applyMaxBtn.classList.add("is-blocked");
    if (restoreBtn) restoreBtn.classList.add("is-blocked");
    if (syncBtn) syncBtn.classList.add("is-blocked");
    if (repairBtn) repairBtn.classList.add("is-blocked");
    return;
  }
  if (select && res.membershipLevel && select.value !== res.membershipLevel) {
    select.value = res.membershipLevel;
  }
  const hits = res.hits || {};
  const maxReady = (hits.showMax || 0) > 0;
  const storage = res.storageMembership || {};
  const storageLine = storage.ok
    ? `本地缓存：stripe=${storage.stripeMembershipType || "—"} · 侧边栏=${storage.applicationUserMembershipType || "—"}`
    : "";
  const lines = [
    maxReady
      ? "状态：MAX 开关已解锁"
      : (res.installed ? "状态：部分解锁，请点「仅解锁 MAX」" : "状态：无 MAX 开关（token 计价会被 hideMaxToggle 藏掉）"),
    `命中：FREE×${hits.modelLock || 0} · 显示MAX×${hits.showMax || 0} · 命名视图×${hits.namedView || 0} · 目录×${hits.catalog || 0} · 绑卡×${hits.maxMode || 0} · 会员×${hits.memPro || 0} · fetch×${hits.fetchSpoof || 0}`,
    storageLine,
    res.version ? `Cursor v${res.version}` : "",
    res.running ? "IDE 正在运行，改文件前请先关闭" : "IDE 未运行，可以改文件",
  ].filter(Boolean);
  if (res.message && res.ok) lines.push(res.message);
  info.textContent = lines.join("\n");
  if (applyBtn) {
    applyBtn.classList.toggle("is-blocked", !res.can_apply);
    applyBtn.title = res.running ? "请先关闭 IDE" : "FREE 锁 + 会员 fetch + MAX + 命名视图（改动较多）";
  }
  if (applyMaxBtn) {
    applyMaxBtn.classList.toggle("is-blocked", !res.can_apply);
    applyMaxBtn.title = res.running ? "请先关闭 IDE" : "只显示 MAX 开关（推荐，改动最小）";
  }
  if (restoreBtn) {
    restoreBtn.classList.toggle("is-blocked", !res.can_restore);
    restoreBtn.title = res.installed ? "去掉本启动器的解锁标记" : "当前没有解锁补丁";
  }
  if (syncBtn) {
    syncBtn.classList.toggle("is-blocked", !res.canSyncStorage);
    syncBtn.title = res.running ? "请先关闭 IDE" : "只改 state.vscdb 里的套餐显示，不重打补丁";
  }
  if (repairBtn) {
    repairBtn.classList.toggle("is-blocked", !res.canRepair);
    repairBtn.title = res.running
      ? "请先关闭 IDE"
      : (res.corrupted ? "会员补丁打坏 workbench 导致黑屏" : "从备份还原 workbench");
  }
  syncIdeGate(Boolean(lastCursorStatus?.running || res.running));
}

async function saveModelUnlockMembership() {
  const select = $("modelUnlockMembership");
  if (!select || !api()?.model_unlock_set_membership) return;
  try {
    paintModelUnlock(await api().model_unlock_set_membership(select.value));
  } catch (e) {
    toast(String(e));
  }
}

async function syncModelUnlockStorage() {
  const select = $("modelUnlockMembership");
  const level = select?.value || "pro";
  if (!api()?.model_unlock_sync_storage) return;
  if (!(await requireIdeClosed("修正侧边栏显示"))) return;
  const status = await api().model_unlock_status();
  if (!status.canSyncStorage) {
    paintModelUnlock(status);
    return toast(status.running ? "请先关闭 IDE" : (status.error || "当前不能修正"));
  }
  const info = $("modelUnlockInfo");
  if (info) info.textContent = "正在写入侧边栏套餐…";
  const res = await api().model_unlock_sync_storage(level);
  paintModelUnlock(await api().model_unlock_status());
  if (!res.ok) return toast(res.error || "失败");
  toast(res.message || "已修正侧边栏显示");
}

async function repairModelUnlock() {
  if (!api()?.model_unlock_repair) return;
  if (!(await requireIdeClosed("修复黑屏"))) return;
  const status = await api().model_unlock_status();
  if (!status.canRepair) {
    paintModelUnlock(status);
    return toast(status.running ? "请先关闭 IDE" : (status.error || "当前不能修复"));
  }
  const info = $("modelUnlockInfo");
  if (info) info.textContent = "正在从备份还原 workbench…";
  const res = await api().model_unlock_repair();
  paintModelUnlock(await api().model_unlock_status());
  if (!res.ok) return toast(res.error || "失败");
  toast(res.message || "已修复，请再启动 IDE");
}

async function refreshModelUnlock() {
  if (!api()?.model_unlock_status) return;
  try {
    paintModelUnlock(await api().model_unlock_status());
  } catch (e) {
    paintModelUnlock({ ok: false, error: String(e) });
  }
}

async function runModelUnlock(kind) {
  if (!(await requireIdeClosed(kind === "restore" ? "还原模型解锁" : (kind === "applyMax" ? "解锁 MAX" : "完整解锁")))) return;
  const status = await api().model_unlock_status();
  if (kind === "apply" && !status.can_apply) {
    paintModelUnlock(status);
    return toast(status.running ? "请先关闭 IDE" : (status.error || "当前不能解锁"));
  }
  if (kind === "applyMax" && !status.can_apply) {
    paintModelUnlock(status);
    return toast(status.running ? "请先关闭 IDE" : (status.error || "当前不能解锁 MAX"));
  }
  if (kind === "restore" && !status.can_restore) {
    paintModelUnlock(status);
    return toast(status.installed ? (status.running ? "请先关闭 IDE" : "无法还原") : "当前没有解锁补丁");
  }
  const select = $("modelUnlockMembership");
  if (kind === "apply" && select && api()?.model_unlock_set_membership) {
    await api().model_unlock_set_membership(select.value);
  }
  const fn = kind === "restore" ? "model_unlock_restore" : "model_unlock_apply";
  const info = $("modelUnlockInfo");
  if (info) {
    info.textContent = kind === "restore" ? "正在还原…" : (kind === "applyMax" ? "正在解锁 MAX…" : "正在完整解锁…");
  }
  const res =
    kind === "applyMax"
      ? await api().model_unlock_apply(null, true)
      : await api()[fn](kind === "apply" ? select?.value : undefined);
  paintModelUnlock(res);
  if (!res.ok) return toast(res.error || "失败");
  if (res.skipped) return toast(res.message || "无需还原");
  toast(
    kind === "restore"
      ? "已还原，请再启动 IDE"
      : kind === "applyMax"
        ? "已解锁 MAX，请再启动 IDE"
        : "已完整解锁，请再启动 IDE",
  );
  refreshWbDiag();
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
  if (res.ok && res.processProxy?.removed) toast("已卸掉残留的 version.dll");
  if (res.ok && accountId) lastAccountId = accountId;
  await refreshCursorStatus();
}

async function closeIde(opts = {}) {
  const skipConfirm = Boolean(opts.skipConfirm);
  if (!skipConfirm && !confirm("关闭 Cursor 以腾出内存？账号仍留在启动器里。")) return { ok: false, cancelled: true };
  toast("正在关闭 IDE…");
  const res = await api().close_ide();
  toast(res.ok ? (res.closed ? "已关闭 Cursor" : "Cursor 本来就没在运行") : (res.error || "关闭失败"));
  await refreshCursorStatus();
  return res;
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
  }, 8000);
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
      toast(`已填入 ${rec.proxy_type}://${rec.host}:${rec.port}${ms}，请点「保存」`);
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
  const enabled = $("proxyEnabled")?.checked;
  const clash = $("proxyRoute")?.value !== "gateway";
  if (enabled) {
    const tip = clash
      ? "将写入 settings/argv，并改写 Cursor 的 workbench（风险高）。\n写入前会自动备份，可用「一键还原误触」撤回。\n\n确定继续？"
      : "将在 Cursor 已关闭时写入 settings/argv（网关补丁不动）。\n写入前会自动备份，可用「一键还原误触」撤回。\n\n若 Cursor 仍在运行，则只记偏好、不改文件。\n\n确定保存？";
    if (!window.confirm(tip)) return;
  }
  if (clash && enabled) {
    const ok = window.confirm(
      "再次确认：你选的是「改回官方 API」，会改安装目录里的 workbench。\n用网关补丁请改选「网关原生」。\n\n仍然继续？"
    );
    if (!ok) return;
  }
  const res = await api().save_proxy({
    enabled: !!enabled,
    bypass_gateway: clash,
    process_hook: false,
    proxy_type: $("proxyType").value,
    host: $("proxyHost").value,
    port: Number($("proxyPort").value || 7891),
    strict_ssl: false,
  });
  if (!res.ok) {
    toast(res.error || "失败");
  } else if (res.deferred || res.filesWritten === false) {
    toast(res.message || "已记住设置；请先关 IDE，再用启动器启动");
  } else if (res.route?.changed || res.route?.hits) {
    toast(`已保存 · 已改回官方 API（${res.route.hits || 0} 处）· 可用一键还原`);
  } else {
    toast(res.message || "已保存（已备份，可一键还原）");
  }
  await loadProxy();
  paintSettingsMeta(lastCursorStatus);
};

if ($("btnUndoProxy")) {
  $("btnUndoProxy").onclick = async () => {
    const ok = window.confirm(
      "一键还原误触将：\n" +
        "1. 还原 settings/argv 快照\n" +
        "2. 尽量恢复 workbench 网关补丁备份\n" +
        "3. 删除 version.dll（若有）\n" +
        "4. 关闭启动器里的代理开关\n\n" +
        "会先关闭正在运行的 Cursor。确定？"
    );
    if (!ok) return;
    toast("正在还原…");
    try {
      const res = await api().undo_proxy_injection();
      toast(res.ok ? (res.message || "已还原") : (res.error || "还原失败"));
      if ($("proxyEnabled")) $("proxyEnabled").checked = false;
      await loadProxy();
      await refreshCursorStatus();
    } catch (e) {
      toast("还原失败：" + String(e));
    }
  };
}

$("proxyRoute")?.addEventListener("change", async () => {
  paintSettingsMeta(lastCursorStatus);
  try {
    const res = await api().get_proxy();
    if ($("proxyDetectInfo")) $("proxyDetectInfo").textContent = formatProxyStatus(res);
  } catch {}
});

async function runDll(fnName, waitText, okText) {
  if (!(await requireIdeClosed("操作 DLL / 补丁文件"))) return;
  toast(waitText);
  const res = await api()[fnName]();
  toast(res.ok ? (res.message || okText) : (res.error || "失败"));
  await loadProxy();
  await refreshCursorStatus();
}
if ($("btnDllInstall")) $("btnDllInstall").onclick = async () => {
  const ok = window.confirm(
    "写入 version.dll 极易导致 Cursor 闪退/黑屏，往往只能重装恢复。\n\n确定仍要写入？"
  );
  if (!ok) return;
  return runDll("install_process_proxy", "正在写入 DLL…", "已写入");
};
if ($("btnDllRemove")) $("btnDllRemove").onclick = () => runDll("uninstall_process_proxy", "正在删除 DLL（会备份）…", "已删除");
if ($("btnDllRestore")) $("btnDllRestore").onclick = () => runDll("restore_process_proxy_files", "正在还原 DLL…", "已还原");
if ($("btnWorkbenchRestore")) $("btnWorkbenchRestore").onclick = () => runDll("restore_workbench", "正在还原 workbench 备份…", "已还原补丁");
if ($("btnRecoverCursor")) $("btnRecoverCursor").onclick = () => runDll("uninstall_process_proxy", "正在删除 DLL…", "已删除");
$("btnSavePath").onclick = async () => {
  const res = await api().set_cursor_path($("cursorPath").value);
  toast(res.ok ? "路径已保存" : (res.error || "失败"));
  await refreshCursorStatus({ ctxwin: true, modelUnlock: true, update: true });
};
if ($("btnApplyDisableUpdate")) {
  $("btnApplyDisableUpdate").onclick = async () => {
    toast("正在禁用自动更新…");
    const res = await api().apply_disable_updates();
    if (!res.ok) return toast(res.error || "失败");
    toast("已禁用自动更新");
    await refreshUpdateStatus();
  };
}
if ($("btnRestoreUpdate")) {
  $("btnRestoreUpdate").onclick = async () => {
    if (!confirm("恢复后 Cursor 可能再次自动升级并覆盖补丁，确定？")) return;
    const res = await api().restore_updates();
    toast(res.ok ? "已恢复自动更新" : (res.error || "失败"));
    await refreshUpdateStatus();
  };
}
if ($("disableAutoUpdate")) {
  $("disableAutoUpdate").onchange = async () => {
    if ($("disableAutoUpdate").checked) {
      await refreshUpdateStatus();
      return;
    }
    if (!confirm("取消勾选不会自动恢复更新器，需点「恢复更新」。继续？")) {
      $("disableAutoUpdate").checked = true;
    }
  };
}
$("btnCtxwinApply").onclick = () => runCtxwin("apply");
$("btnCtxwinRestore").onclick = () => runCtxwin("restore");
$("btnCtxwinRefresh").onclick = () => refreshCtxwin();
if ($("btnWbDiagRefresh")) $("btnWbDiagRefresh").onclick = () => refreshWbDiag();
if ($("btnHealthRefresh")) $("btnHealthRefresh").onclick = () => refreshWbDiag();
if ($("btnAutofix")) $("btnAutofix").onclick = () => runAutofix();
if ($("btnWbDiagFix500k")) $("btnWbDiagFix500k").onclick = () => runWbDiagFix500k();
if ($("btnWbDiagRestore")) $("btnWbDiagRestore").onclick = () => runWbDiagRestore();
if ($("btnIdeGateClose")) {
  $("btnIdeGateClose").onclick = async () => {
    const step = pendingWbNext;
    await closeIde();
    await refreshWbDiag();
    if (!lastCursorStatus?.running && step?.needsClosed && typeof step.run === "function") {
      if (confirm(`IDE 已关。现在执行「${step.label}」？`)) {
        await step.run();
        await refreshWbDiag();
      }
    }
  };
}
if ($("btnWbNext")) $("btnWbNext").onclick = () => runWbNext();
$("btnModelUnlockApplyMax").onclick = () => runModelUnlock("applyMax");
$("btnModelUnlockApply").onclick = () => runModelUnlock("apply");
$("btnModelUnlockRestore").onclick = () => runModelUnlock("restore");
$("btnModelUnlockSyncStorage").onclick = () => syncModelUnlockStorage();
$("btnModelUnlockRepair").onclick = () => repairModelUnlock();
$("btnModelUnlockRefresh").onclick = () => refreshModelUnlock();
$("modelUnlockMembership")?.addEventListener("change", () => saveModelUnlockMembership());
$("btnShortcutDesktop").onclick = () => createChosenShortcuts(true, false);
$("btnShortcutStart").onclick = () => createChosenShortcuts(false, true);
$("btnShortcutSkip").onclick = async () => {
  try { await api().skip_shortcut_prompt(); } catch {}
  $("shortcutDialog")?.close();
};
$("btnShortcutCreate").onclick = async () => {
  const desktop = $("scPromptDesktop")?.checked;
  const startMenu = $("scPromptStart")?.checked;
  if (!desktop && !startMenu) {
    toast("请至少选一项");
    return;
  }
  const res = await createChosenShortcuts(desktop, startMenu);
  if (res?.ok) $("shortcutDialog")?.close();
};
$("shortcutDialog")?.addEventListener("cancel", () => {
  try { api()?.skip_shortcut_prompt(); } catch {}
});
document.querySelector(".settings-fold")?.addEventListener("toggle", (ev) => {
  if (ev.target.open) {
    refreshWbDiag();
    refreshCtxwin();
    refreshShortcutStatus();
    refreshUpdateStatus();
  }
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

function shortcutLabel(st) {
  const bits = [];
  if (st.hasDesktop) bits.push("桌面已有");
  if (st.hasStartMenu) bits.push("开始菜单已有");
  return bits.length ? bits.join(" · ") : "还没有快捷方式";
}

async function refreshShortcutStatus() {
  const panel = $("shortcutPanel");
  const info = $("shortcutInfo");
  if (!panel || !api()?.shortcut_status) return;
  try {
    const st = await api().shortcut_status();
    if (!st?.canCreate) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    if (info) info.textContent = st.error ? st.error : shortcutLabel(st);
    const desk = $("btnShortcutDesktop");
    const start = $("btnShortcutStart");
    if (desk) desk.disabled = !!st.hasDesktop;
    if (start) start.disabled = !!st.hasStartMenu;
  } catch {
    panel.hidden = true;
  }
}

async function createChosenShortcuts(desktop, startMenu) {
  const fn = api()?.create_shortcuts;
  if (!fn) return { ok: false, error: "API 未就绪" };
  const res = await fn(!!desktop, !!startMenu);
  toast(res.ok ? (res.message || "已创建") : (res.error || "失败"));
  await refreshShortcutStatus();
  return res;
}

async function maybePromptShortcuts() {
  if (!api()?.shortcut_status) return;
  try {
    const st = await api().shortcut_status();
    await refreshShortcutStatus();
    if (!st?.canCreate || st.prompted || st.hasDesktop || st.hasStartMenu) return;
    const dlg = $("shortcutDialog");
    if (dlg && !dlg.open) dlg.showModal();
  } catch {}
}

$("proxyEnabled")?.addEventListener("change", () => paintSettingsMeta(lastCursorStatus));

async function boot() {
  if (!api()) {
    const pill = $("loginPill");
    if (pill && boot._tries > 40) pill.textContent = "API 未就绪";
    boot._tries = (boot._tries || 0) + 1;
    return setTimeout(boot, 120);
  }
  try {
    await Promise.all([refreshCursorStatus({ ctxwin: true, modelUnlock: true }), loadProxy(), renderAccounts()]);
    paintSettingsMeta(lastCursorStatus);
    startStatusWatch();
    await maybePromptShortcuts();
    refreshWbDiag();
    refreshLauncherUpdate();
  } catch (e) {
    const pill = $("loginPill");
    if (pill) pill.textContent = "启动失败";
    toast("界面初始化失败：" + String(e));
  }
}
boot._tries = 0;
boot();
