# 对照笔记：Grok Bot Box Relay v136

**对象**：`za/1/8.24/Bot/installers/sand_stream_installer_tools_grokbot_box_relay_v136.py`  
（`TOOL_VERSION = "1.4.4-grokbot-box-relay.2-linux31913"`）  
**同族**：`…_v134.py`（1.3.4 / 仅 3.18.9）、`…_v135.py`（1.4.0 / 仅 3.19.13）  
**内嵌近亲**：`SandClaimer-源码分享-1.4.2.zip` 内的 `grok_box.py`（`1.4.4-grokbot-box-relay.1`，无 Linux 3.18.9 sibling；与独立 v136 相似度约 0.94，**不是**同一文件）  
**对照**：本仓库 `launcher/sand_stream.py`（`MODULE_VERSION = 1.3.1`）+ 发版启动器；启动器侧 **零** `BOX_RELAY` / `gateway-descriptor` / `EnsureSandBox` 认知。  
**关联**：[notes-sandclaimer-142.md](notes-sandclaimer-142.md) · [notes-outer-sand-artifacts.md](notes-outer-sand-artifacts.md) §4–§5

一句话：**2026-09-09 起服务端拒收「Cursor 登录票 + sand 身份」直连 `InferenceService.Stream`；v136 把 Stream 改道到 Grok Bot 云端 Box 上的 `/sand-stream-relay/.../Stream`，用 Box 内 Bot 票转发，并在票快过期时用 Cursor 号自愈 mint。启动器仍走本机原生网关 Direct，与 Box Relay 互斥，禁止叠打。**

---

## 背景：9/9 服务端改口径（整条 Sand 线的分水岭）

| 时点 | 现象 |
|------|------|
| 9/8 及以前 | `managed-local` + `clientType:"sand"` 直连 Stream 仍可计 Bot 额度 |
| **9/9 起** | 同一路径一发即 401；本机号直连 `api2.cursor.sh` 明确回 **「Sand traffic is not supported on this endpoint」** |

结论（外围与 Claimer README 一致）：**只改客户端身份 / URL / 头，已经不可能让对话计入 Bot 额度。** 可行路径变成「请求从 Box 出去、带 Box 的 Bot 票」。这直接影响启动器现行 L2 Direct 在生产环境是否还能计额度——见文末「对启动器的含义」，本笔记只登记事实，**不在此轮改代码**。

---

## v136 是什么

| 项 | 内容 |
|----|------|
| 原生目标 | Cursor **3.19.13**（macOS / Windows / Linux） |
| Linux 兼容 | **3.18.9**：委托同目录 sibling `sand_stream_installer_tools_grokbot_direct_v131.py` 做 patch owner，本脚本只叠 Box Relay/auth 层；两套锚点故意不混 |
| 一键入口 | `setup-all` / `provision_and_install()`：`EnsureSandBox` → Box 内装 relay → 注入 `applyAuthorization` → 重启 |
| 鉴权演进 | v1.4.0/1.4.1 = 读 `grok-box-relay.json` **静态 token**；现行块 = 静态路径 + **临近过期自刷新**（`refresh` 块 + EnsureSandBox，best-effort，失败仍用旧票） |
| 旧块保留 | `GROK_RUNTIME_AUTH_*_V141` 整段 verbatim，供原地迁移与字节级 uninstall |
| 不依赖 | **不需要**本机安装 Grok Bot 桌面客户端（1.3.4 桌面登录路已废弃） |
| Marker 核 | Direct Stream + `SAND_GROK_BOX_RELAY_AUTH_V1` / `SAND_GROK_RUNTIME_AUTH_V1` + Task V3 / Action V2 + L7 系（Rules/MCP/User Rules/MAX_TOKENS）等；`MEMBERSHIP_SPOOF` 只出现在「外来归属表」数据里，**不是**本工具打点 |

---

## 相对 v134 / v135

| | v134 | v135 | **v136** |
|--|------|------|----------|
| `TOOL_VERSION` | `1.3.4-grokbot-box-relay.4` | `1.4.0-grokbot-box-relay.1` | `1.4.4-….2-linux31913` |
| Cursor | 仅 3.18.9 | 仅 3.19.13 | 3.19.13 + Linux 3.18.9 sibling |
| 自刷新 gateway | 无 / 早期 | 静态为主 | **有**（v1.4.2+ 注释口径） |
| `provision` 密度 | 较低 | 中 | 高（EnsureSandBox 一键） |
| 依赖 sibling v131 | 否 | 否 | **Linux 3.18.9 必需** |

---

## 与启动器对照

### 启动器仍强在哪（相对 v136）

| 点 | 说明 |
|----|------|
| 双轨嗅探 | `PatchTrack` 3.18/3.19 + 文件特征；v136 仍是「写死版本 + Linux 旁路」，不是启动器那种统一分流 |
| 安全纪律 | Task 锁父模型 / `subagentTypeName` 守卫、Action 白名单、会员伪装不进 `sand_stream` |
| 产品面 | 账号管家、代理、更新拦截、进程守护；v136 只做 Stream/Box 工程 |
| 尽力打 + `missing[]` | v136 偏严格版本门与计数门 |

### v136 独有（启动器目前没有）

| 点 | 说明 | 启动器怎么用 |
|----|------|----------------|
| Box Relay 整条链 | EnsureSandBox、Box 内 `/sand-stream-relay/...`、gateway descriptor、自刷新 | **不迁整包**。9/9 后若 Direct 真死，另开计划评估「原生网关能否等价」或「可选旁路」，禁止把 v136 当 submodule 塞进 apply |
| 静态→自刷新迁移 | 认识 v141 旧字面量并原地升级 | 若将来登记剥离，把 V141 + 现行两套都列入 restore |
| Linux 3.18.9 sibling 委托 | 动态 `importlib` 加载 v131 | 启动器已有自己的 3.18 轨，不必学这种双文件拼接 |

### 叠打坑

1. **同改 `applyAuthorization` / Stream 入口**：启动器 Direct 与 v136 Box Relay 抢同一段传输鉴权。  
2. **同串 Marker**：`SAND_DIRECT_INFERENCE_STREAM_V1`、Task V3、Action V2 等与启动器同名；叠写后双方 uninstall 都可能剥不干净。  
3. **Claimer「打补丁」+ v136**：Claimer 1.4.2 自己的 `sand_patch` 仍打 STREAM_RPC / LOCAL_ACTIONS；README 明确 **3.19.13 接 Grok 只用「一键接入 Grok」，别再点「打补丁」**。  
4. 启动器 `restore` **当前不认识** `SAND_GROK_BOX_RELAY_AUTH_V1`：误跑 v136 后，仅靠启动器还原可能留残留 → 应先跑 v136 / Claimer 的 `uninstall`。

---

## 叠打矩阵

| 机器状态 | 该怎么做 |
|----------|----------|
| 只用启动器 | 设置里启用完整/仅 Stream。**不要**跑 v136 / Claimer「一键接入 Grok」。 |
| 只要 3.19.13 + Bot 额度（外围方案） | 用独立 v136 `setup-all`，或 Claimer 1.4.2「一键接入 Grok」；**关掉** Claimer「打补丁」。 |
| 已装启动器 → 误跑了 v136 | 先跑 v136 `uninstall` / Claimer「退出 Grok」，再启动器「还原 Sand Stream」并重新启用。 |
| 已装 v136 → 想换启动器 | 同上：先卸 v136，再启用启动器。 |
| Linux 3.18.9 + v136 | 确认同目录有 `…_direct_v131.py`，否则兼容层直接报错。 |

---

## 不必搬进启动器（本轮）

| 禁止 | 原因 |
|------|------|
| 整段 EnsureSandBox / Box 内装路由 | 运维面与启动器「本机原生网关」产品定位冲突；权限与失败面过大 |
| 把 `grok-box-relay.json` 当默认鉴权源 | 与现有账号管家 / 原生网关状态机两套真相 |
| subprocess 代跑 v136 | 双备份、标记互拒（与 Claimer 纪律一致） |
| 把 Claimer 内嵌 `grok_box.py` 当唯一源 | 比独立 v136 **少** Linux sibling；版本号还停在 `.1` |

**可另开一轮评估（不夹带进现有 apply）：**

- 9/9 之后启动器 Direct 在真机是否仍计 Bot 额度；若否，产品层要明确「启动器 ≠ Bot 额度方案」。  
- 若要兼容误装机器：仅做 **marker 登记 + restore 剥离**（V141 静态块 + 现行自刷新块），不引入 provision。

---

## 对启动器的含义（登记，未立项）

1. 外围生态已把「计 Bot 额度」从「本机 sand Direct」迁到「Box Relay」。  
2. `MODULE_VERSION 1.3.1` 对 Box Relay **零认知** → status 解释不了「为何已启用 Sand 仍 401」。  
3. 下一步若动代码，优先顺序建议：**(A) 真机确认 Direct 是否仍可用 → (B) UI/文案标明能力边界 → (C) 可选：登记/剥离 Box Relay marker**；不要先搬 EnsureSandBox。
