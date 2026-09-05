# 实施计划：Sand Stream 双档迁入（1.1.9 工具安全 + 可选子代理）

**目标**：启动器内可选「仅 Stream」或「完整（工具可用）」；尽量打补丁，打不全返回 `missing[]` 明细。  
**发版意向**：v1.3.8（拆 commit 后再 bump）。

## 参考基线（按优先级）

| 来源 | 路径 | 采纳什么 |
|------|------|----------|
| **主** | `Bot/archives/SandClaimer-源码分享-1.1.9/sand_patch.py` + `sand_rpc.js` | 条件化 Stream、transport→api2、move_exec、HDRFIX_V2、拒半装经验 |
| **辅** | `Bot/installers/sand_stream_v1.2.6_subagent.py` | Task V2 / subagent route·session / action / resume / wake（完整档第二层） |
| **现状** | `launcher/sand_stream.py`（≈v1.2.2） | 备份/预检/原子写保留；**废弃无条件 Joe 短路**（会砍工具链） |

> 1.1.0–1.1.3 / 桌面 1.2.2 无条件 `hre()→Joe` 会导致工具 `execute` 为 undefined。完整档必须以 1.1.9「有 `runInference` 则不短路」为准。

---

## 产品约定（已拍板）

| 档位 | `profile` | 内容 | 就绪标志 |
|------|-----------|------|----------|
| **仅 Stream** | `stream` | L0–L4（含 RPC 改写）+ **HDRFIX_V2** | `streamReady` |
| **完整** | `full` | L0–L5 + 默认 L6；UI 可**取消勾选**「含 Task/子代理」→ 只打到 L5 | `toolsReady`；勾选且 L6 齐 → `fullReady` |

- 默认按钮：**启用完整**（默认勾选 L6）；次要：**仅 Stream**。  
- **L4**：两档都打（「仅 Stream」也要协议改写，否则容易只改路径却仍打错后端）。  
- **HDRFIX_V2：两档强制**（见下）。  
- **尽力打**：锚点命中多少写多少；写后扫描 → `hits` + `missing`；**预检/写盘失败仍回滚**；缺项不整单回滚。  
- 缺「对话级」核心（如无 managed-local / 无 Stream 通路）→ `ok=false`。  
- 仅缺 Task/wake 等 → `ok=true, complete=false` + 明细。  
- 版本：不硬拒非 3.18.9；`versionHint` 提示锚点按 3.18.9。  
- `restore`：一次清掉本模块全部 marker（含 RPC 片段），不保留半档。

### client-type：两档强制 HDRFIX_V2

`AgentService` / `agent.v1` → **`ide`**；其余 → **`sand`**。

| 方案 | 说明 |
|------|------|
| **强制 V2（采用）** | 与 1.1.9 一致；Agent 管线不背 sand 头，少「连不上 / 404 / 模式拒」类坑；两档同一套身份逻辑，好维护 |
| 仅 Stream 用全局 sand | 实现短一点，但 Agent 路径带 sand 头易和官方路由打架；和完整档行为分裂，排错成本高 |

「仅 Stream」只表示 **不装 move_exec / 不装 L6**，不表示换一套 client-type。

---

## 补丁分层（实现时按层开关）

```
L0  身份 / 资格 bypass /（可选会员伪装：本轮可不做，留给 model_unlock）
L1  managed-local + local-runtime + agent-host enable/identity
L2  条件化 direct Stream（仅 !runInference）— 取代 v1.2.2 无条件注入
L3  transport → _backendTransport（api2）— 避免 Agent 后端 404
L4  sand_rpc.js 注入 + stream wrap — Agent Run ↔ Inference Stream 协议改写
L5  move_exec — 工具执行器（完整档必打）
L6  v1.2.6：taskTool V2 / subagent route·session / action / resume / wake
```

- `stream` = L0–L4 + HDRFIX_V2（L4 缺失进 missing，不阻塞 L1–L3 已写入）  
- `full` = L0–L5 + HDRFIX_V2；若勾选「含 Task/子代理」再加 L6（L6 缺失只影响 `fullReady`；L5 中则仍可 `toolsReady`）  
- API：`apply(profile="full"|"stream", include_subagent: bool = True)`（仅 `full` 时 `include_subagent` 有效）

---

## 步骤

### 1. 后端：用 1.1.9 替换危险的 Stream 核
**依赖**：无  
**改**：`sand_stream.py`  
- 去掉无条件 `_direct_stream_injection`；改为 1.1.9 条件化版本，并卸载旧字面量  
- 迁入 move_exec、transport host swaps、HDRFIX_V2（至少 full）  
- 嵌入 / 注入 `sand_rpc.js`（标记 `SAND_RPC_REWRITE_*`），apply/remove 可逆  
- `apply_patch_to_content(content, profile)`  
**验收**：单测证明旧无条件注入可被剥掉；条件注入在「有 runInference」片段上不短路；RPC 片段可装可卸。

### 2. 后端：叠加 v1.2.6 子代理层（L6）
**依赖**：步骤 1  
**改**：移植 taskTool V2、subagent route/session、action 白名单、resume mode、completion wake；`inspect` 分项计数。  
**验收**：合成片段上 `full` 命中 L6 markers；`stream` 不含 L6。

### 3. 后端：状态机与尽力打 API
**依赖**：1–2  
**改**：`status` / `apply(profile)` 返回 `streamReady` / `toolsReady` / `fullReady` / `hits` / `missing` / `versionHint`；桥接 `sand_stream_apply(profile)`。  
**验收**：mock 缺 wake → `complete=false` 且 `missing` 含对应键；mock 缺 managed-local → `ok=false`。

### 4. 前端：双按钮 + L6 勾选 + 分层明细
**依赖**：步骤 3  
**改**：主「启用完整」、次「仅 Stream」；完整旁勾选「含 Task/子代理」（默认勾选，可取消）；信息区按 L1–L6 分行；缺失项列表可读。  
**验收**：取消勾选后 apply 不含 L6 markers；勾选时尽力打 L6；不全时 toast/预览含缺失名。

### 5. 文档、测试、发版
**依赖**：1–4  
**改**：`tests/test_sand_stream.py`；`Bot/README`、`dev-references.local.md`、本计划勾选；拆 commit → v1.3.8 Release。  
**验收**：pytest 全绿；本机 3.18.9 上完整档尽量 `toolsReady`（有 Task 需求再验 L6）。

---

## 风险

| 风险 | 缓解 |
|------|------|
| RPC 改写与条件 Stream 叠加重写 | 优先 1.1.9 组合；单测 + 真机抓包确认只打 api2 Inference |
| L6 与 1.1.9 标记冲突 | L6 仅加在 full；install 前检测 external / 旧 installer 标记 |
| `sand_rpc.js` 体积与预检 | 注入目标限 extensionHost / agent-host；workbench 仍走现有预检 |
| 已装启动器 v1.2.2 无条件短路 | apply 时先 `_strip_legacy_unconditional_stream` 再写入 |
| 双备份（Claimer vs 启动器） | 不代跑 Claimer；逻辑迁入启动器统一备份目录 |

---

## 非目标（本轮不做）

- 不把「一键补齐」默认纳入 Sand  
- 不代跑 Claimer / v1.2.6 外置脚本  
- 不全局开 `long_running_jobs`  
- 不迁会员伪装 / MAX（仍归 `model_unlock`）  
- 不在本轮做 mac 专用打包

---

## 建议 commit 拆分

1. `feat(sand): adopt 1.1.9 conditional stream + move_exec + transport`  
2. `feat(sand): embed sand_rpc rewrite hook`  
3. `feat(sand): optional v1.2.6 subagent lifecycle layer`  
4. `feat(sand): dual profile apply with missing report`  
5. `feat(ui): Sand Stream full vs stream-only`  
6. `test: sand stream layered fixtures`  
7. `release: v1.3.8 …`

---

## 已确认

1. **L4**：两档都打（默认）。  
2. **L6**：完整档默认勾选，可取消。  
3. **HDRFIX_V2**：两档强制。

## 本会话进度

- 步骤 1–4 已落地（`launcher/sand_stream.py` + 设置页双按钮）。未发 v1.3.8、未拆 commit。
- 额外：设置「日常状态」下增加崩溃日志归因（`launcher/crash_diag.py`）。
- **L2 核已被取代**：后续见 [`plan-sand-stream-v131.md`](plan-sand-stream-v131.md)（Grok Bot Direct，不再用 1.1.9 条件化 Stream）。
