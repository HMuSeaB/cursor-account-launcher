# 实施计划：请求头伪装 / fetch 三件套（兼容性报告补完）

**目标**：把当初那三句——「各版本差、哪些包能改、请求头封装」——落到 Grok Bot 明细里，专门覆盖 **出站请求头伪装** 和 **入站 fetch 回包**。  
**不是**再写一套 fetch/XHR 钩子。

上一轮已经做完的：`sand_report.py` 的 已生效 / 可打未打 / 锚点缺失、包列表、版本建议。请求头只写在 `notes` 和页面 hint 里，**指纹（credentialFingerprint）和会员 fetch 没有独立规则**。

## 三句话分别指什么

| # | 当时的话 | 对应层 | 启动器里已经有的 | 报告里现在缺什么 |
|---|----------|--------|------------------|------------------|
| 1 | 展示 Cursor 各版本的区别 | 本机 vs `ANCHOR_VERSION`（现 3.18.9） | `upgrade.advice` 一整段 | 没按「请求头 / fetch」拆：3.12 没有 agent-host，但 workbench HDRFIX + extensionHost RPC 仍可能打上 |
| 2 | 判断哪些包能改 | `compat.packages` | 有 `canPatch` / `patched`，key 是 `rpcRewrite` 这种内部名 | 看不出哪个包改请求头、哪个改 fetch 回包 |
| 3 | 请求头封装（Claimer 网关补丁、指纹、伪装） | 出站头 + 入站 fetch | L4 `sand_rpc.js`（fetch/http2/electron + `sandHdr`）；HDRFIX_V2；`SAND_AGENT_IDE_V1` 钉指纹对象的 ide；`MODEL_MEMBERSHIP_SPOOF_V1` 在 **完整解锁** 里 deepMerge | 报告只把 RPC 当成一条 marker；旧 RPC 缺 `catalogUrl` 不会标「部分」；指纹规则未列；会员 fetch 未列 |

Claimer 1.2.1 对照（`za/1/8.24/Bot/archives/SandClaimer-源码分享-1.2.1`）：

- `sand_rpc.js`：出站 `x-cursor-client-type=sand`、`x-cursor-client-version=0.18.0`、`x-sand-box-namespace=prod`，并改 `AgentService/Run` → `InferenceService/Stream`。启动器 **已有**，且多了 `catalogUrl`（AvailableModels / GetServerConfig 保持 ide）。
- `sand_patch.py` 的 `SAND_MEMBERSHIP_SNIPPET`：renderer **回包** deepMerge。启动器对应的是 `model_unlock.build_fetch_snippet`，**不是** `sand_stream`。
- `return{headers:…,credentialFingerprint:`：启动器已打 `SAND_AGENT_IDE_V1`，报告没这条。

## 产品约定（已拍板，本轮不许破）

1. **不新写** fetch / XHR 钩子，避免和 `MODEL_MEMBERSHIP_SPOOF` 抢 `globalThis.fetch` 导致黑屏。  
2. **不把** Claimer 会员伪装叠进 `sand_stream` apply / 不绑 `fullReady`。  
3. **不迁** `LOCAL_ACTIONS` / `SUBAGENT_LOCAL`。  
4. 会员 fetch 在报告里 **只读** 现有 marker：`/*MODEL_MEMBERSHIP_SPOOF_V1*/` 或 Claimer 的 `/*SAND_MEMBERSHIP_SPOOF_V1*/`。Grok Bot「启用」按钮不改这一条。  
5. 不新扫磁盘：规则只跑 `inspect_status` 已经读进内存的 JS 快照（workbench + extensionHost + 扩展包）。  
6. `L7/L8` 仍不影响 `fullReady`。本轮新增的会员 fetch **更不能** 影响 `streamReady` / `fullReady`。

## 请求头四条（本轮要变成一等规则）

```
出站 · HDRFIX_V2     workbench header.set("x-cursor-client-type") → Agent=ide，其余 sand
出站 · AGENT_IDE     return{headers,credentialFingerprint} 前钉 ide（指纹对象不跟 Bot 走 sand）
出站 · RPC           extensionHost 封装 fetch/http2/electron.net：sandHdr + 路径改写；目录 URL 跳过
入站 · MEMBERSHIP    完整解锁才有的 fetch 回包 deepMerge（只展示，Grok Bot 不写入）
```

HDRFIX、RPC 规则已在 `RULES` 里。本轮补 AGENT_IDE + MEMBERSHIP，并给 RPC 加「片段质量」判定。

---

## 步骤

### 1. 报告：指纹规则 `agentIde`
**依赖**：无  
**改**：`launcher/sand_report.py`、`launcher/sand_stream.py` 的 `inspect_content_hits`（只加计数，不改 apply）  
- 新 `RuleSpec`：`key=agentIde`，layer `L4`，required=`stream`。  
- marker：`SAND_AGENT_IDE_MARKER`（`/*SAND_AGENT_IDE_V1*/`）。  
- leftover：`SAND_AGENT_IDE_MARKER not in content` 且 `AGENT_IDE_INJECT_RE.search(content)`。  
- `RELATED_NEEDLES["agentIde"] = ("credentialFingerprint:",)`；没有指纹字面量 → `feature_absent`（例如特旧构建）。  
- `inspect_content_hits` 增加 `"agentIde": content.count(SAND_AGENT_IDE_MARKER)`。  
**验收**：  
- 合成 `return{headers:e,credentialFingerprint:` → status `pending`；`apply_patch_to_content` 后 `applied`。  
- 无 `credentialFingerprint` 的纯 workbench 片段 → `missing` + `feature_absent`。  
- `streamReady` / `fullReady` 判定式不因这一条新增而改语义（apply 本来就会打上；只是报告能看见）。

### 2. 报告：RPC 片段质量（旧 RPC 缺 catalogUrl 算部分）
**依赖**：无（可与步骤 1 并行）  
**改**：`sand_report.py` 的 `_rpc_leftover` / 或单独 `_rpc_stale`  
- 无 marker 且文件属于 `RPC_FILE_NAMES` → 仍 `pending`（现状）。  
- 有 `SAND_RPC_REWRITE_MARKER` 但片段里 **没有** `catalogUrl`（或没有 `AvailableModels`）→ `partial`，fix 文案：「旧 RPC 会把目录请求也改成 sand，关 IDE 后重新启用 Grok Bot 会换成带目录守卫的片段」。  
- 有 marker 且含 `catalogUrl` + `x-sand-box-namespace` + `0.18.0` → `applied`。  
**验收**：  
- `extensionHostProcess.js` 仅 marker、无 `catalogUrl` → `partial`。  
- 当前 `launcher/sand_rpc.js` 注入后的合成文本 → `applied`。  
- 现有 `test_rpc_only_counts_extension_host` / `test_rpc_partial_across_host_and_worker` 仍绿。

### 3. 报告：会员 fetch 只读（不写入）
**依赖**：无（可与 1–2 并行）  
**改**：`sand_report.py`  
- 新 `RuleSpec`：`key=membershipFetch`，layer `fetch`，required=`unlock`（新档位：永远 `optional=True`，不进 `summary.required`）。  
- `file_names`：`workbench.desktop.main.js`、`workbench.glass.main.js`。  
- markers：`MARKER_FETCH`（`/*MODEL_MEMBERSHIP_SPOOF_V1*/`）以及 Claimer `/*SAND_MEMBERSHIP_SPOOF_V1*/`。  
- leftover：workbench 上没有上述 marker（表示「完整解锁可以打」，不是「Grok Bot 漏打」）。  
- why：拦截 membership / usage / AvailableModels **回包** deepMerge；与 L4 出站 `sandHdr` 不是同一条钩子。  
- `adjust_compat_scope`：`required=="unlock"` 一律 optional。  
**验收**：  
- 空 workbench → `pending` 且 `optional`；`summary.missing` **不含** 这条标题。  
- 含 `MODEL_MEMBERSHIP_SPOOF_V1` → `applied` 且 optional。  
- 单测禁止 `sand_stream.apply_patch_to_content` 往内容里写入 `MODEL_MEMBERSHIP_SPOOF`。

### 4. 版本差：请求头层矩阵
**依赖**：1–3（用得到新规则的 missKind）  
**改**：`evaluate_compat` 增加 `headerLayers`（或扩展 `upgrade`），`web/app.js` 的 `sandCompatHint` / `sandUpgradeAdvice`  
结构示例：

```json
"headerLayers": {
  "relation": "older|match|newer",
  "rows": [
    {"key": "hdrfixV2", "title": "workbench 身份分流", "status": "…", "onOlder": "3.12 通常可打"},
    {"key": "rpcRewrite", "title": "extensionHost 出站封装", "status": "…", "onOlder": "3.12 仍有 extensionHost"},
    {"key": "agentIde", "title": "指纹对象钉 ide", "status": "…", "onOlder": "有 credentialFingerprint 才打得上"},
    {"key": "membershipFetch", "title": "会员/目录回包", "status": "…", "onOlder": "完整解锁才打，不归 Grok Bot"}
  ]
}
```

- `upgrade.advice` 保留；hint 增加一行：「出站伪装看 HDRFIX/RPC/指纹；回包伪装看完整解锁，不要点 Grok Bot 去补会员 fetch。」  
**验收**：  
- `cursor_version=3.12.30` 时 `headerLayers.relation=older`；L1 仍是 `package_absent`；`rpcRewrite` 只要扫到 `extensionHostProcess.js` 就不是「包不存在」。  
- 页面「版本与补丁明细」能看到这四行，而不是只靠底部 notes。

### 5. 可改包：按职责分组
**依赖**：1–3  
**改**：`evaluate_compat` 的 `packages[]` 增加 `roles: ["header"|"fetch"|"other"]`；`paintSandStream`  
- header：包的 `canPatch`/`patched` 与 `hdrfixV2|agentIde|rpcRewrite|streamWrap` 相交。  
- fetch：相交 `membershipFetch`。  
- UI：可改包列表 key 用中文短名（身份分流 / 指纹 / RPC封装 / 会员回包），不要直接甩 `rpcRewrite`。  
- 无锚点的包仍折叠成「另有 N 个包没有对应锚点」，避免设置页再变长。  
**验收**：  
- `extensionHostProcess.js` 未打 RPC → 标签「可打」且 roles 含 `header`，keys 文案含「RPC封装」。  
- workbench 仅 HDRFIX leftover、无会员 marker → roles 含 `header`，会员那条因 optional 不把整包刷成「必须打完整解锁」。

### 6. 测试
**依赖**：1–5  
**改**：`tests/test_sand_report.py`（不碰真实安装）  
- 步骤 1–5 的合成用例。  
- 断言 `apply_patch_to_content` 后文本 **不含** `MODEL_MEMBERSHIP_SPOOF` / `SAND_MEMBERSHIP_SPOOF`。  
- 断言 RPC 缺 `catalogUrl` → `partial`。  
**验收**：`python -m pytest tests/test_sand_report.py tests/test_sand_stream.py -q` 全绿。

---

## 风险

| 风险 | 缓解 |
|------|------|
| 把会员 fetch 做成必打，用户会去点完整解锁搞坏模型墙 | `required=unlock` + optional；文案写明「仅完整解锁」 |
| 新规则再扫一遍 40MB workbench | 只用已有 snaps；禁止在 `evaluate_compat` 里 `read_text` |
| RPC leftover 对空 `extensionHostProcess.js` 仍 pending（现状单测） | 保持；质量检查只在 **已有 marker** 时看 catalogUrl |
| 设置页再变卡 | 不新增 DOM 区块到折叠外；四条并进现有规则列表；包列表仍只渲染 live |
| 有人理解成「再写 fetch 钩子」 | 步骤 3 验收锁死 apply 不写会员 snippet |

## 非目标

- 不新写 fetch/XHR，不改 `sand_rpc.js` 的 sandHdr 语义（除非步骤 2 发现现用片段真缺 catalogUrl——以仓库 `launcher/sand_rpc.js` 为准，现已有）  
- 不把会员伪装打进 Grok Bot 启用  
- 不迁 Claimer LOCAL_ACTIONS  
- 不在本轮做 1.3.11 发版 / bump  
- 不把 JA3 / 网关 TLS 指纹搬进启动器（Claimer 的「指纹」在客户端是 `credentialFingerprint` 对象，不是 TLS）

## 建议改动文件

1. `launcher/sand_report.py` — 规则 + headerLayers + package roles  
2. `launcher/sand_stream.py` — 仅 `inspect_content_hits` 加 `agentIde`  
3. `web/app.js` — 包 key 中文、hint 用 headerLayers  
4. `web/index.html` — 明细区一句「出站 vs 回包」  
5. `tests/test_sand_report.py`

## 建议 commit 拆分

1. `feat(sand-report): agentIde fingerprint rule`  
2. `fix(sand-report): stale RPC without catalogUrl is partial`  
3. `feat(sand-report): read-only membership fetch status`  
4. `feat(ui): header layer matrix + package roles`  
5. `test: sand header/fetch report cases`

## 已确认 / 待你说开工

已确认（沿用上一轮拍板 + 本次澄清）：三件事都落在 **报告**，核心是请求头伪装和 fetch；不新写钩子。  

待开工后再改代码。说「开工」即按步骤 1→6 做。

## 本会话进度

- [x] 步骤 1 `agentIde` 规则 + `inspect_content_hits`
- [x] 步骤 2 旧 RPC 缺 catalogUrl → partial
- [x] 步骤 3 会员 fetch 只读 `required=unlock`
- [x] 步骤 4 `headerLayers` + 明细区四行
- [x] 步骤 5 包 `roles` + 中文短名
- [x] 步骤 6 `python -m pytest tests -q` → 150 passed
