# 对照笔记：SandClaimer 1.3.1

**对象**：`za/1/8.24/Bot/archives/SandClaimer-源码分享-1.3.1`（`TOOL_VERSION = 1.3.1`）  
**对照**：本仓库 `launcher/sand_stream.py`（模块 `1.3.0`）+ 发版启动器 1.3.11  
**用途**：以后看 Sand 线时先读这份，不要把 Claimer 整包当升级源。实施计划仍以 [plan-sand-stream-v131.md](plan-sand-stream-v131.md) / [plan-sand-version-tracks.md](plan-sand-version-tracks.md) 为准。  
**审计**：这份是白名单源码分享包，**没有远程后门**（token 只打 Cursor 官方 + 公开 DoH；账号落 `%LOCALAPPDATA%\SandClaimer`，DPAPI）。群里另发的 Nuitka exe 若不是这个包编的，另审。

一句话：**Claimer 主业是领资格，补丁核是 STREAM_RPC（剥 Joe）；启动器主业是账号管家，补丁核是 Grok Bot Direct（写 Joe / 3.19 `class J`）。两套不能叠打。**

---

## 各自优势

### 启动器强在哪（相对 1.3.1）

| 点 | 说明 |
|----|------|
| **L2 核跟官方现状** | Direct 绕过 `RunInference`（sand 身份会被拒）。1.3.1 反而剥 Joe，改在 attempt 入口 `return` + `e.stream`。 |
| **3.18 / 3.19 双轨** | 版本族 + 文件嗅探。1.3.1 写死 Cursor **3.18.9**。 |
| **分层、可还原** | `stream` / `full`、尽力打 + `missing[]`。1.3.1 一把梭，无分档。 |
| **Task V3 / Action V2** | 父模型 ID、放行 summarize/resume、子代理不再派发 Task、**没有** `mode-not-supported`。 |
| **L7 / L8** | 1M / Rules / MCP / User Rules + Preseed / `push_req_context` 50ms。1.3.1 没有这套 marker。 |
| **HDRFIX_V2 + RPC 强制保留** | Direct 仍要 Agent 出 ide、Stream 打 api2。1.3.1 的 v131 脚本会把这两项当外源拒装；启动器已内嵌，禁止再去跑外置脚本。 |
| **会员 / MAX 不进 sand_stream** | 在 `model_unlock`。Grok Bot 启用不会顺带改套餐显示。 |
| **产品闸门不靠全局开关** | **不写** `longRunningJobs:!0`。1.3.1 的 `sand_advanced` 默认会写。 |
| **管家能力** | 切号、额度、代理、减负、设备、会话守卫、更新拦截。Claimer 只有领号 + 切号 + 打补丁。 |

### 1.3.1 强在哪（不必因此改核）

| 点 | 说明 | 启动器怎么用 |
|----|------|----------------|
| **领取** | `start-sand-trial` / 团队通道、三池额度、导出 txt | **不迁**。要领号用 Claimer 当独立工具，启动器不兼领取器。 |
| **打补丁报告** | `patch_report.py` 逐条规则 + 关 IDE → 写入 → 校验 → 读 Agent Host 日志 | 报告层可继续增强（见 header-fetch 计划），不要把他们的安装编排整段搬进来。 |
| **1M 回包抬升** | STREAM 包装里若服务端 `maxTokens` 小于所选 `context` 就抬；碰到 `INPUT_TOKEN_LIMIT` 自动停 | **可参考、不整段搬**。启动器已有 Joe `agentTokenLimit` + L7。真机仍显示 300K 再单开一轮对照这条。 |
| **DoH** | 绕本机网关劫持 `cursor.com` / `api2.cursor.sh` | 启动器走进程代理，不在 sand_stream 里挂全局 `getaddrinfo`。 |
| **CDP 已登录浏览器** | 免费号绑卡 | 领取器用，启动器不搬隔离 Chrome。 |
| **http2 / dsv3 / privacy 早退门** | 对齐 SandCleanPatch，强制 managed-local 之前少几道 throw | 3.18 真机缺了再补单条，不预装整簇。 |
| **扫整个 agent-host dist** | 不写死 657/675 编号 | 启动器已 glob dist；清单里另加了 657/61/675/4884。 |

---

## 劣势 / 坑（1.3.1 对启动器）

1. **会卸掉启动器的 Direct**。`apply` 见到 `SAND_DIRECT_INFERENCE_STREAM_V1` 就剥，再写 `SAND_STREAM_RPC_V1`。已用启动器完整档的机器再点 Claimer「打补丁」，Bot 核被换掉。  
2. **`LOCAL_ACTIONS` / `SUBAGENT_LOCAL` 和 Action V2 抢同一段 `selectTurnRuntime`**。双补丁写坏或还原不净。  
3. **默认开 `longRunningJobs`**。启动器产品约定禁止用这条全局闸代替 Task/Action 语义。  
4. **会员伪装写进同一套 sand_patch**（含写死 `teamId:28945905` 的 fetch 回包）。只改显示，但和 `model_unlock` 叠 fetch 有黑屏风险。  
5. **无 3.19 轨**。3.19.13 上 3.18.9 字面量可显示「已注入」实际仍走 `RunInference`。  
6. **Joe 字面量仍是旧的**：无 `agentTokenLimit`、Grok 4.5/4.6 不互斥；而且 1.3.1 **根本不注入**这段，只留着给卸载旧补丁用。  
7. **探针日志**写 `%LOCALAPPDATA%\SandClientMode\sand-client-cli\trace.log`（modelId / client-type / maxTokens）。不出网，别当分享材料。

---

## 不必搬进启动器

和 [v131 计划「不迁」](plan-sand-stream-v131.md) 对齐，1.3.1 复核后 **仍然禁止**：

| 禁止 | 原因 |
|------|------|
| STREAM_RPC 核、剥 Joe Direct | 与现网 L2 相反 |
| `SAND_LOCAL_ACTIONS_V1` / `SAND_SUBAGENT_LOCAL_V1` | 与 Action V2 / subagent route 同锚 |
| `longRunningJobs:!0` 及整份 `sand_advanced` | 全局闸；探针不是产品层 |
| 领取 UI / `sand_api.py` 的 trial 接口 | 不是启动器职责 |
| 会员伪装 / MAX / 模型锁进 `sand_stream` | 已在 `model_unlock`；不绑 `fullReady` |
| `SAND_GLASS_CLIENT_V1` | 已有 `SAND_GLASSFIX_V1` |
| 写死 3.18.9、整单拒绝缺锚 | 已走双轨 + 尽力打 |
| DoH 全局 hook、CDP 登录浏览器 | 另模块 / 另工具 |
| subprocess 代跑 Claimer / v131 脚本 | 双备份、标记互拒 |
| 生命周期缺一条就拒写（CAM 那套） | 启动器保持 `missing[]` |

**可另开一轮、不要夹带进现有 apply 的：**

- STREAM 回包抬 `maxTokens` + `INPUT_TOKEN_LIMIT` 自动停（仅当真机 1M 仍显示 300K）。  
- 更多 action 401 → **扩 Action V2 白名单**，不要改回 LOCAL_ACTIONS。

---

## 叠打

| 机器状态 | 该怎么做 |
|----------|----------|
| 只用启动器 | 设置里「启用完整 / 仅 Stream」。不要再跑 1.3.1 打补丁。 |
| 已打 1.3.1 | 先用 Claimer **回退**，再用启动器启用。不要两边各点一次。 |
| 只要领号 | 用 Claimer 的导入/领取/导出；**关掉它的补丁面板**。 |

`restore` 必须能清：Direct 新旧字面量、STREAM_RPC、Task/Action 各版、L7/L8、Claimer 能识别的 LOCAL_ACTIONS（能剥则剥，剥不了进 `missing`，禁止覆盖写坏）。
