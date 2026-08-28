const $ = (id) => document.getElementById(id);
const api = () => window.pywebview?.api;

let accounts = [];
let activeAccountId = null;
let detailAccountId = null;
let sessions = [];
let autoKeepIds = new Set();
let keepReasons = {};

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

function ringHtml(label, value, color) {
  const p = pct(value);
  const r = 22;
  const c = 2 * Math.PI * r;
  const off = c * (1 - p / 100);
  return `<div class="ring-item"><div class="ring"><svg width="52" height="52" viewBox="0 0 52 52"><circle class="ring-bg" cx="26" cy="26" r="${r}"></circle><circle class="ring-fg" cx="26" cy="26" r="${r}" stroke="${color}" stroke-dasharray="${c}" stroke-dashoffset="${off}"></circle></svg><div class="ring-val">${p >= 0 ? p : "—"}</div></div><div class="ring-label">${esc(label)}</div></div>`;
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

function renderAccountCard(a) {
  const email = displayEmail(a);
  const initial = (email[0] || "?").toUpperCase();
  const mClass = membershipClass(a.membershipType);
  const badges = [`<span class="tag ${mClass}">${esc(membershipLabel(a.membershipType))}</span>`];
  (a.tags || []).forEach((t) => badges.push(`<span class="tag custom">${esc(t)}</span>`));
  const expiry = a.proExpiryMs ? `周期至 ${fmtDate(a.proExpiryMs)} · ${daysLeft(a.proExpiryMs)}` : "周期未知";
  const stats = `近30天 $${Number(a.periodCostUsd || 0).toFixed(2)} · ${a.requestCount30d || 0}次`;
  const apiPct = a.apiPercentUsed >= 0 ? a.apiPercentUsed : a.includedApiPct;
  const autoPct = a.autoPercentUsed >= 0 ? a.autoPercentUsed : a.includedTotalPct;
  const botPct = a.botPercent;
  const err = a.err ? `<div class="hint" style="color:var(--danger)">${esc(a.err)}</div>` : "";

  return `<article class="acc-card" data-id="${esc(a.id)}">
    <div class="acc-head">
      <input type="checkbox" class="acc-check" data-select="${esc(a.id)}" />
      <div class="acc-avatar">${esc(initial)}</div>
      <div class="acc-meta">
        <div class="acc-email" title="${esc(email)}">${esc(email)}</div>
        <div class="acc-badges">${badges.join("")}${a.hasPassword ? '<span class="tag">🔑</span>' : ""}</div>
        <div class="acc-sub">${esc(expiry)}</div>
        <div class="acc-stats">${esc(stats)}</div>
      </div>
    </div>
    ${err}
    <div class="ring-row">
      ${ringHtml("高级", apiPct, "#ef4444")}
      ${ringHtml("Auto", autoPct, "#22c55e")}
      ${ringHtml("Bot", botPct, "#f59e0b")}
    </div>
    <div class="acc-foot">
      <button class="icon-btn" data-action="detail" data-id="${esc(a.id)}" title="详情">ℹ</button>
      <button class="icon-btn" data-action="refresh" data-id="${esc(a.id)}" title="刷新">↻</button>
      <button class="icon-btn" data-action="devices" data-id="${esc(a.id)}" title="设备">📱</button>
      <button class="btn primary btn-switch" data-action="switch" data-id="${esc(a.id)}">切换</button>
      <button class="icon-btn danger" data-action="remove" data-id="${esc(a.id)}" title="删除">🗑</button>
    </div>
  </article>`;
}

async function renderAccounts() {
  accounts = await api().list_accounts();
  const filters = await api().list_account_filters();
  fillSelect($("filterGroup"), "全部分组", filters.groups || []);
  fillSelect($("filterTag"), "全部标签", filters.tags || []);
  const rows = filteredAccounts();
  $("accGrid").innerHTML = rows.map(renderAccountCard).join("");
  $("emptyAccounts").hidden = rows.length > 0;
}

function fillSelect(el, allLabel, items) {
  const cur = el.value;
  el.innerHTML = `<option value="">${allLabel}</option>` + items.map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
  if ([...el.options].some((o) => o.value === cur)) el.value = cur;
}

async function refreshCursorStatus() {
  const res = await api().cursor_status();
  const pill = $("loginPill");
  if (!res.ok) {
    pill.textContent = "未检测到 Cursor";
    $("cursorInfo").textContent = res.error || "请设置 Cursor 路径";
    return;
  }
  pill.textContent = res.running ? "已登录 · 运行中" : "已登录";
  $("cursorInfo").textContent = `${res.executable || res.path} · v${res.version || "?"}`;
}

async function loadProxy() {
  const res = await api().get_proxy();
  const cfg = res.saved || {};
  $("proxyEnabled").checked = cfg.enabled !== false;
  $("proxyType").value = cfg.proxy_type || cfg.proxyType || "http";
  $("proxyHost").value = cfg.host || "127.0.0.1";
  $("proxyPort").value = cfg.port || 7890;
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
        <div class="k">AccessToken</div><div class="v">${esc((a.token || "").slice(0, 48))}…</div><button class="copy-link" data-copy="${esc(a.token || "")}">复制</button>
        <div class="k">套餐</div><div class="v"><span class="tag ${membershipClass(a.membershipType)}">${esc(membershipLabel(a.membershipType))}</span> ${expiryDays ? `周期至 ${fmtDate(a.proExpiryMs)} · ${expiryDays}` : ""}</div><span></span>
        <div class="k">最近刷新</div><div class="v">${esc(fmtTime(a.lastRefreshed))}</div><span></span>
      </div>
    </div>
    ${progressBlock("费用概览（近30天）", `$${Number(a.periodCostUsd || 0).toFixed(2)}`, "", Math.min(100, (a.periodCostUsd || 0) * 4), "pink", `<span>${a.requestCount30d || 0} 次请求</span>`)}
    ${progressBlock("套餐额度", `$${Number(a.costUsd || 0).toFixed(2)} / $${Number(a.costMaxUsd || 0).toFixed(2)}`, "", a.usagePct >= 0 ? a.usagePct : pct((a.costUsd / Math.max(a.costMaxUsd, 0.01)) * 100), "green", `<span>Auto ${pct(a.autoPercentUsed)}%</span><span>API ${pct(a.apiPercentUsed)}%</span>${a.giftUsd ? `<span>赠送 $${a.giftUsd}</span>` : ""}`)}
    ${a.botPercent >= 0 ? progressBlock("Grok Bot 独立额度", `${pct(a.botPercent)}%`, "", a.botPercent, "teal", a.botResetMs ? `<span>重置于 ${fmtTime(a.botResetMs)}</span>` : "") : ""}
    <div class="detail-section"><h3>用量分类</h3><div class="usage-cards">
      <div class="usage-card"><h4>Auto 模式</h4><div>${pct(a.autoPercentUsed)}%</div><div class="progress-bar" style="margin-top:8px"><div class="progress-fill green" style="width:${pct(a.autoPercentUsed)}%"></div></div><div class="hint">${esc(a.autoModelMessage || "—")}</div></div>
      <div class="usage-card"><h4>高级模型</h4><div>${pct(a.apiPercentUsed)}%</div><div class="progress-bar" style="margin-top:8px"><div class="progress-fill purple" style="width:${pct(a.apiPercentUsed)}%"></div></div><div class="hint">${esc(a.namedModelMessage || "—")}</div></div>
    </div></div>
    ${a.onDemandUsd ? `<div class="detail-section"><div class="progress-head"><strong>按需用量</strong><span>$${Number(a.onDemandUsd).toFixed(2)}</span></div></div>` : ""}
  `;
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

async function launch(accountId) {
  toast("正在切号并启动 IDE…");
  const res = await api().launch_ide(accountId || null);
  toast(res.ok ? "已启动 Cursor（--classic）" : (res.error || "失败"));
  await refreshCursorStatus();
}

async function openDevices(accountId) {
  activeAccountId = accountId;
  $("devicesDialog").showModal();
  await loadSessions();
}

async function loadSessions() {
  if (!activeAccountId) return;
  const res = await api().list_sessions(activeAccountId);
  if (!res.ok) return toast(res.error || "拉取设备失败");
  sessions = res.sessions || [];
  autoKeepIds = new Set(res.autoKeepIds || []);
  keepReasons = res.keepReasons || {};
  renderSessions();
}

function renderSessions() {
  $("sessionCount").textContent = String(sessions.length);
  const body = $("sessionBody");
  body.innerHTML = sessions.map((s) => {
    const protectedRow = s.isCurrent || autoKeepIds.has(s.id);
    const keepChecked = protectedRow;
    return `<div class="device-item ${protectedRow ? "protected" : ""}">
      <input type="checkbox" data-keep="${esc(s.id)}" ${keepChecked ? "checked disabled" : ""} />
      <div>
        <strong>${esc(s.typeLabel)}</strong> ${s.isCurrent ? '<span class="tag">本机</span>' : ""}
        <div class="hint">${esc(keepReasons[s.id] || fmtTime(s.createdAt))}</div>
      </div>
      ${protectedRow ? "" : `<button class="btn sm danger" data-kick="${esc(s.id)}" data-type="${esc(s.sessionType || "")}">Revoke</button>`}
    </div>`;
  }).join("");
  updateKickSummary();
}

function updateKickSummary() {
  const keep = new Set();
  document.querySelectorAll("[data-keep]").forEach((el) => { if (el.checked) keep.add(el.getAttribute("data-keep")); });
  for (const s of sessions) if (s.isCurrent) keep.add(s.id);
  const kickCount = sessions.filter((s) => !keep.has(s.id) && !s.isCurrent).length;
  $("kickSummary").textContent = kickCount ? `将踢掉 ${kickCount} 台，保留 ${keep.size} 台` : "没有需要踢掉的设备";
  $("btnKickOthers").disabled = kickCount === 0;
}

async function kickOthers() {
  if (!activeAccountId) return;
  const keep = [...document.querySelectorAll("[data-keep]")].filter((el) => el.checked).map((el) => el.getAttribute("data-keep"));
  const res = await api().revoke_other_sessions(activeAccountId, keep);
  toast(res.ok ? `已踢 ${(res.revoked || []).length} 台` : (res.error || "失败"));
  await loadSessions();
  await renderAccounts();
}

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("[data-action], [data-copy], [data-kick], .copy-link");
  if (!t) return;
  if (t.dataset.copy !== undefined) return copyText(t.dataset.copy);
  const id = t.dataset.id;
  const action = t.dataset.action;
  if (action === "detail") return openDetail(id);
  if (action === "refresh") return refreshOne(id);
  if (action === "devices") return openDevices(id);
  if (action === "switch") return launch(id);
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

$("searchInput").oninput = () => renderAccounts();
["filterGroup", "filterTag", "filterPlan"].forEach((id) => { $(id).onchange = () => renderAccounts(); });

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
  const wsHint = res.hasWsToken ? "（含 ws token，可用设备管理）" : "（仅 access_token，设备管理需 ws token）";
  toast(`已探测 ${res.email || ""} ${wsHint}`);
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
$("btnSaveProxy").onclick = async () => {
  const res = await api().save_proxy({
    enabled: $("proxyEnabled").checked,
    proxy_type: $("proxyType").value,
    host: $("proxyHost").value,
    port: Number($("proxyPort").value || 7890),
    strict_ssl: false,
  });
  toast(res.ok ? "代理已保存" : (res.error || "失败"));
};
$("btnSavePath").onclick = async () => {
  const res = await api().set_cursor_path($("cursorPath").value);
  toast(res.ok ? "路径已保存" : (res.error || "失败"));
  await refreshCursorStatus();
};
$("detailClose").onclick = () => $("detailDialog").close();
$("devicesClose").onclick = () => $("devicesDialog").close();
$("btnDetailSave").onclick = () => saveDetailMeta();
$("btnDetailRefresh").onclick = () => detailAccountId && refreshOne(detailAccountId);
$("btnDetailSwitch").onclick = () => detailAccountId && launch(detailAccountId);
$("btnDetailDevices").onclick = () => { $("detailDialog").close(); detailAccountId && openDevices(detailAccountId); };
$("btnRefreshSessions").onclick = () => loadSessions();
$("btnKickOthers").onclick = () => kickOthers();

async function boot() {
  if (!api()) return setTimeout(boot, 120);
  await Promise.all([refreshCursorStatus(), loadProxy(), renderAccounts()]);
}
boot();
