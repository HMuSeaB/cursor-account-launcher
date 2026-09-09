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
  const apiKey = String(a?.apiKey || "").trim();
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
    <div class="token-block">
      <div class="progress-head">
        <strong>Agent API Key</strong>
        <span class="hint">${apiKey ? "已保存" : "未保存"}</span>
      </div>
      <input id="detailApiKey" class="token-box" type="password" spellcheck="false" value="${esc(apiKey)}" placeholder="crsr_…" />
      <p class="hint token-hint">用于 Cursor Agent CLI（与 IDE 登录 Token 不同）。保存后可点卡片「CLI」一键启动。</p>
      <div class="guard-actions" style="margin-top:8px">
        <button type="button" class="btn" id="btnSaveApiKey">保存 API Key</button>
        <button type="button" class="btn primary" id="btnLaunchCliDetail">启动 CLI</button>
      </div>
    </div>
  </div>`;
}

function machineDetailSection(a) {
  const ids = a.deviceIds || {};
  const full = String(ids.serviceMachineId || ids.machineId || ids.telemetryMachineId || "").trim();
  const short = a.machineIdShort || full.replace(/[-{}]/g, "").slice(0, 12);
  let status = "尚未绑定。下次切换此号时会写入当时的本机指纹。";
  if (full) {
    status = a.machineMatch ? "与本机当前机器码一致" : "与本机当前机器码不一致（切到此号才会写回绑定值）";
  }
  return `<div class="detail-section">
    <div class="progress-head">
      <strong>机器码</strong>
      ${full ? `<button type="button" class="copy-link" data-copy="${esc(full)}">复制全文</button>` : ""}
    </div>
    <p class="hint" style="margin:6px 0 10px">${full ? `<span class="tag machine">${esc(short)}</span> ` : ""}${esc(status)}</p>
    <div class="guard-actions">
      <button type="button" class="btn" id="btnRotateMachine">更换机器码</button>
    </div>
    <p class="hint">更换会生成新 Desktop 指纹并绑到此账号。本机正在用这个号时需先关 IDE。</p>
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
  if (localIdentity.userId) return a.id === localIdentity.userId;
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
    cli: '<path d="M4 7l6 5-6 5"/><path d="M12 17h8"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/>',
    more: '<circle cx="12" cy="12" r="1.5" fill="currentColor"/><circle cx="6" cy="12" r="1.5" fill="currentColor"/><circle cx="18" cy="12" r="1.5" fill="currentColor"/>',
    launch: '<polygon points="8 5 19 12 8 19 8 5" fill="currentColor" stroke="none"/>',
    switch: '<path d="M8 3L4 7l4 4"/><path d="M4 7h16"/><path d="M16 21l4-4-4-4"/><path d="M20 17H4"/>',
  };
  return `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ""}</svg>`;
}

function renderAccountCard(a) {
  const email = displayEmail(a);
  const initial = (email[0] || "?").toUpperCase();
  const mClass = membershipClass(a.membershipType);
  const local = isLocalAccount(a);
  const badges = [];
  if (local) badges.push('<span class="tag local">本机</span>');
  badges.push(`<span class="tag ${mClass}">${esc(membershipLabel(a.membershipType))}</span>`);
  if (hasWsToken(a)) {
    badges.push('<span class="tag pro" title="完整 WorkOS Session Token（长效稳定，支持设备与用量管理）">长效 WS</span>');
  } else {
    badges.push('<span class="tag trial" title="纯短期 Access Token（仅约1小时有效，无法自动续期，容易失效掉号），建议提供 user_xxx:: 完整 Session Token">临时 acc (易掉)</span>');
  }
  if (a.hasApiKey) badges.push('<span class="tag teal">CLI</span>');
  const machineShort = a.machineIdShort || "";
  if (machineShort) {
    const localShort = lastCursorStatus?.localMachineShort || "";
    const mismatch = local && localShort && machineShort.toLowerCase() !== localShort.toLowerCase();
    badges.push(`<span class="tag machine${mismatch ? " warn" : ""}" title="${mismatch ? "与本机当前机器码不一致" : "已绑定机器码"}">机器码 ${esc(machineShort)}</span>`);
  }
  (a.tags || []).forEach((t) => badges.push(`<span class="tag custom">${esc(t)}</span>`));
  if (a.hasPassword) badges.push('<span class="tag">密码</span>');
  const expiry = a.proExpiryMs ? `周期至 ${fmtDate(a.proExpiryMs)} · ${daysLeft(a.proExpiryMs)}` : "周期未知";
  const stats = `近30天 $${Number(a.periodCostUsd || 0).toFixed(2)} · ${a.requestCount30d || 0}次`;
  const apiPct = a.apiPercentUsed >= 0 ? a.apiPercentUsed : a.includedApiPct;
  const autoPct = a.autoPercentUsed >= 0 ? a.autoPercentUsed : a.includedTotalPct;
  const botPct = a.botPercent;
  const err = a.err ? `<div class="hint" style="color:var(--danger)">${esc(a.err)}</div>` : "";
  const switchAction = local ? "launch-here" : "switch";
  const switchLabel = local ? "启动 IDE" : "切换并启动";
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
      <div class="acc-foot-main">
        <button class="btn primary btn-switch" data-action="${switchAction}" data-id="${esc(a.id)}" title="${switchTitle}">
          ${local ? ico("launch") : ico("switch")} <span>${switchLabel}</span>
        </button>
      </div>
      <div class="acc-foot-side">
        <button class="icon-btn" data-action="detail" data-id="${esc(a.id)}" title="详情">${ico("info")}</button>
        <button class="icon-btn" data-action="refresh" data-id="${esc(a.id)}" title="刷新额度">${ico("refresh")}</button>
        <div class="acc-more-wrap">
          <button class="icon-btn" data-action="toggle-more" data-id="${esc(a.id)}" title="更多操作" aria-label="更多操作">
            ${ico("more")}
          </button>
          <div class="acc-more-menu" role="menu">
            <button type="button" class="acc-menu-item" data-action="copy-token" data-id="${esc(a.id)}">
              ${ico("copy")} <span>复制 Token</span>
            </button>
            <button type="button" class="acc-menu-item" data-action="devices" data-id="${esc(a.id)}">
              ${ico("devices")} <span>登录设备与守卫</span>
            </button>
            <button type="button" class="acc-menu-item" data-action="launch-cli" data-id="${esc(a.id)}">
              ${ico("cli")} <span>启动 Agent CLI</span>
            </button>
            <div class="acc-menu-divider"></div>
            <button type="button" class="acc-menu-item danger" data-action="remove" data-id="${esc(a.id)}">
              ${ico("trash")} <span>删除账号</span>
            </button>
          </div>
        </div>
      </div>
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
  if (status?.version && status.version !== "?") bits.push(`v${status.version}`);
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
    else if (step?.inspectOnly) title.textContent = step.label;
    else if (step) title.textContent = `下一步：${step.label}`;
    else title.textContent = "Cursor 已关闭 — 可以改补丁";
  }
  if (hint) {
    if (running) {
      hint.textContent = step && step.needsClosed && !step.inspectOnly
        ? `要「${step.label}」：先点右边关 IDE，关掉后会自动继续。`
        : (step?.inspectOnly
          ? (step.hint || "现在只能看状态。模型墙请去扩展面板打，启动器不代写。")
          : "现在只能看状态、记代理偏好。改补丁前先关 IDE。");
    } else if (step?.hint) {
      hint.textContent = step.hint;
    } else {
      hint.textContent = "灰掉的按钮现在不能按。高级危险区平时别开。";
    }
  }
  if (closeBtn) closeBtn.hidden = !running;
  if (nextBtn) {
    const showNext = !running && step && step.id !== "ready" && typeof step.run === "function" && !step.inspectOnly;
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
  const wall = res.wall || {};
  const active = wall.active || (
    (layers.gateway > 0 && layers.sub2api > 0) ? "both"
      : (layers.gateway > 0 ? "yc" : (layers.sub2api > 0 ? "sub2api" : "none"))
  );
  if (active === "both") {
    return {
      id: "gateway",
      label: "模型墙：两套叠打（启动器只检查）",
      hint: wall.action || "同一时间只留 YC 或 Sub2API 一套。点刷新重新扫描。不要重装客户端。",
      needsClosed: false,
      inspectOnly: true,
      primary: false,
      run: null,
    };
  }
  if (active === "none") {
    return {
      id: "gateway",
      label: "模型墙：未接管（启动器只检查）",
      hint: wall.action || "点刷新重新扫描。补丁请在 YC 或 Sub2API 扩展面板打，启动器不代写。不要重装。",
      needsClosed: false,
      inspectOnly: true,
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
    hint: (active === "sub2api"
      ? "当前是 Sub2API 窄墙 + MAX + 500k。要更多模型和 Sand 就切回 YC。"
      : "当前是 YC 原生（多模型 / 自己的号 / Sand）+ MAX + 500k。以后用启动器开。"),
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

  const wall = res.wall || {};
  const yc = wall.yc || {};
  const sub2 = wall.sub2api || {};
  const ycOn = (yc.present === true) || (layers.gateway > 0);
  const sub2On = (sub2.present === true) || (layers.sub2api > 0);
  const items = [
    {
      id: "yc",
      ok: ycOn,
      idle: !ycOn && sub2On,
      warn: wall.active === "both",
      label: "YC 原生",
      meta: ycOn
        ? `${yc.hits || layers.gateway} 处 43111/__bajie · 多模型 / 自己的号 / Sand`
        : (yc.extensionInstalled ? "扩展在，workbench 未接管" : "未写入"),
    },
    {
      id: "sub2api",
      ok: sub2On,
      idle: !sub2On && ycOn,
      warn: wall.active === "both",
      label: "Sub2API",
      meta: sub2On
        ? `${sub2.endpoint || "localhost"} · 窄模型墙`
        : (sub2.extensionInstalled ? "扩展在，workbench 未接管" : "未写入"),
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
    const tone = it.warn ? "critical" : (it.ok ? "ok" : (it.idle ? "idle" : "warn"));
    const mark = it.warn ? "!" : (it.ok ? "✓" : (it.idle ? "–" : "○"));
    const isNext = step && !step.inspectOnly && (
      (step.id === "max" && it.id === "max") ||
      (step.id === "ctxwin" && it.id === "ctxwin") ||
      ((step.id === "proxy" || step.id === "proxy-write") && it.id === "proxy") ||
      (step.id === "repair" && it.id === "max")
    );
    return `<li class="wb-check ${tone}${isNext ? " is-next" : ""}"><span class="mark">${mark}</span><span>${it.label}</span><span class="meta">${it.meta}</span></li>`;
  }).join("");
}

function paintWbIncidents(res) {
  const box = $("wbIncidents");
  if (!box) return;
  if (!res || !res.ok) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const causeLabel = {
    stripped: "改回官方剥掉",
    upgraded: "升级覆盖了",
    overwritten: "文件被盖掉",
    missing: "从未写入 / 无备份",
    conflict: "两套叠打",
  };
  const activeLabel = {
    yc: "YC 原生",
    sub2api: "Sub2API 窄墙",
    both: "两套叠打",
    none: "都没接管",
  };
  const items = [];
  const wall = res.wall || {};
  if (wall.ok) {
    const active = wall.active || "none";
    const tone = (active === "both" || active === "none") ? "lost" : "tip";
    items.push({
      kind: "wall",
      tone,
      title: wall.title || "当前网关",
      why: wall.why || "",
      action: wall.action || "",
      badge: causeLabel[wall.cause] || activeLabel[active] || "",
      restore: false,
    });
  }
  const classic = res.classic || {};
  if (classic.ok && classic.lost) {
    items.push({
      kind: "classic",
      tone: "lost",
      title: classic.title || "旧版风格被覆盖了",
      why: classic.why || "",
      action: classic.action || "",
      badge: "进程没带 --classic",
      restore: false,
    });
  }
  if (!items.length) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
    box.innerHTML = items.map((it) => {
    const badge = it.badge ? `<span class="wb-incident-badge">${esc(it.badge)}</span>` : "";
    return `<article class="wb-incident is-${it.tone}"><div class="wb-incident-head"><strong>${esc(it.title)}</strong>${badge}</div><p>${esc(it.why)}</p><p class="wb-incident-action">${esc(it.action)}</p></article>`;
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
    if (opts.sandStream) {
      refreshSandStream();
      refreshBotGateway();
    }
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
    paintWbIncidents(lastWbDiag);
    const hint = $("wbNextHint");
    if (hint && pendingWbNext) {
      hint.textContent = pendingWbNext.inspectOnly
        ? (pendingWbNext.hint || "点刷新重新扫描模型墙。补丁请在扩展面板打，启动器不代写。")
        : (res.running && pendingWbNext.needsClosed
          ? `卡在「${pendingWbNext.label}」— 先关 IDE`
          : (pendingWbNext.hint || pendingWbNext.label));
    }
    syncIdeGate(!!res.running);
  }
  if (opts.ctxwin) refreshCtxwin();
  if (opts.modelUnlock) refreshModelUnlock();
  if (opts.sandStream) {
    refreshSandStream();
    if (typeof refreshBotGateway === "function") refreshBotGateway();
  }
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
    lines.push("⚠ 没检测到模型墙：请到 YC 或 Sub2API 扩展面板打补丁，启动器不代写");
  } else if (route === "clash" && patch.patched) {
    lines.push("只改代理参数，不会剥模型墙。要拆墙请用对应扩展面板回滚");
  } else if (route === "gateway") {
    lines.push("网关原生：不改 workbench；启动时由启动器带代理参数");
  } else {
    lines.push("保存只写 settings/argv，不动模型墙");
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

function _sandIncludeSubagent() {
  return Boolean($("sandIncludeSubagent")?.checked);
}

const SAND_LAYER_SPEC = [
  ["L0", "身份分流", ["hdrfixV2"]],
  ["L1", "本地路由", ["managedLocalRoute", "localRuntimeLoad", "agentHostEnablement", "agentHostIdentity"]],
  ["L2", "Direct 对话", ["directStream"]],
  ["L3", "传输", ["transportHost"]],
  ["L4", "协议改写", ["rpcRewrite", "streamWrap", "agentIde"]],
  ["L5", "工具执行", ["moveExec"]],
  ["L6", "子代理", ["taskTool", "subagentRoute", "actionRoute", "completionWake"]],
  ["L7", "工作区", ["maxTokens", "rulesSkills", "mcpFilesystem", "userRules"]],
  ["L8", "首问加速", ["rulesPreseed", "pushContextTimeout"]],
];

const SAND_CORE_MISSING = new Set([
  "managedLocalRoute",
  "localRuntimeLoad",
  "agentHostEnablement",
  "agentHostIdentity",
  "directStream",
  "hdrfixV2",
  "rpcRewrite",
  "streamWrap",
  "transportHost",
]);

const SAND_TASK_MISSING = new Set([
  "taskTool",
  "subagentRoute",
  "subagentSession",
  "actionRoute",
  "resumeMode",
  "completionWake",
  "maxTokens",
  "rulesSkills",
  "mcpFilesystem",
  "userRules",
  "rulesPreseed",
  "pushContextTimeout",
]);

function _sandMainMissing(res) {
  const keys = res.missing || [];
  const labels = res.missingLabels || [];
  if (!res.installed) return [];
  if (res.fullReady) return [];
  const pick = (allow) => keys
    .map((key, i) => (allow.has(key) ? labels[i] : ""))
    .filter(Boolean);
  if (!res.streamReady) return pick(SAND_CORE_MISSING);
  if (res.toolsReady && _sandIncludeSubagent()) return pick(SAND_TASK_MISSING);
  return [];
}

function _sandRulePill(row) {
  if (row.optional && row.status === "missing") return ["", "当前档不需要"];
  if (row.status === "applied") return ["ok", row.statusLabel || "已生效"];
  if (row.status === "partial") return ["warn", row.statusLabel || "部分生效"];
  if (row.status === "pending") return ["warn", row.statusLabel || "可打未打"];
  const miss = {
    package_absent: "包不存在",
    shape_changed: "代码变了",
    feature_absent: "版本没有",
  };
  return ["bad", miss[row.missKind] || row.statusLabel || "锚点缺失"];
}

const SAND_KEY_LABELS = {
  hdrfixV2: "身份分流",
  agentIde: "指纹",
  rpcRewrite: "RPC封装",
  streamWrap: "stream wrap",
  membershipFetch: "会员回包",
};

function _sandKeyLabel(key) {
  return SAND_KEY_LABELS[key] || key;
}

function _sandPkgKind(pkg) {
  const leftover = (pkg.canPatch || []).length;
  const marked = (pkg.patched || []).length;
  if (leftover && marked) return ["warn", "部分", (pkg.canPatch || []).concat(pkg.patched || [])];
  if (leftover) return ["warn", "可打", pkg.canPatch || []];
  if (marked) return ["ok", "已改", pkg.patched || []];
  return ["", "无锚点", []];
}

function _sandSetMeta(id, text) {
  const el = $(id);
  if (el) el.textContent = text || "";
}

function _sandFillCatSummaries(res) {
  const compat = res?.compat || {};
  const summary = compat.summary || {};
  const headers = (compat.headerLayers && compat.headerLayers.rows) || [];
  const headerOk = headers.filter((row) => row.status === "applied").length;
  const packages = compat.packages || [];
  const live = packages.filter((pkg) => (pkg.canPatch || []).length || (pkg.patched || []).length);
  const rules = compat.rules || [];
  const required = rules.filter((row) => !row.optional);
  const applied = required.filter((row) => row.status === "applied").length;
  const pending = required.filter((row) => row.status === "pending" || row.status === "partial").length;
  const bits = [
    compat.cursorVersion ? `v${compat.cursorVersion}` : (res?.version ? `v${res.version}` : ""),
    compat.patchTrack || "",
    summary.required ? `${summary.applied || applied}/${summary.required}` : "",
  ].filter(Boolean);
  _sandSetMeta("sandDetailMeta", bits.join(" · "));
  _sandSetMeta("sandCatHeaderMeta", headers.length ? `${headerOk}/${headers.length}` : "");
  _sandSetMeta("sandCatPkgsMeta", live.length ? `${live.length} 个` : "无");
  let ruleMeta = required.length ? `${applied}/${required.length}` : "";
  if (pending) ruleMeta += ` · ${pending} 未齐`;
  _sandSetMeta("sandCatRulesMeta", ruleMeta);
}

const _sandLazy = { res: null, header: false, pkgs: false, rules: false, layer: Object.create(null) };

function _sandResetLazy(res) {
  _sandLazy.res = res;
  _sandLazy.header = false;
  _sandLazy.pkgs = false;
  _sandLazy.rules = false;
  _sandLazy.layer = Object.create(null);
}

function _sandRuleItemHtml(row) {
  const [cls, label] = _sandRulePill(row);
  const files = (row.files || []).filter(Boolean);
  const why = [row.why, row.extra].filter(Boolean).join(" ");
  const fix = row.fix && !(row.optional && row.status === "missing") ? row.fix : "";
  const needUnlock = row.key === "membershipFetch" && (row.status === "pending" || row.status === "partial");
  const action = needUnlock
    ? `<div class="sand-rule-actions"><button type="button" class="btn ghost sm" data-sand-go="unlock">去完整解锁</button></div>`
    : "";
  return `<li class="sand-rule"><span class="pill ${esc(cls)}">${esc(label)}</span><div class="sand-rule-body"><div class="sand-rule-title">${esc(row.title || "")}${row.optional ? '<span class="sand-rule-opt"> · 当前档不强制</span>' : ""}</div>${why ? `<p class="sand-rule-why">${esc(why)}</p>` : ""}${files.length ? `<div class="sand-rule-files">${esc(files.join("  "))}</div>` : ""}${fix ? `<p class="sand-rule-fix">${esc(fix)}</p>` : ""}${action}</div></li>`;
}

function _sandPaintHeaderCat() {
  if (_sandLazy.header || !$("sandCatHeader")?.open) return;
  const res = _sandLazy.res;
  const headerEl = $("sandHeaderLayers");
  if (!headerEl) return;
  _sandLazy.header = true;
  if (!res || !res.ok) {
    headerEl.innerHTML = "";
    return;
  }
  const compat = res.compat || {};
  const rows = (compat.headerLayers && compat.headerLayers.rows) || [];
  const byKey = {};
  for (const row of compat.rules || []) byKey[row.key] = row;
  const older = compat.headerLayers && compat.headerLayers.relation === "older";
  headerEl.innerHTML = rows.map((row) => {
    const full = byKey[row.key] || {};
    return _sandRuleItemHtml({
      key: row.key,
      title: row.title,
      why: full.why || "",
      extra: older ? (row.onOlder || "") : "",
      files: full.files,
      fix: full.fix,
      optional: row.key === "membershipFetch" || full.optional,
      status: row.status,
      statusLabel: row.statusLabel,
      missKind: full.missKind || "",
    });
  }).join("");
}

function _sandPaintPkgsCat() {
  if (_sandLazy.pkgs || !$("sandCatPkgs")?.open) return;
  const res = _sandLazy.res;
  const pkgsEl = $("sandStreamPackages");
  if (!pkgsEl) return;
  _sandLazy.pkgs = true;
  if (!res || !res.ok) {
    pkgsEl.innerHTML = "";
    return;
  }
  const packages = (res.compat || {}).packages || [];
  const live = packages.filter((pkg) => (pkg.canPatch || []).length || (pkg.patched || []).length);
  const idle = packages.length - live.length;
  pkgsEl.innerHTML = live.map((pkg) => {
    const [cls, label, keys] = _sandPkgKind(pkg);
    const keyText = [...new Set(keys)].map(_sandKeyLabel).join("、");
    return `<li class="sand-pkg" title="${esc(pkg.name)}"><span class="pill ${esc(cls)}">${esc(label)}</span><div><span class="sand-pkg-name">${esc(pkg.name)}</span>${keyText ? `<span class="sand-pkg-keys">${esc(keyText)}</span>` : ""}</div></li>`;
  }).join("");
  if (!live.length) {
    pkgsEl.innerHTML = `<li class="hint">当前扫到的包里没有可改锚点。</li>`;
  } else if (idle > 0) {
    pkgsEl.insertAdjacentHTML("beforeend", `<li class="hint">另有 ${idle} 个包没有对应锚点。</li>`);
  }
}

function _sandPaintLayerRules(layerId) {
  if (!layerId || _sandLazy.layer[layerId]) return;
  let fold = null;
  for (const el of document.querySelectorAll(".sand-cat-layer")) {
    if (el.dataset.layer === layerId) {
      fold = el;
      break;
    }
  }
  if (!fold?.open) return;
  const list = fold.querySelector("[data-layer-list]");
  if (!list) return;
  _sandLazy.layer[layerId] = true;
  const res = _sandLazy.res;
  const rules = ((res && res.compat) || {}).rules || [];
  const rows = rules.filter((row) => String(row.layer || "") === layerId);
  list.innerHTML = rows.map(_sandRuleItemHtml).join("");
}

function _sandPaintRulesCat() {
  if (_sandLazy.rules || !$("sandCatRules")?.open) return;
  const wrap = $("sandRuleGroups");
  const res = _sandLazy.res;
  if (!wrap) return;
  _sandLazy.rules = true;
  _sandLazy.layer = Object.create(null);
  if (!res || !res.ok) {
    wrap.innerHTML = "";
    return;
  }
  const rules = (res.compat || {}).rules || [];
  if (!rules.length) {
    const layers = res.layers || {};
    wrap.innerHTML = `<ul class="sand-layers">${SAND_LAYER_SPEC.map(([id, label, keys]) => {
      const block = layers[id] || {};
      const on = keys.filter((key) => Number(block[key] || 0) > 0).length;
      const cls = on === keys.length ? "is-on" : (on > 0 ? "is-partial" : "is-off");
      return `<li class="sand-layer ${cls}"><span>${esc(id)} ${esc(label)}</span><span>${on}/${keys.length}</span></li>`;
    }).join("")}</ul>`;
    return;
  }
  const byLayer = new Map();
  for (const row of rules) {
    const id = String(row.layer || "其他");
    if (!byLayer.has(id)) byLayer.set(id, []);
    byLayer.get(id).push(row);
  }
  const known = SAND_LAYER_SPEC.map(([id]) => id);
  const extra = [...byLayer.keys()].filter((id) => !known.includes(id));
  const order = known.concat(extra);
  const summary = (res.compat || {}).summary || {};
  const need = Number(summary.required || 0);
  const done = Number(summary.applied || 0);
  const verdict = need && done >= need
    ? `${done}/${need} 条当前档已生效`
    : (need ? `${done}/${need} 条已生效，还没打全` : `${rules.length} 条规则`);
  const pillCls = need && done >= need ? "ok" : (done ? "warn" : "");
  wrap.innerHTML = `<div class="sand-rules-head"><span class="pill ${esc(pillCls)}">${esc(verdict)}</span><p class="sand-rules-legend">已生效 = 标记已写入。可打未打 = 找到锚点还没改。锚点缺失 = 这版 Cursor 没有这段代码。</p></div>` + order.map((id) => {
    const rows = byLayer.get(id);
    if (!rows || !rows.length) return "";
    const spec = SAND_LAYER_SPEC.find((item) => item[0] === id);
    const label = spec ? spec[1] : id;
    const required = rows.filter((row) => !row.optional);
    const applied = required.filter((row) => row.status === "applied").length;
    const pending = required.filter((row) => row.status === "pending" || row.status === "partial").length;
    let meta = required.length ? `${applied}/${required.length}` : `${rows.length}`;
    if (pending) meta += ` · ${pending} 未齐`;
    return `<details class="sand-cat sand-cat-layer" data-layer="${esc(id)}"><summary><span>${esc(id)} ${esc(label)}</span><span class="sand-fold-meta">${esc(meta)}</span></summary><ul class="sand-layers" data-layer-list></ul></details>`;
  }).join("");
  wrap.querySelectorAll(".sand-cat-layer").forEach((el) => {
    el.addEventListener("toggle", () => {
      if (el.open) _sandPaintLayerRules(el.dataset.layer);
    });
  });
}

function _sandPaintOpenCats() {
  _sandPaintHeaderCat();
  _sandPaintPkgsCat();
  _sandPaintRulesCat();
}

function paintSandStream(res) {
  const stateEl = $("sandStreamState");
  const copyEl = $("sandStreamCopy");
  const missingEl = $("sandStreamMissing");
  const hintEl = $("sandCompatHint");
  const adviceEl = $("sandUpgradeAdvice");
  const fullBtn = $("btnSandStreamApplyFull");
  const streamBtn = $("btnSandStreamApplyStream");
  const restoreBtn = $("btnSandStreamRestore");
  const setBlocked = (applyBlocked, restoreBlocked) => {
    fullBtn?.classList.toggle("is-blocked", applyBlocked);
    streamBtn?.classList.toggle("is-blocked", applyBlocked);
    restoreBtn?.classList.toggle("is-blocked", restoreBlocked);
  };
  if (!stateEl && !copyEl) return;
  _sandResetLazy(res);
  if (!res || !res.ok) {
    if (stateEl) {
      stateEl.textContent = "不可用";
      stateEl.dataset.state = "critical";
    }
    if (copyEl) copyEl.textContent = res?.error || "无法检测 Bot 补丁状态";
    if (missingEl) missingEl.innerHTML = "";
    if (hintEl) hintEl.textContent = "";
    if (adviceEl) adviceEl.textContent = "";
    _sandSetMeta("sandDetailMeta", "");
    _sandSetMeta("sandCatHeaderMeta", "");
    _sandSetMeta("sandCatPkgsMeta", "");
    _sandSetMeta("sandCatRulesMeta", "");
    setBlocked(true, true);
    _sandPaintOpenCats();
    return;
  }

  let title = "未启用";
  let tone = "off";
  let copy = "还没打补丁。日常用「启用完整」；只要对话通路就用「仅对话」。500k / MAX 请看顶栏日常状态。";
  if (res.fullReady) {
    title = "完整档";
    tone = "ok";
    copy = "工具和子代理可用，Bot 走 Direct Stream。";
  } else if (res.toolsReady) {
    title = "工具已开";
    tone = "ok";
    copy = "对话和工具可用。勾选 Task 后再启用完整，可补子代理。";
  } else if (res.streamReady) {
    title = "仅对话";
    tone = "ok";
    copy = "Bot 已走 Direct Stream，还没装工具和子代理。聊天里的 256k 窗口归 500k 回包，不归这一栏。";
  } else if (res.installed) {
    title = "不完整";
    tone = "warn";
    copy = "有残留标记，但对话通路还没打齐。";
  }
  const compat = res.compat || {};
  const summary = compat.summary || {};
  const meta = [
    compat.versionHint || res.versionHint || (res.version ? `Cursor v${res.version}` : ""),
    summary.required ? `${summary.applied || 0}/${summary.required} 条当前档规则已生效` : "",
    res.running ? "请先关 IDE 再改文件" : "",
  ].filter(Boolean).join(" · ");
  if (stateEl) {
    stateEl.textContent = title;
    stateEl.dataset.state = tone;
  }
  if (copyEl) copyEl.textContent = [copy, meta].filter(Boolean).join(" ");
  if (hintEl) {
    const bits = [
      compat.cursorVersion ? `本机 Cursor v${compat.cursorVersion}` : "",
      compat.patchTrack
        ? (compat.testedBuild
          ? `补丁轨 ${compat.patchTrack}（已测 ${compat.anchorVersion || ""}）`
          : `补丁轨 ${compat.patchTrack}`)
        : "",
      compat.versionHint || "",
    ].filter(Boolean);
    const v132 = res.installer132;
    if (v132 && v132.detected) {
      const total = Object.values(v132.counts || {}).reduce((a, b) => a + (b || 0), 0);
      bits.push(
        `检测到 Sand-Stream-Installer 1.3.2 残留 ${total} 处：启用/还原会自动迁回，已装启动器就不要再跑该工具`
      );
    }
    hintEl.textContent = bits.join(" · ");
    hintEl.hidden = !hintEl.textContent;
  }
  if (adviceEl) {
    adviceEl.textContent = (compat.upgrade && compat.upgrade.advice) || "";
    adviceEl.hidden = !adviceEl.textContent;
  }

  if (missingEl) {
    missingEl.innerHTML = "";
    const counts = { package_absent: 0, shape_changed: 0, feature_absent: 0 };
    for (const row of (compat.rules || [])) {
      if (row.optional || row.status !== "missing" || !counts.hasOwnProperty(row.missKind)) continue;
      counts[row.missKind] += 1;
    }
    const kinds = [
      counts.package_absent ? `包不存在 ${counts.package_absent}` : "",
      counts.shape_changed ? `代码变了 ${counts.shape_changed}` : "",
      counts.feature_absent ? `这个版本没有 ${counts.feature_absent}` : "",
    ].filter(Boolean);
    if (kinds.length) {
      const item = document.createElement("li");
      item.className = "wb-diag-rec warn";
      const strong = document.createElement("strong");
      strong.textContent = "缺失分类";
      item.appendChild(strong);
      item.appendChild(document.createTextNode(kinds.join(" · ")));
      missingEl.appendChild(item);
    }
    const shown = _sandMainMissing(res);
    if (shown.length) {
      const item = document.createElement("li");
      item.className = "wb-diag-rec warn";
      const strong = document.createElement("strong");
      strong.textContent = "还缺";
      item.appendChild(strong);
      item.appendChild(document.createTextNode(shown.join("、")));
      missingEl.appendChild(item);
    }
  }

  _sandFillCatSummaries(res);
  _sandPaintOpenCats();

  const blocked = !res.canApply;
  setBlocked(blocked, !res.canRestore);
  if (fullBtn) fullBtn.title = res.running ? "请先关闭 IDE" : "对话 + 工具，可选子代理";
  if (streamBtn) streamBtn.title = res.running ? "请先关闭 IDE" : "只打 Direct Stream，不含工具";
  if (restoreBtn) restoreBtn.title = res.installed ? "去掉本模块全部 Sand 补丁" : "当前未安装";
  syncIdeGate(Boolean(lastCursorStatus?.running || res.running));
}

async function refreshSandStream() {
  if (!api()?.sand_stream_status) return;
  try {
    paintSandStream(await api().sand_stream_status("full", _sandIncludeSubagent()));
  } catch (e) {
    paintSandStream({ ok: false, error: String(e) });
  }
}

function waitPatchJob(paint) {
  const show = typeof paint === "function" ? paint : () => {};
  return new Promise((resolve) => {
    let settled = false;
    const finish = (p) => {
      if (settled) return;
      settled = true;
      clearInterval(waitPatchJob._t);
      window.removeEventListener("patch-job-progress", onEvent);
      show(p);
      const res = p.result || { ok: p.phase !== "error", error: p.message, message: p.message };
      resolve(res);
    };
    const onEvent = (ev) => {
      const p = ev.detail || {};
      show(p);
      if (!p.busy) finish(p);
    };
    window.addEventListener("patch-job-progress", onEvent);
    waitPatchJob._t = setInterval(async () => {
      try {
        const p = await api().patch_job_progress();
        show(p);
        if (!p.busy) finish(p);
      } catch {
        finish({ busy: false, phase: "error", message: "进度读取失败", result: { ok: false, error: "进度读取失败" } });
      }
    }, 300);
  });
}

async function runPatchJob(startName, args, fallbackFn, startMessage, paint) {
  const show = typeof paint === "function" ? paint : () => {};
  show({ pct: 3, phase: "start", message: startMessage || "开始处理…", busy: true, steps: [] });
  const bridge = api();
  if (bridge?.[startName]) {
    const started = await bridge[startName](...args);
    if (!started?.ok) {
      show({ pct: 0, phase: "error", message: started?.error || "无法开始", steps: [] });
      return started || { ok: false, error: "无法开始" };
    }
    return waitPatchJob(show);
  }
  try {
    const res = await fallbackFn();
    show({
      pct: 100,
      phase: res?.ok ? "done" : "error",
      message: res?.message || res?.error || (res?.ok ? "完成" : "失败"),
    });
    return res;
  } catch (e) {
    show({ pct: 0, phase: "error", message: String(e) });
    return { ok: false, error: String(e) };
  }
}

function paintSandJobProgress(p) {
  const steps = Array.isArray(p.steps) ? p.steps : [];
  const show = Boolean(p.busy || steps.length);
  const box = $("sandJobBox");
  if (box) box.hidden = !show;
  const copy = $("sandStreamCopy");
  if (copy && p.message) copy.textContent = p.message;
  const stateEl = $("sandStreamState");
  if (stateEl && p.busy) {
    stateEl.textContent = "处理中";
    stateEl.dataset.state = "busy";
  }
  const head = $("sandJobHead");
  const restoring = String(p.job || "").includes("restore") || String(p.message || "").includes("还原");
  if (head) head.textContent = restoring ? "本次还原" : "本次写入";
  paintJobSteps($("sandJobSteps"), steps);
}

function _paintSandBusy(text) {
  const copy = $("sandStreamCopy");
  const stateEl = $("sandStreamState");
  if (stateEl) {
    stateEl.textContent = "处理中";
    stateEl.dataset.state = "busy";
  }
  if (copy) copy.textContent = text;
}

async function runSandStream(kind, profile) {
  const label = kind === "restore" ? "还原 Grok Bot" : (profile === "stream" ? "启用仅对话" : "启用完整档");
  _paintSandBusy("先确认 IDE 已关…");
  toast(label + "：处理中，请稍等");
  await new Promise((r) => setTimeout(r, 50));
  if (!(await requireIdeClosed(label))) {
    refreshSandStream();
    return;
  }
  if (kind === "restore") {
    const ok = window.confirm("只去掉 Grok Bot。MAX 和 500k 会尽量保留；若被拆掉会自动补回。确定？");
    if (!ok) {
      refreshSandStream();
      return;
    }
  } else {
    const extra = profile === "stream"
      ? "只改 Bot 对话通路，不装工具和子代理。不管 500k / MAX。"
      : (_sandIncludeSubagent() ? "打上对话通路、工具和子代理。不管 500k / MAX。" : "打上对话通路和工具，不含子代理。不管 500k / MAX。");
    const ok = window.confirm(`${extra}\n改的是 Cursor 安装目录里的文件，Bot 栏里会一条条列出。确定？`);
    if (!ok) {
      refreshSandStream();
      return;
    }
  }
  const startMessage = kind === "restore" ? "正在还原 Grok Bot…" : "正在写入 Grok Bot…";
  _paintSandBusy(startMessage);
  toast(startMessage);
  const includeSubagent = _sandIncludeSubagent();
  const res = kind === "restore"
    ? await runPatchJob("sand_stream_restore_start", [], () => api().sand_stream_restore(), startMessage, paintSandJobProgress)
    : await runPatchJob(
      "sand_stream_apply_start",
      [profile === "stream" ? "stream" : "full", includeSubagent],
      () => api().sand_stream_apply(profile === "stream" ? "stream" : "full", includeSubagent),
      startMessage,
      paintSandJobProgress,
    );
  paintSandStream(res);
  if (!res.ok) return toast(res.error || "失败");
  if (res.skipped) {
    toast(res.message || "无需操作");
  } else if (kind !== "restore" && res.complete === false) {
    const shown = _sandMainMissing(res);
    if (shown.length) toast("已写入，仍缺：" + shown.join("、"));
    else if (res.streamReady && !res.fullReady) toast("对话通路已写入，请再启动 IDE");
    else toast("已写入能打到的层，请再启动 IDE");
  } else {
    toast(res.message || (kind === "restore" ? "已还原，请再启动 IDE" : "已启用，请再启动 IDE"));
  }
  refreshWbDiag();
}

function paintCrashDiag(res) {
  const title = $("crashHeadline");
  const advice = $("crashAdvice");
  const list = $("crashFindings");
  if (!title) return;
  if (!res || !res.ok) {
    title.textContent = "崩溃原因";
    if (advice) advice.textContent = res?.error || "无法读取 Cursor 日志";
    if (list) list.innerHTML = "";
    return;
  }
  title.textContent = res.headline || "崩溃原因";
  if (advice) advice.textContent = res.advice || "";
  if (list) {
    const items = (res.likely || []).slice(0, 4);
    const recent = (res.recentExtensions || []).slice(0, 4).map((e) => e.id).filter(Boolean);
    list.innerHTML = items.map((item) => {
      const tone = item.severity === "critical" ? "critical" : (item.severity === "warn" ? "warn" : "ok");
      const ext = item.extensionId ? ` · ${esc(item.extensionId)}` : "";
      const detail = item.detail ? `<small>${esc(item.detail)}</small>` : "";
      return `<li class="wb-diag-rec ${tone}"><strong>${esc(item.title)}${ext}</strong>${detail}</li>`;
    }).join("") + (recent.length && !items.some((i) => i.extensionId)
      ? `<li class="wb-diag-rec"><strong>最近安装的扩展</strong><small>${esc(recent.join("、"))}</small></li>`
      : "");
  }
}

async function refreshCrashDiag() {
  if (!api()?.crash_diagnose) return;
  try {
    paintCrashDiag(await api().crash_diagnose());
  } catch (e) {
    paintCrashDiag({ ok: false, error: String(e) });
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
    paintWbIncidents(null);
    if (chips) chips.innerHTML = _wbChip("诊断失败", "critical");
    if (recs) recs.innerHTML = "";
    if (hint) hint.textContent = res?.error || "无法读取诊断，点刷新重试";
    info.textContent = res?.error || "无法读取诊断";
    syncIdeGate(Boolean(lastCursorStatus?.running));
    return;
  }

  pendingWbNext = computeWbNext(res);
  paintWbChecklist(res);
  paintWbIncidents(res);
  if (hint) {
    const step = pendingWbNext;
    if (step?.inspectOnly) {
      hint.textContent = step.hint || "点刷新重新扫描模型墙。补丁请在 YC / Sub2API 扩展面板打，启动器不代写。";
    } else if (res.cursorRunning && step?.needsClosed) {
      hint.textContent = `卡在「${step.label}」— 先关 IDE，关掉后点顶栏「${step.label}」或会自动继续。`;
    } else if (step?.id === "launch") {
      hint.textContent = step.hint || "日常组合齐了。用启动器开 Cursor 即可。";
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
    bits.push(_wbChip(layers.gateway > 0 ? `YC×${layers.gateway}` : "无 YC", layers.gateway > 0 ? "ok" : "warn"));
    bits.push(_wbChip(layers.sub2api > 0 ? "Sub2API" : "无 Sub2API", layers.sub2api > 0 ? "ok" : "info"));
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
    restoreBtn.title = res.cursorRunning ? "请先关闭 IDE" : "从 official 基线还原 workbench（不会用 bajie 备份补墙）";
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
  if (step.inspectOnly || (step.id === "gateway" && typeof step.run !== "function")) {
    toast((lastWbDiag && lastWbDiag.wall && lastWbDiag.wall.why) || "已扫描模型墙。启动器只检查，不代写。");
    return refreshWbDiag();
  }
  if (typeof step.run !== "function") {
    return toast(step.hint || "没有可执行的下一步");
  }
  if (step.needsClosed && !(await requireIdeClosed(step.label))) return;
  await step.run();
  await refreshWbDiag();
}

let wbDiagInflight = null;

async function refreshWbDiag(opts = {}) {
  if (!api()?.workbench_diagnostic) return;
  const force = opts.force !== false;
  const extras = opts.extras === true;
  if (!force && lastWbDiag?.ok) {
    paintHealthBanner(lastWbDiag);
    return;
  }
  if (wbDiagInflight) {
    await wbDiagInflight;
    if (!force) return;
  }
  const run = (async () => {
    const info = $("wbDiagInfo");
    if (info && force) info.textContent = "正在扫描…";
    try {
      const res = await api().workbench_diagnostic(force);
      paintWbDiag(res);
      paintHealthBanner(res);
    } catch (e) {
      paintWbDiag({ ok: false, error: String(e) });
      paintHealthBanner({ ok: false, error: String(e) });
    }
    if (extras) {
      refreshCrashDiag();
      refreshLauncherUpdate();
    }
  })();
  wbDiagInflight = run;
  try {
    await run;
  } finally {
    if (wbDiagInflight === run) wbDiagInflight = null;
  }
}

function paintHealthBanner(res) {
  const banner = $("healthBanner");
  const title = $("healthTitle");
  const hint = $("healthHint");
  const fixBtn = $("btnAutofix");
  const wallStatus = $("healthWallStatus");
  if (!banner) return;
  banner.hidden = false;
  if (!res?.ok) {
    banner.dataset.state = "critical";
    if (title) title.textContent = "补丁自检失败";
    if (hint) hint.textContent = res?.error || "无法诊断";
    if (fixBtn) fixBtn.hidden = true;
    if (wallStatus) wallStatus.hidden = true;
    return;
  }
  const af = res.autofix || {};
  const steps = (af.steps || []).filter((s) => !s.manual && !s.inspectOnly);
  const upgrade = res.cursorUpgrade || {};
  const wall = res.wall || {};
  const active = wall.active || (wall.present === false ? "none" : (wall.present ? "yc" : "none"));
  const conflict = active === "both";
  const wallDown = active === "none";
  let state = "ok";
  if (res.modelUnlock?.corrupted) state = "critical";
  else if (conflict || wallDown || !af.ready || upgrade.needsRepatch) state = "warn";
  banner.dataset.state = state;

  if (wallStatus) {
    const labels = {
      yc: "模型墙：YC 原生",
      sub2api: "模型墙：Sub2API",
      both: "模型墙：两套叠打",
      none: "模型墙：未接管",
    };
    wallStatus.hidden = false;
    wallStatus.textContent = labels[active] || "模型墙：—";
    wallStatus.dataset.state = (conflict || wallDown) ? "warn" : "ok";
    wallStatus.title = wall.why || wall.action || "启动器只检查模型墙，不代写。点刷新重新扫描。";
  }

  if (title) {
    if (res.modelUnlock?.corrupted) {
      title.textContent = "workbench 异常，先修黑屏";
    } else if (conflict) {
      title.textContent = wall.title || "两套网关补丁叠在一起";
    } else if (wallDown) {
      title.textContent = wall.title || "两套网关都没接管 workbench";
    } else if (af.ready && !upgrade.needsRepatch) {
      const kind = active === "sub2api" ? "Sub2API 窄墙" : "YC 原生";
      title.textContent = `${kind} · Cursor v${res.version || "?"} · 启动器 v${res.launcherVersion || "?"}`;
    } else if (upgrade.needsRepatch) {
      const ver = (res.version && res.version !== "?") ? res.version : "";
      title.textContent = ver
        ? `Cursor 已升级到 v${ver} — 建议重打补丁`
        : "读不到 Cursor 版本 — 安装可能不完整";
    } else {
      title.textContent = `待补齐 ${steps.length} 项`;
    }
  }
  if (hint) {
    const noWallWrite = "一键补齐只打 MAX / 500k / 代理，不打模型墙。";
    if (conflict || wallDown) {
      const why = wall.why || "YC 原生和 Sub2API 窄墙同一时间只应打一套。不要重装客户端。";
      hint.textContent = steps.length > 0 ? `${why} ${noWallWrite}` : why;
    } else if (af.ready && !upgrade.needsRepatch) {
      hint.textContent = res.profile || (active === "sub2api" ? "Sub2API 窄墙" : "YC 原生");
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
    ? "将关闭 Cursor，然后自动：仅 MAX → 500k → 代理参数。\n模型墙请用 YC / Sub2API 扩展面板自己打，启动器不代写。\n确定？"
    : "将自动补齐：仅 MAX → 500k → 代理参数。\n模型墙请用 YC / Sub2API 扩展面板自己打，启动器不代写。\n确定？";
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
  if (!confirm("将从 official 基线还原 workbench（不会用 bajie 备份补墙）。确定？")) return;
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
  const startName = kind === "restore" ? "ctxwin_restore_start" : "ctxwin_apply_start";
  const startMessage = kind === "restore" ? "正在还原 500k…" : "正在启用 500k…";
  const info = $("ctxwinInfo");
  if (info) info.textContent = startMessage;
  const res = await runPatchJob(startName, [], () => api()[fn](), startMessage, (p) => {
    if (info && p.message) info.textContent = p.message;
  });
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
  const preview = res.sidebarPreview || {};
  const storageLine = storage.ok
    ? `侧边栏=${storage.applicationUserMembershipType || "—"} · stripe未改=${storage.stripeMembershipType || "—"}`
    : "";
  const sidebarLine = preview.ok
    ? (
      preview.needsWrite
        ? `侧边栏将写成 ${preview.targetLabel}（现在 ${preview.current || "空"}）。只改缓存，不改程序文件。`
        : `侧边栏已是 ${preview.targetLabel}，不用再写。`
    )
    : "";
  const lines = [
    maxReady
      ? "状态：MAX 开关已解锁"
      : (res.installed ? "状态：部分解锁，请点「仅解锁 MAX」" : "状态：无 MAX 开关（token 计价会被 hideMaxToggle 藏掉）"),
    `命中：FREE×${hits.modelLock || 0} · 显示MAX×${hits.showMax || 0} · 命名视图×${hits.namedView || 0} · 目录×${hits.catalog || 0} · 绑卡×${hits.maxMode || 0} · 会员×${hits.memPro || 0} · fetch×${hits.fetchSpoof || 0}`,
    storageLine,
    sidebarLine,
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
    const preview = res.sidebarPreview || {};
    syncBtn.title = res.running
      ? "请先关闭 IDE"
      : (preview.needsWrite
        ? `只写侧边栏缓存 → ${preview.targetLabel || "Pro"}，不改 workbench`
        : "侧边栏已是目标套餐");
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
  if (!(await requireIdeClosed("写入侧边栏"))) return;
  const status = await api().model_unlock_status();
  if (!status.canSyncStorage) {
    paintModelUnlock(status);
    return toast(status.running ? "请先关闭 IDE" : (status.error || "当前不能写入侧边栏"));
  }
  const preview = status.sidebarPreview || {};
  if (preview.ok && !preview.needsWrite) {
    paintModelUnlock(status);
    return toast(`侧边栏已经是 ${preview.targetLabel || level}，未改任何文件`);
  }
  const from = preview.current || "空";
  const to = preview.targetLabel || level;
  if (!confirm(
    `只改侧边栏缓存（state.vscdb），不改 Cursor 程序文件，不会因此黑屏。\n\n${from} → ${to}\n账单页仍显示真套餐。\n\n确定写入？`
  )) return;
  const info = $("modelUnlockInfo");
  if (info) info.textContent = "正在写入侧边栏套餐…";
  const res = await api().model_unlock_sync_storage(level);
  paintModelUnlock(await api().model_unlock_status());
  if (!res.ok) return toast(res.error || "失败");
  toast(res.message || "已写入侧边栏");
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
  const startMessage = kind === "restore" ? "正在还原 MAX…" : (kind === "applyMax" ? "正在解锁 MAX…" : "正在完整解锁…");
  if (info) info.textContent = startMessage;
  const res = kind === "applyMax"
    ? await runPatchJob("model_unlock_apply_start", [null, true], () => api().model_unlock_apply(null, true), startMessage, (p) => {
      if (info && p.message) info.textContent = p.message;
    })
    : await runPatchJob(
      kind === "restore" ? "model_unlock_restore_start" : "model_unlock_apply_start",
      kind === "restore" ? [] : [select?.value, false],
      () => api()[fn](kind === "apply" ? select?.value : undefined),
      startMessage,
      (p) => {
        if (info && p.message) info.textContent = p.message;
      },
    );
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
    ${machineDetailSection(a)}
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

async function rotateMachine() {
  if (!detailAccountId || !api()?.rotate_account_machine) return;
  if (!confirm("更换后此账号绑定新的 Desktop 机器码，旧设备会话可能还在。确定？")) return;
  toast("正在更换机器码…");
  const res = await api().rotate_account_machine(detailAccountId);
  if (!res.ok) return toast(res.error || "更换失败");
  toast(res.wroteLocal ? "已写入本机并绑定" : "已绑定，下次切换此号时生效");
  if (res.account) renderDetail(res.account);
  await renderAccounts();
  await refreshCursorStatus();
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

async function launchCli(accountId, apiKey = "", save = false) {
  if (!api()?.launch_agent_cli) return toast("当前版本不支持 CLI 启动");
  let key = String(apiKey || "").trim();
  let shouldSave = Boolean(save);
  if (!key) {
    const detail = await api().get_account_detail(accountId);
    if (detail.ok && detail.account?.apiKey) key = String(detail.account.apiKey).trim();
  }
  if (!key) {
    key = String(prompt("粘贴 Cursor API Key（crsr_…）", "") || "").trim();
    if (!key) return;
    shouldSave = confirm("是否把这个 API Key 保存到该账号？（下次可直接点 CLI）");
  }
  toast("正在启动 Agent CLI…");
  const res = await api().launch_agent_cli(accountId, key, null, null, shouldSave);
  toast(res.ok ? (res.saved ? "已保存 Key 并打开 CLI 终端" : "已打开 CLI 终端") : (res.error || "启动失败"));
  if (res.ok && res.saved) await renderAccounts();
  return res;
}

async function saveDetailApiKey() {
  if (!detailAccountId || !api()?.set_account_api_key) return toast("当前版本不支持保存 API Key");
  const key = String($("detailApiKey")?.value || "").trim();
  const res = await api().set_account_api_key(detailAccountId, key);
  toast(res.ok ? (key ? "API Key 已保存" : "已清空 API Key") : (res.error || "保存失败"));
  if (res.ok) {
    await renderAccounts();
    const detail = await api().get_account_detail(detailAccountId);
    if (detail.ok) renderDetail(detail.account);
  }
}

async function openCliDialog() {
  const dlg = $("cliDialog");
  if (!dlg) return;
  dlg.showModal();
  if (api()?.get_cli_config) {
    const cfg = await api().get_cli_config();
    if (cfg?.ok) {
      if (cfg.apiKey && !$("cliApiKeyInput").value) $("cliApiKeyInput").value = cfg.apiKey;
      if (cfg.cwd && !$("cliCwdInput").value) $("cliCwdInput").value = cfg.cwd;
      const hint = $("cliStatusHint");
      const installBtn = $("btnCliInstallHint");
      if (cfg.installed) {
        if (hint) hint.textContent = `已检测到 CLI: ${cfg.agentPath}`;
        if (installBtn) installBtn.hidden = true;
      } else {
        if (hint) hint.textContent = "未检测到 Cursor Agent CLI。建议先安装。";
        if (installBtn) installBtn.hidden = false;
      }
    }
  }
}

function closeCliDialog() {
  const dlg = $("cliDialog");
  if (dlg?.open) dlg.close();
}

async function launchCliDirect() {
  if (!api()?.launch_agent_cli) return toast("当前版本不支持 CLI 启动");
  const key = String($("cliApiKeyInput")?.value || "").trim();
  const cwd = String($("cliCwdInput")?.value || "").trim();
  const prompt = String($("cliPromptInput")?.value || "").trim();
  const remember = Boolean($("cliRememberKey")?.checked);
  if (!key) return toast("请填写 Cursor API Key（crsr_…）");
  toast("正在启动 Agent CLI…");
  const res = await api().launch_agent_cli(null, key, prompt, cwd, remember);
  if (res.ok) {
    toast(res.saved ? "已保存配置并打开终端" : "已打开终端");
    closeCliDialog();
  } else {
    toast(res.error || "启动失败");
  }
}

let _mcpServersCache = [];
let _pendingDeleteMcp = null;

async function loadMcpServers() {
  const container = $("mcpServerList");
  if (!container) return;
  if (!api()?.get_mcp_servers) {
    container.innerHTML = '<p class="hint">当前版本 API 未提供 MCP 管理接口</p>';
    return;
  }
  container.innerHTML = '<p class="hint" style="padding:8px 0">正在扫描 MCP 服务配置…</p>';
  try {
    const res = await api().get_mcp_servers();
    if (!res?.ok) {
      container.innerHTML = `<p class="hint" style="color:var(--danger)">扫描失败: ${esc(res?.error || "未知错误")}</p>`;
      return;
    }
    _mcpServersCache = res.servers || [];
    renderMcpServers(_mcpServersCache);
  } catch (err) {
    container.innerHTML = `<p class="hint" style="color:var(--danger)">读取异常: ${esc(String(err))}</p>`;
  }
}

function renderMcpServers(servers) {
  const container = $("mcpServerList");
  if (!container) return;
  if (!servers || !servers.length) {
    container.innerHTML = `
      <div class="mcp-empty-state">
        <p>未在系统或工作区发现任何有效的 <code>mcp.json</code> 服务配置。</p>
      </div>`;
    return;
  }

  container.innerHTML = servers.map((s) => {
    const scopeClass = s.scope === "global" ? "teal" : "pro";
    const statusPill = s.disabled
      ? '<span class="pill warn" style="font-size:11px">已禁用</span>'
      : '<span class="pill ok" style="font-size:11px">启用中</span>';
    const pluginTag = s.isPlugin
      ? '<span class="tag trial" title="疑似由安装的 Cursor 插件注入">插件服务</span>'
      : '';
    const cmdLine = [s.command, ...(s.args || [])].join(" ");
    const hasDirs = s.extraDirs && s.extraDirs.length > 0;
    const dirsHint = hasDirs
      ? `<span title="关联本地数据目录: ${esc(s.extraDirs.join(', '))}">📁 关联数据 (${s.extraDirs.length})</span>`
      : '';

    return `
      <div class="mcp-card${s.disabled ? ' is-disabled' : ''}" data-mcp-id="${esc(s.id)}">
        <div class="mcp-card-head">
          <div class="mcp-card-title">
            <span>${esc(s.name)}</span>
            <span class="pill ${scopeClass}" style="font-size:11px">${esc(s.scopeLabel)}</span>
            ${statusPill}
            ${pluginTag}
          </div>
          <div class="mcp-card-actions">
            <button type="button" class="btn btn-sm ${s.disabled ? 'primary' : 'ghost'}" data-action="toggle-mcp" data-mcp-id="${esc(s.id)}">
              ${s.disabled ? '启用服务' : '禁用服务'}
            </button>
            <button type="button" class="btn btn-sm danger" data-action="delete-mcp" data-mcp-id="${esc(s.id)}">
              彻底删除
            </button>
          </div>
        </div>
        <div class="mcp-card-cmd" title="${esc(cmdLine)}">${esc(cmdLine || '(无执行命令)')}</div>
        <div class="mcp-card-meta">
          <span title="${esc(s.filePath)}">📄 ${esc(s.filePath)}</span>
          ${dirsHint}
        </div>
      </div>
    `;
  }).join("");
}

async function toggleMcp(mcpId) {
  const item = _mcpServersCache.find((s) => s.id === mcpId);
  if (!item) return;
  const targetDisabled = !item.disabled;
  toast(`正在${targetDisabled ? "禁用" : "启用"} MCP: ${item.name}…`);
  const res = await api().toggle_mcp_server(item.filePath, item.name, targetDisabled);
  if (res?.ok) {
    toast(`已${targetDisabled ? "禁用" : "启用"} ${item.name}（已备份 mcp.json.bak）`);
    await loadMcpServers();
  } else {
    toast(`操作失败: ${res?.error || "未知错误"}`);
  }
}

function promptDeleteMcp(mcpId) {
  const item = _mcpServersCache.find((s) => s.id === mcpId);
  if (!item) return;
  _pendingDeleteMcp = item;

  $("mcpDeleteTargetName").textContent = item.name + (item.isPlugin ? " (插件注入服务)" : "");
  $("mcpDeleteTargetFile").textContent = item.filePath;
  const cleanRow = $("mcpCleanDirsRow");
  if (item.extraDirs && item.extraDirs.length > 0) {
    cleanRow.hidden = false;
    $("mcpCleanDirsCheck").checked = true;
  } else {
    cleanRow.hidden = true;
    $("mcpCleanDirsCheck").checked = false;
  }

  const dlg = $("mcpDeleteDialog");
  if (dlg) dlg.showModal();
}

function closeMcpDeleteDialog() {
  const dlg = $("mcpDeleteDialog");
  if (dlg?.open) dlg.close();
  _pendingDeleteMcp = null;
}

async function confirmDeleteMcp() {
  if (!_pendingDeleteMcp) return;
  const item = _pendingDeleteMcp;
  const cleanDirs = Boolean($("mcpCleanDirsCheck")?.checked);
  closeMcpDeleteDialog();

  toast(`正在彻底删除 MCP 服务: ${item.name}…`);
  const res = await api().delete_mcp_server(item.filePath, item.name, cleanDirs);
  if (res?.ok) {
    let msg = `已彻底删除 ${item.name}（已生成安全备份）`;
    if (res.cleanedDirs && res.cleanedDirs.length > 0) {
      msg += `，并安全归档数据目录`;
    }
    toast(msg);
    await loadMcpServers();
  } else {
    toast(`删除失败: ${res?.error || "未知错误"}`);
  }
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

function paintJobSteps(list, steps) {
  if (!list) return;
  if (!Array.isArray(steps) || !steps.length) {
    list.innerHTML = "";
    list.hidden = true;
    return;
  }
  list.hidden = false;
  const seen = new Set();
  for (const step of steps) {
    const id = String(step?.id || "");
    if (!id) continue;
    seen.add(id);
    let li = null;
    for (const child of list.children) {
      if (child.dataset.stepId === id) {
        li = child;
        break;
      }
    }
    if (!li) {
      li = document.createElement("li");
      li.dataset.stepId = id;
      li.className = "sand-job-item sand-job-enter";
      li.innerHTML = '<span class="sand-pkg-name"></span><span class="sand-pkg-keys"></span>';
      list.appendChild(li);
    }
    const status = step.status || "run";
    li.classList.remove("is-run", "is-done", "is-fail", "is-skip");
    li.classList.add(`is-${status}`);
    const labelEl = li.querySelector(".sand-pkg-name");
    const detailEl = li.querySelector(".sand-pkg-keys");
    if (labelEl) labelEl.textContent = step.label || id;
    if (detailEl) {
      detailEl.textContent = step.detail || "";
      detailEl.hidden = !detailEl.textContent;
    }
  }
  for (const child of [...list.children]) {
    if (!seen.has(child.dataset.stepId)) child.remove();
  }
  list.scrollTop = list.scrollHeight;
}

function showCompactBanner(p) {
  const bar = $("compactBanner");
  if (!bar) return;
  bar.hidden = false;
  const pct = Math.max(0, Math.min(100, Number(p.pct) || 0));
  if ($("compactFill")) $("compactFill").style.width = `${pct}%`;
  if ($("compactText")) $("compactText").textContent = p.message || "正在处理…";
  if ($("compactPct")) $("compactPct").textContent = p.phase === "blocked" || p.phase === "error" ? "" : `${pct}%`;
  bar.classList.toggle("is-done", p.phase === "done");
  bar.classList.toggle("is-error", p.phase === "error" || p.phase === "blocked");
  bar.classList.toggle("is-busy", Boolean(p.busy) && pct < 15 && p.phase !== "done" && p.phase !== "error");
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

const PREF_ACTIVE_TAB = "cursorLauncher.activeTab";

function initTabs() {
  const tabs = document.querySelectorAll(".nav-tab");
  const panels = document.querySelectorAll(".tab-panel");
  if (!tabs.length) return;

  function switchTab(tabId) {
    tabs.forEach((t) => {
      const active = t.dataset.tab === tabId;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", active ? "true" : "false");
    });
    panels.forEach((p) => {
      p.hidden = p.id !== tabId;
      if (!p.hidden) p.classList.add("active");
      else p.classList.remove("active");
    });
    if (tabId === "tabSystem") loadMcpServers();
    try { localStorage.setItem(PREF_ACTIVE_TAB, tabId); } catch {}
  }

  tabs.forEach((tab) => {
    tab.onclick = () => switchTab(tab.dataset.tab);
  });

  try {
    const saved = localStorage.getItem(PREF_ACTIVE_TAB);
    if (saved && document.getElementById(saved)) {
      switchTab(saved);
    }
  } catch {}
}

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("[data-action], [data-copy], [data-kick], .copy-link");
  if (!t) {
    // 点击非菜单区域，关闭所有展开的更多菜单
    document.querySelectorAll(".acc-more-wrap.open").forEach((el) => el.classList.remove("open"));
    return;
  }

  const action = t.dataset.action;
  if (action === "toggle-more") {
    ev.stopPropagation();
    const wrap = t.closest(".acc-more-wrap");
    const wasOpen = wrap?.classList.contains("open");
    document.querySelectorAll(".acc-more-wrap.open").forEach((el) => el.classList.remove("open"));
    if (wrap && !wasOpen) wrap.classList.add("open");
    return;
  }

  // 点击其它任何操作时关闭已展开的菜单
  document.querySelectorAll(".acc-more-wrap.open").forEach((el) => el.classList.remove("open"));

  if (t.dataset.copy !== undefined) return copyText(t.dataset.copy);
  const id = t.dataset.id;
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
  if (action === "launch-cli") return launchCli(id);
  if (action === "remove") {
    if (!confirm("确定删除该账号？")) return;
    await api().remove_account(id);
    toast("已删除");
    await renderAccounts();
    return;
  }
  if (action === "toggle-mcp") return toggleMcp(t.dataset.mcpId);
  if (action === "delete-mcp") return promptDeleteMcp(t.dataset.mcpId);
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
$("btnOpenCliModal").onclick = () => openCliDialog();
$("btnCliCancel").onclick = closeCliDialog;
$("btnCliCancel2").onclick = closeCliDialog;
$("cliDialog").addEventListener("cancel", (ev) => {
  ev.preventDefault();
  closeCliDialog();
});
$("btnLaunchCliDirect").onclick = () => launchCliDirect();
$("btnCliInstallHint").onclick = () => {
  alert("请在 Windows PowerShell 终端中执行官方安装命令：\n\nirm 'https://cursor.com/install?win32=true' | iex");
};
$("btnRefreshMcp")?.addEventListener("click", () => loadMcpServers());
$("btnMcpDeleteCancel")?.addEventListener("click", closeMcpDeleteDialog);
$("btnMcpDeleteCancel2")?.addEventListener("click", closeMcpDeleteDialog);
$("btnConfirmDeleteMcp")?.addEventListener("click", confirmDeleteMcp);
$("mcpDeleteDialog")?.addEventListener("cancel", (ev) => {
  ev.preventDefault();
  closeMcpDeleteDialog();
});
$("btnAdd").onclick = async (ev) => {
  ev.preventDefault();
  const rawInput = ($("tokenInput").value || "").trim();
  if (/^crsr_[A-Za-z0-9]{16,}$/.test(rawInput)) {
    const wantCli = confirm(
      "检测到您输入的是 Cursor Agent API Key（crsr_…）。\n\n" +
      "• 该 Key 仅用于命令行 Agent CLI，无法作为桌面 IDE 客户端的登录凭据（IDE 需要以 eyJ… 或 user_… 开头的 Session Token）。\n\n" +
      "是否现在直接使用此 API Key 启动 Cursor Agent CLI 终端？"
    );
    if (wantCli) {
      closeAddDialog();
      $("tokenInput").value = "";
      return launchCli(null, rawInput);
    }
    return toast("crsr_ Key 仅用于 CLI，IDE 登录需填 Session Token");
  }
  const hasWsFormat = rawInput.includes("::") || rawInput.includes("%3A%3A") || /workoscursorsessiontoken/i.test(rawInput);
  const isPureJwt = /^eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$/.test(rawInput.trim());
  if (isPureJwt && !hasWsFormat) {
    const wantAcc = confirm(
      "⚠️ 风险提示：检测到您输入的是纯 Access Token（裸 JWT）\n\n" +
      "• 掉号风险：纯 acc 仅有约 1 小时有效期，缺乏长效 Session 凭据（WorkosCursorSessionToken），无法正常自动续期。1 小时后 IDE 尝试刷新会话将失败，极易被官方判定异常而导致该账号在云端被强制吊销！\n\n" +
      "• 强烈建议：提供以 user_xxx::eyJ… 开头的完整 Session Token，或直接粘贴整段浏览器 Cookie。\n\n" +
      "是否仍要强制以【临时调试模式】导入该 Token？"
    );
    if (!wantAcc) return;
  }
  const res = await api().import_text(rawInput);
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
    refreshCursorStatus({ update: false });
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
if ($("btnWorkbenchRestore")) $("btnWorkbenchRestore").onclick = () => {
  toast("模型墙请用 YC / Sub2API 扩展面板打。启动器已停用「还原网关补丁」，不会代写。");
};
if ($("btnRecoverCursor")) $("btnRecoverCursor").onclick = () => runDll("uninstall_process_proxy", "正在删除 DLL…", "已删除");
$("btnSavePath").onclick = async () => {
  const res = await api().set_cursor_path($("cursorPath").value);
  toast(res.ok ? "路径已保存" : (res.error || "失败"));
  await refreshCursorStatus({ ctxwin: true, modelUnlock: true, sandStream: true, update: true });
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
if ($("btnSandStreamApplyFull")) $("btnSandStreamApplyFull").onclick = () => runSandStream("apply", "full");
if ($("btnSandStreamApplyStream")) $("btnSandStreamApplyStream").onclick = () => runSandStream("apply", "stream");
if ($("btnSandStreamRestore")) $("btnSandStreamRestore").onclick = () => runSandStream("restore");
if ($("btnSandStreamRefresh")) $("btnSandStreamRefresh").onclick = () => refreshSandStream();
if ($("sandIncludeSubagent")) $("sandIncludeSubagent").onchange = () => refreshSandStream();

async function refreshBotGateway() {
  const pre = $("botGwInfo");
  const copy = $("botGwCopy");
  if (!pre && !copy) return;
  try {
    const res = await api().bot_gateway_status();
    if (!res?.ok) {
      if (pre) pre.textContent = res?.error || "网关状态不可用";
      return;
    }
    const up = res.upstream || {};
    const lines = [
      res.modeEnabled ? "模式：本机网关开" : "模式：关（仍可用 Direct）",
      res.process?.running ? `进程：pid ${res.process.pid}` : "进程：未监听",
      up.configured ? `上游：${up.baseUrlHost} 票已加载` : "上游：还没有 Box 票",
      res.conflictDirect ? "冲突：已检测到 Direct 补丁，不要叠打" : "Direct：未检测到（或无法扫描）",
      res.localStreamUrl ? `本机入口：${res.localStreamUrl}` : "",
      res.note || "",
    ].filter(Boolean);
    if (pre) pre.textContent = lines.join("\n");
  } catch (e) {
    if (pre) pre.textContent = String(e);
  }
}

async function runBotGw(kind) {
  const labels = { provision: "领取并挂路由", enable: "开本机网关", disable: "关本机网关" };
  toast((labels[kind] || kind) + "…");
  try {
    let res;
    if (kind === "provision") res = await api().bot_gateway_provision();
    else if (kind === "enable") res = await api().bot_gateway_enable();
    else res = await api().bot_gateway_disable();
    await refreshBotGateway();
    if (!res?.ok) return toast(res?.error || "失败");
    toast(res.note || res.message || res.cursorHint || "完成");
  } catch (e) {
    toast(String(e));
  }
}

if ($("btnBotGwProvision")) $("btnBotGwProvision").onclick = () => runBotGw("provision");
if ($("btnBotGwEnable")) $("btnBotGwEnable").onclick = () => runBotGw("enable");
if ($("btnBotGwDisable")) $("btnBotGwDisable").onclick = () => runBotGw("disable");
if ($("btnBotGwRefresh")) $("btnBotGwRefresh").onclick = () => refreshBotGateway();
$("sandCatHeader")?.addEventListener("toggle", () => _sandPaintHeaderCat());
$("sandCatPkgs")?.addEventListener("toggle", () => _sandPaintPkgsCat());
$("sandCatRules")?.addEventListener("toggle", () => _sandPaintRulesCat());
document.addEventListener("click", (ev) => {
  const go = ev.target.closest("[data-sand-go='unlock']");
  if (!go) return;
  const tabBtn = document.querySelector(".nav-tab[data-tab='tabSand']");
  if (tabBtn) tabBtn.click();
  const settings = $("settingsFold");
  const emergency = $("emergencyFold");
  const full = $("fullUnlockFold");
  if (settings) settings.open = true;
  if (emergency) emergency.open = true;
  if (full) full.open = true;
  const btn = $("btnModelUnlockApply");
  requestAnimationFrame(() => {
    btn?.scrollIntoView({ block: "center" });
    btn?.focus();
  });
});
if ($("btnWbDiagRefresh")) $("btnWbDiagRefresh").onclick = () => refreshWbDiag({ extras: true });
if ($("btnHealthRefresh")) $("btnHealthRefresh").onclick = () => refreshWbDiag({ extras: true });
if ($("btnAutofix")) $("btnAutofix").onclick = () => runAutofix();
if ($("btnWbDiagFix500k")) $("btnWbDiagFix500k").onclick = () => runWbDiagFix500k();
if ($("btnWbDiagRestore")) $("btnWbDiagRestore").onclick = () => runWbDiagRestore();
if ($("btnIdeGateClose")) {
  $("btnIdeGateClose").onclick = async () => {
    const step = pendingWbNext;
    await closeIde();
    await refreshWbDiag();
    if (!lastCursorStatus?.running && step?.needsClosed && !step.inspectOnly && typeof step.run === "function") {
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
if ($("btnShortcutRefreshIcon")) {
  $("btnShortcutRefreshIcon").onclick = async () => {
    if (!api()?.refresh_shortcut_icons) return toast("当前版本不能刷新图标");
    const res = await api().refresh_shortcut_icons();
    toast(res.ok ? (res.message || "已刷新图标") : (res.error || "刷新失败"));
    await refreshShortcutStatus();
  };
}
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
function nearestScrollY(el) {
  let n = el;
  while (n && n !== document.documentElement) {
    if (n instanceof HTMLElement) {
      const oy = getComputedStyle(n).overflowY;
      if ((oy === "auto" || oy === "scroll") && n.scrollHeight > n.clientHeight + 1) {
        return n;
      }
    }
    n = n.parentElement;
  }
  return null;
}
function layoutSettingsSheet() {
  const fold = document.querySelector(".settings-fold");
  const sheet = fold?.querySelector(".settings-sheet");
  if (!sheet) return;
  if (!fold.open) {
    sheet.style.top = "";
    return;
  }
  const summary = fold.querySelector(":scope > summary");
  const summaryH = summary ? Math.ceil(summary.getBoundingClientRect().height) : 52;
  sheet.style.top = `${summaryH}px`;
}
document.querySelector(".settings-fold")?.addEventListener("toggle", (ev) => {
  const open = Boolean(ev.target.open);
  document.documentElement.classList.toggle("settings-open", open);
  document.body.classList.toggle("settings-open", open);
  requestAnimationFrame(layoutSettingsSheet);
  if (open) {
    refreshWbDiag({ force: false });
  }
});
window.addEventListener("resize", layoutSettingsSheet);
document.querySelector(".settings-fold")?.addEventListener("wheel", (ev) => {
  const fold = ev.currentTarget;
  if (!fold.open) return;
  const sheet = fold.querySelector(".settings-sheet");
  if (!sheet) return;
  const scroller = nearestScrollY(ev.target);
  if (scroller && scroller !== sheet) return;
  const max = sheet.scrollHeight - sheet.clientHeight;
  if (max <= 1) return;
  const next = Math.min(max, Math.max(0, sheet.scrollTop + ev.deltaY));
  if (next === sheet.scrollTop) return;
  sheet.scrollTop = next;
  ev.preventDefault();
}, { passive: false });
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape") return;
  if (document.querySelector("dialog.modal[open]")) return;
  const fold = document.querySelector(".settings-fold");
  if (fold?.open) fold.open = false;
});
$("detailBody").addEventListener("click", (ev) => {
  if (ev.target.id === "btnLoadModelUsage") {
    ev.preventDefault();
    loadModelUsage(ev.target.textContent === "刷新");
  }
  if (ev.target.id === "btnRotateMachine") {
    ev.preventDefault();
    rotateMachine();
  }
  if (ev.target.id === "btnSaveApiKey") {
    ev.preventDefault();
    saveDetailApiKey();
  }
  if (ev.target.id === "btnLaunchCliDetail") {
    ev.preventDefault();
    if (!detailAccountId) return;
    const key = String($("detailApiKey")?.value || "").trim();
    launchCli(detailAccountId, key, Boolean(key));
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
  initTabs();
  if (!api()) {
    const pill = $("loginPill");
    if (pill && boot._tries > 40) pill.textContent = "API 未就绪";
    boot._tries = (boot._tries || 0) + 1;
    return setTimeout(boot, 120);
  }
  try {
    await Promise.all([
      refreshCursorStatus({ ctxwin: true, modelUnlock: true, sandStream: true }),
      loadProxy(),
      renderAccounts(),
      loadMcpServers(),
    ]);
    paintSettingsMeta(lastCursorStatus);
    startStatusWatch();
    await maybePromptShortcuts();
    refreshWbDiag({ extras: false });
    refreshLauncherUpdate();
  } catch (e) {
    const pill = $("loginPill");
    if (pill) pill.textContent = "启动失败";
    toast("界面初始化失败：" + String(e));
  }
}
boot._tries = 0;
boot();
initTabs();
