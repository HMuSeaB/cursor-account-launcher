# 实施计划：Sand Stream 迁到 Grok Bot Direct（v1.3.1）

**目标**：启动器不再走「有 `runInference` 就不短路」的 1.1.9 核；L2 改为 v131 的 **Grok Bot Direct**（绕过官方 Sand 初始化 / `RunInference`，用 Joe 会话直接打后续 Stream），同时 **保留** 启动器已有的 HDRFIX_V2 + RPC 改写 + managed-local 工具链。完整档 L6 升到 Task V3 / Action V2。  
**发版意向**：v1.3.8 已发出（当时还是条件化 Stream）。本轮代码进下一版，**不 bump**。

## 参考基线（按优先级）

| 来源 | 路径 | 采纳什么 |
|------|------|----------|
| **主** | `Bot/installers/sand_stream_installer_tools_grokbot_direct_v131.py` | 无条件 Joe Direct Stream、剥 `SAND_SESSION_INFERENCE_STREAM_V1`、Task V3、Action V2、maxTokens/1M、Rules/MCP/User Rules |
| **保留** | `launcher/sand_stream.py`（当前 ≈1.1.9 + L6 V2） | 备份/预检/原子写、HDRFIX_V2、RPC 改写、transport→api2、双档 `stream`/`full`、尽力打 + `missing[]` |
| **对照** | `Bot/archives/SandClaimer-源码分享-1.2.1/sand_patch.py` | 只作 401/准入说明；**不迁** `LOCAL_ACTIONS` / `SUBAGENT_LOCAL`（与 Action V2 抢同一锚点） |
| **辅** | [kuk-888/cursor-account-manager](https://github.com/kuk-888/cursor-account-manager) v2.3.11 | Rules Preseed、`push_req_context` 50ms、`supportsSelfSummary` 必须 `false`、锚点正则化（3.18.25）、备份对不上就地反补丁。**不跟**它的 Task V2 / Action V1 / 半装拒绝 |

> v131 文件头写明：官方 `RunInference` 现在拒绝 sand 身份；Grok Bot/Box 的 Direct Stream 仍可用。  
> 1.2.1 Claimer 则相反：apply 时 **剥掉** Joe Direct Stream，指望 `runInference` + RPC。本轮不跟 Claimer 这条核。

---

## 产品约定（已拍板）

用户确认的 6 条，全部落到补丁，不允许用「开 long_running_jobs」之类全局开关代替：

| # | 约定 | 落到哪条补丁 |
|---|------|----------------|
| 1 | 显式选当前**父模型**，并继承 Max / 1M 参数 | L6 Task **V3**：`parentRequestedModelName:e.requestedModel.modelId`（不用解析后的 `i` 变体）；`parentModelParameters`、`parentMaxMode:l`；L2 Joe 会话 `agentTokenLimit` 读 `context`（`1m→1e6` / `300k` / `200k`）；L7 `SAND_MAX_TOKENS_V1` |
| 2 | Task **按原 ID 恢复**，避免 `mode-not-supported` | L6 Action **V2**：去掉 V1 里 `userMessageAction && requestedMode!==AGENT → mode-not-supported`；保留 `SAND_SUBAGENT_RESUME_AGENT_MODE_V1`（`UNSPECIFIED→AGENT`） |
| 3 | 放行 `summarizeAction`、`resumeAction` | Action V2 白名单含这两项，并加 `executePlanAction`、`backgroundTaskCompletionAction` |
| 4 | 后台子代理完成后自动唤醒父会话 | 已有 `SAND_SUBAGENT_COMPLETION_WAKE_V1`（`source==="subagent"`）；本轮不改语义，只保证 Direct 核换完后仍打、仍计 `fullReady` |
| 5 | 子代理内禁止再次派发 Task | Task V3 **保持** `void 0!==e.runOptions.subagentTypeName?void 0:`（子代理 turn 不挂 `taskToolProps`） |
| 6 | **不全局**开 `long_running_jobs` | v131 源码无此字符串；启动器也不写。Shell / Await 行为不靠这个闸 |
| 7 | 长对话不强制自我摘要 | Joe 注入 **保持** `supportsSelfSummary:!1`。CAM v2.3.10 改成 `true` 后，摘要请求走 Bot 路由失败，长对话被截断/串乱；[v2.3.11](https://github.com/kuk-888/cursor-account-manager/releases/tag/v2.3.11) 已改回。单测禁止出现 `supportsSelfSummary:!0` |

其它沿用 v126：

| 档位 | `profile` | 本轮变化 | 就绪标志 |
|------|-----------|----------|----------|
| **仅 Stream** | `stream` | L2 改为 Direct Joe；仍打 L0–L4 + HDRFIX_V2；不打 L5/L6/L7 | `streamReady`（Direct 核必须在；不再要求「条件化」包装） |
| **完整** | `full` | 上 + L5 + 默认 L6（V3/V2）+ L7 | `toolsReady`；勾选 L6 且齐 → `fullReady` |

- 默认按钮仍是 **启用完整**（默认勾选 Task/子代理）。  
- **HDRFIX_V2、L4 RPC：两档仍强制**（v131 没有这两项，且会把它们当成「外源标记」拒装——所以必须迁进启动器，禁止用户再去跑 v131 脚本叠打）。  
- `restore`：一次清掉本模块全部 marker（含 Direct 旧/新字面量、Task V1/V2/V3、Action V1/V2、L7、L8）。  
- 已装启动器条件化 Stream / 已装外置 v131：apply 时先剥再写，不整盘重装 Cursor。

### L2 核：为什么改回无条件 Joe

| 方案 | 说明 |
|------|------|
| **Grok Bot Direct（采用）** | `hre()` 后立刻注入 Joe 会话，**不**包 `if(!(e&&typeof e.runInference==="function"))`；并剥掉 v1.2.7+ 的空会话标记 `SAND_SESSION_INFERENCE_STREAM_V1`（那条会再进 `RunInference`，sand 身份会被拒） |
| 保留 1.1.9 条件化 | 有 `runInference` 的包体会继续走官方初始化，和「绕过第一段协议」目标相反 |
| 跟 1.2.1 彻底删 Joe | 只剩 RPC 改写 + runInference；官方一旦拒 sand，对话直接挂 |

工具链不靠 Joe 的 `getExecutor`，靠 L1 managed-local + L5 move_exec。因此 Direct 与「工具可用」可以同时成立——这是 v131 相对桌面 1.2.2 无条件短路的差别，也是本轮必须 **先保证 L1/L5 仍打上** 的原因。

---

## 补丁分层（实现时按层开关）

```
L0  身份 / 资格 bypass + HDRFIX_V2（Agent→ide，其余 sand）     [已有]
L1  managed-local + local-runtime + agent-host enable/identity [已有]
L2  Grok Bot Direct：无条件 Joe + 剥 SESSION_STREAM + context→agentTokenLimit
L3  transport → _backendTransport（api2）                     [已有]
L4  sand_rpc.js + stream wrap                                 [已有]
L5  move_exec                                                 [已有，完整档]
L6  Task V3 / Action V2 / subagent route·session / resume / wake
L7  maxTokens、Rules+Skills 仍注册 exec、MCP filesystem、User Rules
L8  CAM：Rules Preseed（`_lastPushedRulesProto=[]`）+ push_req_context 超时 10s→50ms
    （glass true-branch 跟启动器现有 GLASSFIX，不另引入 SAND_GLASS_CLIENT_V1）
```

- `stream` = L0–L4（L2=Direct）  
- `full` = 上 + L5；勾选「含 Task/子代理」再加 L6+L7+L8  
- L7/L8 缺项进 `missing` / `complete=false`，**不**绑死 `fullReady`（`fullReady` 仍看 L6）；不把 `ok` 打成 false（对话核仍是 L1+L2）  
- API 不变：`apply(profile="full"|"stream", include_subagent: bool = True)`

### 不迁 / 禁止叠打

- **禁止**启动器再去 `subprocess` 跑 v131 / Claimer 脚本（双备份、外源标记互拒）。  
- **不迁** Claimer 的 `SAND_LOCAL_ACTIONS_V1` / `SAND_SUBAGENT_LOCAL_V1`：和 Action V2 / subagent route 改同一段 `selectTurnRuntime`。若真机仍出现更多 action 的 401，另开一轮扩白名单，不在本轮双补丁。  
- **不迁** Claimer 领取器 UI / `sand_api.py`（资格领取不是启动器职责）。  
- **不迁** 会员伪装 / MAX（仍归 `model_unlock`）。  
- **不引入** `SAND_GLASS_CLIENT_V1`：启动器已有 `SAND_GLASSFIX_V1`，两套玻璃改写叠在一起难还原。  
- **不跟** CAM 的「生命周期缺一条就整单拒绝写入」：启动器仍尽力打 + `missing[]`。  
- **不搬** CAM 的 VSIX / 侧栏账号 UI / 隔离浏览器进控制台（切号、额度、设备启动器已有）。  
- **不把** Task/Action 停在 CAM 的 V2/V1（仍升 V3/V2）。

### CAM 2.3.11 对照（只采加速与教训，不采整包）

源码：`src/sandStream.js` + `src/sandPatcher.js`。[Releases](https://github.com/kuk-888/cursor-account-manager/releases)

| 点 | CAM | 启动器本轮 |
|----|-----|------------|
| Direct Stream | 无条件 Joe，**无** 1M/`agentTokenLimit`，仍硬编码 `Joe`/`cre`/`nre` | 跟 **v131**（含 context→1M） |
| Task / Action | 仍 V2 / V1（V1 还留着 `mode-not-supported`） | 升 **V3 / V2** |
| HDRFIX / RPC | 无 | **保留** |
| Rules Preseed | `_lastPushedRulesProto=void 0` → `[]`，首问 peek 不空等 10s | **迁入 L8**。副作用：首问可能少带规则，后续问正常 |
| push_req_context | `1e4` → `50` ms + `SAND_PUSH_CONTEXT_TIMEOUT_V1` | **迁入 L8**（Preseed 未命中时的安全网） |
| `supportsSelfSummary` | 2.3.10 改 `true` 翻车，2.3.11 改回 `false` | 保持 `!1`，单测锁死 |
| 锚点 | `hre` / `Mn.FL` / `Cre=` 改成捕获标识符，宣称 3.18.9 **和** 3.18.25 | Direct / resume / session **尽量抄正则**；缺命中再补 `657.js`/`61.js`/`675.js` |
| 备份对不上 | 不覆盖新版 Cursor，**就地反补丁** | 启动器 restore 已有备份体系；对不上时应对齐这个策略，本轮若改动小则顺手做，否则单列后续 |
| 半装 | 预检缺条 **拒绝写入** | 不跟 |

---

## 步骤

### 1. 后端：L2 换成 Grok Bot Direct
**依赖**：无  
**改**：`launcher/sand_stream.py`  
- `_direct_stream_injection()` 改为 v131 字面量（无 `runInference` 守卫；含 `agentTokenLimit` 从 `context` 读取；`parameters` 仍用 `(n.parameters\|\|[])` 防空；**`supportsSelfSummary:!1` 不得改成 `!0`**）。  
- 锚点不要写死 `function hre(`：抄 CAM 的 `DIRECT_STREAM_ANCHOR_RE`（捕获函数名），3.18.25 改名后仍能打上。  
- apply 顺序：剥 `SAND_SESSION_INFERENCE_STREAM_V1` → 按 marker 边界剥任何旧 Direct 注入（条件化 / 1.2.2 / 已是 Direct 但字面量旧）→ 在 `DIRECT_STREAM_ANCHOR` 后写入新注入。  
- `remove_patch_from_content` / `_strip_direct_stream_injection` 必须能清：条件化包装、v131 Direct、SESSION_STREAM 残留。  
- `HIT_LABELS["directStream"]` 改为「L2 Grok Bot Direct」。`streamReady`：有 Direct marker 即可，**不再**断言存在 `if(!(e&&typeof e.runInference`。  
**验收**：  
- 合成 `hre()` 片段 apply 后含 Joe 注入、**不含** `runInference` 守卫。  
- 输入为「条件化旧注入」或「仅 SESSION_STREAM 标记」时，apply 后只剩一份新 Direct。  
- restore 后锚点处无任何 SAND_DIRECT / SESSION_STREAM 标记。

### 2. 后端：L6 升到 Task V3 + Action V2
**依赖**：步骤 1  
**改**：`sand_stream.py` 的 `_apply_l6` / `_strip_l6` / `_managed_task_tool_props`  
- `SAND_MANAGED_TASK_TOOL_MARKER` → `/*SAND_MANAGED_TASK_TOOL_V3*/`；保留 V1/V2 字面量只用于迁移和卸载。  
- V3 默认：`parentRequestedModelName:e.requestedModel.modelId`；catalog `[[requested,{slug:requested}],[i,{slug:requested}]]`；`isModelValid:t=>t===requested\|\|t===i`（箭头参数必须是 `t`，不能用 `e` 阴影外层）。  
- **安全阀**：patched 串仍以 `void 0!==e.runOptions.subagentTypeName?void 0:` 开头。  
- Action：新常量 `MANAGED_ACTION_ROUTE_PATCHED` = V2（白名单加 `executePlanAction`，删除 `mode-not-supported` 分支）；V1 字面量仅迁移。  
- resume / wake / subagent route / session：语义不变，strip 时新旧 Action/Task 都要能卸。  
**验收**：  
- `full` + 合成 L6 片段：出现 V3 + V2 marker；出现 `summarizeAction`/`resumeAction`；**不出现** `mode-not-supported`。  
- 含 `subagentTypeName?void 0`；`stream` profile 不含 V3/V2。  
- 输入已是 V1 Action / V2 Task 时，一次 apply 迁到 V2/V3，旧 marker 为 0。

### 3. 后端：L7（1M / Rules / MCP / User Rules）
**依赖**：步骤 1（可与步骤 2 并行写，但合进同一 `apply_patch_to_content`，且仅 `want_l6` 时打）  
**改**：从 v131 原样迁入四组 ORIGINAL/PATCHED（`SAND_MAX_TOKENS_V1`、`SAND_RULES_SKILLS_V4`、`SAND_MCP_FILESYSTEM_V1`、`SAND_USER_RULES_V1`）及对应 restore。  
- `inspect_content_hits` / `classify_readiness` 增加 L7 keys；缺 L7 → `missing` + `complete=false`，不单独把 `ok=false`。  
- 信息区新行「L7 工作区能力」。  
**验收**：  
- 合成 `resolveExtendedUsage({...maxTokens:n.maxTokens})` apply 后含 IIFE 且 marker 在。  
- `injectLocalModeNonFileRules(e){if(!flags.localMode)` 变为 `if(!1&&!flags.localMode)` + marker。  
- restore 四组全部回到 ORIGINAL。

### 4. 后端：L8（Rules Preseed + push_req_context 50ms）
**依赖**：步骤 1（可与 2–3 并行，仅 `want_l6` 时打；`stream` 档不打）  
**改**：从 CAM `sandStream.js` 迁入：  
- `RULES_PRESEED`：`this._lastPushedRulesProto=void 0,this._providerRulesCache=new Map` → `=[]/*SAND_RULES_PRESEED_V1*/,this._providerRulesCache=new Map`  
- `PUSH_CONTEXT_TIMEOUT`：`"[push_req_context]",x=1e4` → `x=50/*SAND_PUSH_CONTEXT_TIMEOUT_V1*/`（已是 50/200/500+marker 的也迁到 50）  
- hits：`rulesPreseed`、`pushContextTimeout`；信息区「L8 首问等待」。  
- 已知 marker 含这两项，避免 CAM 已注入的机器被当成外源拒写。  
**验收**：  
- 合成 void 0 片段 apply 后变为 `=[]` + marker；restore 回 `void 0`。  
- 合成 `1e4` 片段 apply 后为 `50` + marker；restore 回 `1e4`。  
- `stream` profile 不含这两 marker。

### 5. 状态机、外源标记、UI 文案
**依赖**：1–4  
**改**：  
- `MODULE_VERSION` → `1.2.0`（模块语义：Direct + L6 V3 + L8）。  
- 已知 marker 集合纳入 V3/V2/L7/L8；inspect 时 v131 / CAM 留下的这些标记视为**本模块已装**，apply 原地升级，**不要**再当 `external_marker` 拒写。  
- Claimer 独有标记（`LOCAL_ACTIONS` / `MEMBERSHIP_SPOOF` 等）仍按现有 external 逻辑：能剥的剥，剥不了的进 `missing`/`message`，不覆盖写坏。  
- UI（`web/index.html` + `app.js`）：hint 改为「Bot 走 Grok Bot Direct Stream；完整档含工具 + Task V3」；L2 行不再写「条件化」；分层明细加 L7/L8。  
**验收**：  
- 单测：内容已含 V3/Direct 时 `status.installed` 为真且 `external_marker_count==0`。  
- 设置页文案无「条件化 Stream」。

### 6. 测试、文档、发版
**依赖**：1–5  
**改**：  
- `tests/test_sand_stream.py`：替换「条件化不跳过 runInference」用例为「Direct 即使片段里有 runInference 也注入 Joe」。新增 V1→V2 Action 迁移、V2→V3 Task 迁移、安全阀、`supportsSelfSummary:!1`、maxTokens、Preseed/timeout、restore 全清。  
- `dev-references.local.md`：推荐源改为 v131；注明 CAM 只采 L8 与 SelfSummary 教训。  
- 本计划勾选进度。  
- pytest 全绿后再谈 bump / Release。  
**验收**：`python -m pytest tests/test_sand_stream.py -q` 全绿；本机 3.18.9 上完整档 apply 后 `fullReady` 或给出可读 `missingLabels`（缺锚点不装死）。

---

## 风险

| 风险 | 缓解 |
|------|------|
| 无条件 Joe 再次导致工具 `execute` 为 undefined | 完整档必须同时打 L1+L5；单测断言 Direct 与 move_exec 可共存；真机用一次带工具的 Bot 对话确认。若工具仍挂，**回滚 L2 字面量**，不要用开 `long_running_jobs` 补 |
| Direct + L4 RPC 双重改写把请求打到错误后端 | 保持 HDRFIX_V2（Agent 出 ide）；真机抓包：Bot 对话应是 `InferenceService/Stream`，IDE Agent 仍是 `AgentService` |
| 已装 v131 的机器再点启动器 | 把 v131 marker 登记为已知；apply 剥旧写新，禁止「发现外源就整单拒绝」 |
| 已装启动器条件化 L2 | 步骤 1 的剥+写；单测覆盖 |
| Action V2 与 Claimer LOCAL_ACTIONS 同锚 | 本轮不迁 LOCAL_ACTIONS；若机器上已有 Claimer 该标记，restore/apply 先按 Claimer 字面量剥掉再打 V2 |
| `isModelValid` 箭头参数阴影 | 严格抄 v131：`t=>t===...`，单测禁止出现 `e=>e===e.requestedModel` |
| Preseed 让首问少带规则 | 接受（CAM 原文如此）；后续 turn 会被 agent-host 推送覆盖。不要把 timeout 改成 0 |
| 已装 CAM 的机器再点启动器 | L8 marker 登记为已知；不要当外源拒绝 |
| 3.18.25 压缩名变化 | Direct/resume/session 用捕获标识符；仍缺命中再加 `657.js`/`61.js`/`675.js`，不在本轮为对齐 CAM 改成「缺条拒写」 |

---

## 非目标（本轮不做）

- 不代跑 v131 / Claimer / CAM / 1.2.6 外置脚本  
- 不全局开 `long_running_jobs`，不把 `supportsSelfSummary` 改成 `true`  
- 不迁领取器、会员伪装、MAX、`SAND_GLASS_CLIENT_V1`、`LOCAL_ACTIONS` / `SUBAGENT_LOCAL`  
- 不搬 CAM 的 VSIX / 侧栏 UI / 隔离浏览器；不改成「生命周期缺条就整单拒绝」  
- 不在本轮做 mac 专用打包、不改发版脚本以外的账号/切号逻辑

---

## 建议 commit 拆分

1. `feat(sand): L2 Grok Bot Direct stream (strip session/conditional)`  
2. `feat(sand): L6 Task V3 + Action V2 (no mode-not-supported)`  
3. `feat(sand): L7 maxTokens / rules / mcp / user-rules`  
4. `feat(sand): L8 rules preseed + push_req_context 50ms`  
5. `feat(ui): Sand Stream copy for Direct + L7/L8 hits`  
6. `test: sand stream v131/CAM fixtures and migrations`  
7. `docs: plan-sand-stream-v131 + local refs`  
8. `release: v1.3.8 …`（另一次会话，本轮不 bump）

---

## 已确认

1. L2 跟 v131 Direct，不跟 1.1.9 条件化、不跟 1.2.1 删 Joe。  
2. 七条产品约束全部要有对应补丁（含 `supportsSelfSummary:!1`），不用全局闸门代替。  
3. 启动器 HDRFIX_V2 + RPC 保留，两档强制。  
4. CAM 只采 L8 + 锚点正则 + SelfSummary 教训，不采整包脚本、不改「尽力打」。  
5. 本轮先落地计划，**说「开工」后再改代码**。

## 本会话进度

- [x] 步骤 1 L2 Grok Bot Direct（锚点正则、剥 SESSION/条件化、Joe + 1M + `supportsSelfSummary:!1`）
- [x] 步骤 2 L6 Task V3 + Action V2
- [x] 步骤 3 L7 maxTokens / Rules / MCP / User Rules
- [x] 步骤 4 L8 Preseed + push_req_context 50ms
- [x] 步骤 5 状态机 / UI 文案 / 已知 marker
- [x] 步骤 6 单测 + 本地参考；`python -m pytest tests -q` 全绿
- 已随 v1.3.9 发版
- `.cursorignore` 已改为 `/installers/`
