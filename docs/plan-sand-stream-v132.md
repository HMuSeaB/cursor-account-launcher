# 实施计划：Sand-Stream-Installer 1.3.2 对照与兼容（登记 / 剥离 / 叠打纪律）

**对象**：`za/1/8.24/Bot/archives/Sand-Stream-Installer-v1.3.2-fixed(1)`（内层 `sand_stream_installer.py`，`TOOL_VERSION = "1.3.2-macos-seal.1"`；外层 `(1)` 只是重复下载解包壳）。  
**对照**：`Bot/installers/sand_stream_installer_tools_grokbot_direct_v131.py`（v1.3.1）+ 本仓库 `launcher/sand_stream.py`（模块 1.3.0）+ 发版启动器 1.3.12。  
**用途**：启动器对 1.3.2 新 marker 从「零认知」改为**认识、能报、能剥（剥不了进 missing，不覆盖写坏）**；同锚点先剥再打。**不引入** 1.3.2 的激进语义。  
**发版意向**：`MODULE_VERSION` → `1.3.1`；启动器版本 **不 bump**。

---

## 审核要点（请先拍这几条）

1. **范围**：只做「已知 marker 登记 + status 残留报告 + restore/apply 剥离」，不改 L2/L6 核心、不加新打点。
2. **呈现方式**：1.3.2 残留在 status 用一个汇总字段 `installer132`，**不**往 sand_report 20 条规则里加 9 条（备选见待确认 2）。
3. **可选项不立项**：MULTITASK 白名单扩展、state.vscdb 子代理目录，本轮都不做，挂触发条件（见「可选项」）。
4. **restore 默认自动剥** 1.3.2 字面量；剥不掉的进 message 并指引「先跑 Sand-Stream-Installer 的卸载」。
5. 结论基线：1.3.2 的外来检测/卸载能力是 v1.3.1 的**真子集**（无 KNOWN 注册表），两安装器注入代码均**无外联**（唯一 URL 常量 `SAND_ONBOARDING_URL` 未被引用）。

---

## 参考基线

| 来源 | 路径 | 采纳什么 |
|------|------|----------|
| **主（剥离源）** | `archives/Sand-Stream-Installer-v1.3.2-fixed(1)/.../sand_stream_installer.py`（下称 **A**） | 9 组 ORIGINAL/PATCHED 字面量（A:299-433 原样抄）、SUBAGENT_TASK 动态正则形态（A:717-747、`SUBAGENT_TASK_PATCH_RE`）、1.3.2 Direct 注入体（A:436-469，作旧字面量剥） |
| **对照（上一代）** | `installers/sand_stream_installer_tools_grokbot_direct_v131.py` | 确认「删了什么」（L7/Task V3/Action V2/resume/wake），不搬任何补丁 |
| **现状** | `launcher/sand_stream.py` | 现有 external/KC 机制、`_strip_direct_stream_injection`、move_exec 三形态 restore、尽力打 + `missing[]` 全部沿用 |

---

## 现状问题（本轮动机）

| # | 问题 | 后果 |
|---|------|------|
| 1 | 1.3.2 的 9 个新 marker 启动器全项目零认知；external 检测只覆盖 CLIENT/ELIGIBILITY guard + KC | status 解释不了「L2/L6 为什么缺」；报告无残留提示 |
| 2 | 同锚冲突：`taskToolProps:void 0`（1.3.2 SUBAGENT_TASK ↔ 启动器 Task V3）、action route 区（BACKGROUND_COMPLETION ↔ 启动器 Action V2）、`hre(` Direct 锚 | 已装 1.3.2 再点启动器：directStream/L6 进 missing，核心层报缺项，apply 失败或半装；反向 1.3.2 计数门拒绝 |
| 3 | restore 兜底折叠只罩 `"(ide|sand|glass)"/*SAND…*/` **尾缀**形态；1.3.2 的 BACKGROUND/RUN_OPTIONS/MULTITASK 是 marker **中插**（`"!1"/*…*/?"…"`） | 现有 restore 清不掉这些残留 |
| 4 | 1.3.2 的 MOVE_EXEC 括号形态 `p=(!0/*SAND_MOVE_EXEC_V1*/)`：marker 同串已在 `sand_stream.py:74-75` 并认，但 restore 三形态（1230-1244、1788）是否含括号变体未验证 | 残留可能剥不掉 |
| 5 | 1.3.2 Direct 注入（无 `agentTokenLimit`、无 4.6/4.5 互斥）不在启动器旧字面量剥离清单 | 叠打时同锚双 Direct |

---

## Marker 对照表（实施时以 A 源码原文为准，此处为形态备忘）

| Marker（A 行号） | ORIGINAL → PATCHED 形态 | 与启动器关系 |
|------|------|------|
| `SAND_MULTITASK_ROUTE_V1`（A:49、299-312） | mode 检查加 `userMessageAction` 前缀并放行 MULTITASK，marker 插在 `?` 前；有 LEGACY（无前缀）变体 | 新打点，**不搬**；真机需要时按 Action V2 白名单方式自研（OPT-A） |
| `SAND_BACKGROUND_COMPLETION_V1`（A:55、313-332） | 现行 `"!1"+marker+?"action-not-supported"` = actionCase **全放行**；LEGACY/V2 反而是白名单（userMessage+backgroundTaskCompletion） | **不搬**：启动器 Action V2 已白名单含 backgroundTaskCompletion |
| `SAND_SUBAGENT_RUN_OPTIONS_V1`（A:54、333-340） | `hasUnsupportedRunOptions` 门改 `"!1"` 恒假 | **不搬**：会废掉「子代理禁再派发」（`subagentTypeName` 守卫，约定 #5） |
| `SAND_SUBAGENT_FEATURES_V1`（A:50、360-381） | 特性 const 追加 `useClientSideSubagent/enableMultitaskMode/defaultSubagentsRunInBackground` + 尾缀 marker；LEGACY 还含 `longRunningJobs:!0`、`enableAwaitForSubagents` | **不搬**（useClientSideSubagent 启动器 L6 session 已有；LEGACY 含全局闸） |
| `SAND_SUBAGENT_CAPTURE_V1`（A:51、382-389） | `function(e,t){` → `function(e,t,H){/*m*/var n,o;`（捕获父 inferenceClient） | **不搬**；是 OPT-B 的前置技巧，记入笔记即可 |
| `SAND_SUBAGENT_CONFIG_V1`（A:52、390-395） | `d=new PF;return Object.assign(` → `d=new PF;let P;/*m*/return P=Object.assign(` | 同上 |
| （未命名 INVOKE 对，A:396-401） | `}(t,e.agentToolsClient),` → `}(t,e.agentToolsClient,e.inferenceClient),` | 同上（无独立 marker，靠 CAPTURE/CONFIG marker 定位） |
| `SAND_SUBAGENT_TASK_V1`（A:53、402-414、717-747） | `taskToolProps:void 0` → 巨对象（父模型+state.vscdb 动态目录 IIFE；LEGACY 硬编码 claude-fable-5/kimi-k2.5；`isModelBlocked:()=>!1`、无 `subagentTypeName` 守卫） | **不搬**：与已拍板 Task V3「锁父模型+禁再派发」相反；restore 用骨架正则剥 |
| `SAND_GLASS_OVERRIDE_V1`（A:56、426-433） | `isGlass?"sand":"sand"/*m*/`（真分支也 sand） | **不搬**：已有 `SAND_GLASSFIX_V1`；restore 回 ORIGINAL `isGlass?"glass":"ide"` |
| `SAND_MOVE_EXEC_V1`（A:48、355-359） | `p=(!0/*SAND_MOVE_EXEC_V1*/)`；LEGACY `p=!0;/*m*/` | marker 同串已并认（74-75）；**只补括号形态 restore** |
| （Direct 注入，A:436-469） | 同 v131 Joe Direct 但**无 `agentTokenLimit`**、无 4.6/4.5 互斥 | 加入 `_strip_direct_stream_injection` 旧字面量清单 |

> 另：1.3.2 的 CLIENT/ELIGIBILITY/MOVE_EXEC marker 与启动器**同串**，不构成外来冲突；GLASS_OVERRIDE 的 REMOVE 正则（A:426-433）可直接参考。

---

## 产品约定（沿用已拍板，本轮不许破）

1. 不全局开 `longRunningJobs`；不放回 `mode-not-supported`；`supportsSelfSummary:!1`。
2. 子代理禁再派发 Task（`subagentTypeName` 守卫不撤）→ 这是否决 1.3.2 RUN_OPTIONS/SUBAGENT_TASK 的直接依据。
3. 尽力打 + `missing[]`，不跟「缺条拒写」；外来标记能剥则剥、剥不了进 missing，禁止覆盖写坏。
4. 会员伪装/MAX 归 `model_unlock`；领取不进启动器；不 subprocess 代跑任何外置脚本。

---

## 方案范围

| 做 | 不做（理由） |
|----|----|
| 登记 9 个新 marker + 残留 status 字段 | BACKGROUND_COMPLETION 全放行（与白名单约定冲突） |
| restore/apply 剥离 1.3.2 字面量（含 Direct、MOVE_EXEC 括号、TASK 动态正则） | SUBAGENT_RUN_OPTIONS / SUBAGENT_TASK / CAPTURE / CONFIG / FEATURES 打点（语义相反 + 守卫缺失） |
| status/UI 叠打指引 | GLASS_OVERRIDE 打点（已有 GLASSFIX） |
| 文档 + 单测 | 严格计数门、macOS codesign、SUDO_USER、MAX_TOKENS（启动器已有更强 L7）、3.19（1.3.2 也没有） |

---

## 步骤

### 1. 已知 marker 登记 + 残留检测
**改**：`launcher/sand_stream.py`  
- 新常量组 `SAND_V132_MARKERS`（9 个：MULTITASK_ROUTE / BACKGROUND_COMPLETION / SUBAGENT_FEATURES / CAPTURE / CONFIG / TASK / RUN_OPTIONS / GLASS_OVERRIDE；MOVE_EXEC 已在 74-75 并认，不重复登记）。  
- `_bytes_may_have_sand_patch`（2419-2420）与 `_build_uninstall_plan` 的扫描集合加入这 9 个。  
- `inspect_status` / `_status_payload` 增加 `installer132: {detected, counts, files, message}`；**不**计入 `external_marker_count`、不触发 apply 拒写。  
**验收**：合成含 BACKGROUND_COMPLETION + SUBAGENT_TASK 的片段 → `installer132.detected=True`、counts/files 正确；现网（无残留）status 与本轮前逐字段一致。

### 2. restore：1.3.2 字面量剥离
**改**：`remove_patch_from_content`（1700-1824）+ `_strip_direct_stream_injection`  
- 9 组 ORIGINAL/PATCHED 从 A:299-433 原样抄（串替换）；SUBAGENT_TASK 动态版用骨架正则（参照 A 的 `SUBAGENT_TASK_PATCH_RE`：`taskToolProps:\{.*?\}/*SAND_SUBAGENT_TASK_V1*/`，DOTALL），LEGACY/V130 两版按字面量。  
- GLASS_OVERRIDE：`isGlass?"sand":"sand"/*m*/` → 回 ORIGINAL（待确认 3 拍终点）。  
- MOVE_EXEC 括号形态 `p=(!0/*SAND_MOVE_EXEC_V1*/)` 补进现有三形态（1230-1244、1788）；LEGACY `p=!0;/*m*/` 一并核。  
- 1.3.2 Direct 注入体加入旧字面量剥离清单（与 v131 条件化/1.2.2/SESSION_STREAM 并列）。  
- 剥不掉 → 计入 restore 结果 message（文件名 + marker 名），不覆盖写坏。  
**验收**：9 组 roundtrip：A 字面量进 → restore 后回 ORIGINAL、无任何 `SAND_`/`KC_` 残留；与自家补丁共存的合成片段 → restore 只剥 1.3.2、自家 marker 完好；SUBAGENT_TASK 动态 IIFE 换一组模型 slug 仍能剥。

### 3. apply：同锚先剥再打 + 可读降级
**改**：`apply_patch_to_content` / `apply()` 路径  
- 每个目标文件先跑步骤 2 的 1.3.2 剥离（并入现有「剥旧写新」顺序，先于自家 ORIGINAL 匹配）。  
- 剥成功 → 正常打自家 Task V3 / Action V2 / Direct；剥不掉 → 该层进 `missing`/`missingLabels`，message 写明「1.3.2 残留占用 taskToolProps / action route / hre 锚点，先运行 Sand-Stream-Installer 的卸载，或用还原再启用」。  
- 1.3.2 marker 不算 `external_marker`（与 v131/CAM 同待遇）。  
**验收**：合成「1.3.2 已打 taskToolProps + `!1` action 门」片段 apply → 自家 V3/V2 上、无叠加写坏、`missing` 不含已剥项；「剥不掉」分支 → 核心层缺才 `ok=false`，L6 缺只 `complete=false` + 可读 message。

### 4. 报告 / UI 文案
**改**：`_status_payload`、`web/app.js`（Grok Bot 区）、`dev-references.local.md`  
- 残留行：检测到 1.3.2（macos-seal.1）补丁 N 处（列文件），指引按叠打矩阵处理。  
- hint 补一句：已装启动器不要跑 1.3.2；要换启动器先跑它的卸载。  
**验收**：mock status 透出 `installer132`；页面无「代跑外置脚本」类指引。

### 5. 文档
**改**：`docs/notes-sandclaimer-131.md` 增补「1.3.2 对照」小节（删了什么/换什么/安全子集/无外联结论），或单开 `notes-installer-132.md`（待确认 4）；本计划勾进度。

### 6. 测试与收尾
**改**：`tests/test_sand_stream.py` 全部合成用例；`python -m pytest tests -q` 全绿；`MODULE_VERSION` → `1.3.1`，不写 Release。

### 可选项（默认不立项，挂触发条件）

| 项 | 内容 | 触发条件 |
|----|------|----------|
| OPT-A | MULTITASK 白名单式扩展（形态参考 A:299-312，但做成自家 marker、并入 Action V2 家族，保留 actionCase 限定） | 真机出现 MULTITASK `mode-not-supported` |
| OPT-B | state.vscdb 只读子代理模型目录（`model_unlock.py` 已读同一 ItemTable key，读法可复用）+ 父 inferenceClient 捕获（A:382-401） | 产品决定放开「子代理选任意启用模型」；需重拍约定 #5，另开计划 |

---

## 叠打矩阵（写进 notes / UI hint）

| 机器状态 | 现状 | 本轮后 |
|----------|------|--------|
| 只用启动器 | — | 不变；**不要**跑 1.3.2（同锚互斥，它大概率计数门拒绝或叠写） |
| 已装 1.3.2 → 点启动器 | L2/L6 锚点被占，核心层报缺项，失败或半装 | status 报残留；apply 先剥再打；剥不掉给可读指引 |
| 已装启动器 → 跑 1.3.2 install | 计数门大概率拒绝（锚点已被改） | 文案明确「不要跑」；真被装上 → 启动器 restore 可剥 |
| 想从 1.3.2 换启动器 | 无路径 | 首选：1.3.2 自己 uninstall（能清自己）→ 启动器启用；兜底：启动器 restore 自动剥 |

---

## 风险

| 风险 | 缓解 |
|------|------|
| 字面量抄错（A 压缩名随构建变） | 以 A 源码为准 + roundtrip 单测锁；正则剥不掉宁进 missing，不覆盖 |
| GLASS_OVERRIDE 与自家 GLASSFIX/client marker 互相咬 | restore 顺序固定：先剥 GLASS_OVERRIDE → 再走自家 client/GLASSFIX 还原；单测锁顺序 |
| SUBAGENT_TASK 动态 IIFE 每台机器目录不同 | 只按 marker 定界的骨架正则剥，不比对目录内容 |
| 1.3.2 Direct 与自家 Direct 同锚双写 | apply 剥离清单先于写入；单测「1.3.2 Direct 进 → 只剩自家一份」 |
| 误把同串 MOVE_EXEC/CLIENT marker 当外来 | 同串视为自家；只按**字面量形态**区分（括号变体只进 restore 清单） |

---

## 非目标（本轮不做）

- 不搬 1.3.2 任何新打点（BACKGROUND_COMPLETION / RUN_OPTIONS / SUBAGENT_* / GLASS_OVERRIDE / MULTITASK_ROUTE）  
- 不引入严格计数门 / 缺条拒写；不做 macOS codesign / SUDO_USER / `state.vscdb` 写入  
- 不迁 MAX_TOKENS（已有 L7）；不做 3.19（1.3.2 亦无）  
- 不代跑 1.3.2 / 不 subprocess 外置脚本  
- 不 bump 启动器版本，不改账号 / 切号 / 额度逻辑

---

## 建议 commit 拆分

1. `feat(sand): register installer-1.3.2 markers + residue status`  
2. `feat(sand): strip installer-1.3.2 literals on restore/apply`  
3. `fix(sand): move_exec bracketed literal restore`  
4. `feat(ui): installer-1.3.2 residue hint + stacking guide`  
5. `test: installer-1.3.2 fixtures and roundtrips`  
6. `docs: plan-sand-stream-v132 + notes`

---

## 已确认（2026-09-06 拍板）

1. **范围**：只做登记 + 剥离 + 指引，OPT-A/OPT-B 不立项（挂触发条件）。  
2. **残留呈现**：status 汇总字段 `installer132`，不加 sand_report 规则。  
3. **GLASS_OVERRIDE 还原终点**：回 ORIGINAL `isGlass?"glass":"ide"`。  
4. **notes 落点**：**单开 `notes-installer-132.md`**。  
5. **剥离默认值**：apply/restore 都默认自动剥，剥不掉再提示。

## 本会话进度

- [x] 步骤 1 登记 + 残留检测（`SAND_V132_MARKERS` / `inspect_v132_hits` / status `installer132`）  
- [x] 步骤 2 restore 剥离（`_strip_v132` 13 组字面量对 + TASK 骨架正则 + GLASS_OVERRIDE 正则 + MOVE_EXEC 括号/分号形态）  
- [x] 步骤 3 apply 先剥再打（`apply_patch_to_content` 顶部剥 1.3.2；1.3.2 Direct == 启动器 legacy 注入，现有清单天然覆盖）  
- [x] 步骤 4 报告 / UI（`_status_payload.installer132` + web/app.js 残留行；apply/restore 后仍检出残留则追加指引）  
- [x] 步骤 5 文档（单开 [notes-installer-132.md](notes-installer-132.md) + dev-references 加行）  
- [x] 步骤 6 测试 + `MODULE_VERSION` 1.3.1（`tests/test_sand_stream.py` 新增 9 例；`pytest tests -q` 210 passed）

**实施纪要**：① 1.3.2 的 Direct 注入体与启动器 `_legacy_direct_stream_injection()` 逐字相同（A:436-469 已核对），无需新增剥离对；② `PatchStatus.installer132` 用 `_empty_installer132()` 默认形状，消费端可直接读 `detected`；③ SUBAGENT_TASK 动态目录只按 marker 定界骨架正则剥（LEGACY/V130 变体同被覆盖），不比对目录内容。
