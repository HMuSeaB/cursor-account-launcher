# 对照笔记：散落外围 Sand 文件与启动器架构差异分析

**对象**：`za/1/8.24/Bot/` 根目录下原先散落的 7 个文件/压缩包  
**对照**：`cursor-launcher`（启动器）现行架构（双轨 3.18/3.19、Joe Direct、Task V3、Action V2、原生网关、账号管家）  
**归档更新**：
- 第一批散落文件已分类归档入 `Bot/extensions/`、`Bot/installers/`、`Bot/archives/` 并同步更新 `Bot/README.md`。
- 第二批（2026-09-09 根目录再散落的 4 个 `.py` + 4 个压缩包）同样已归入 `Bot/installers/` 与 `Bot/archives/`；浏览器重复下载的 `(1)` 后缀已去掉。根目录只保留 `README.md`。

---

## 1. 散落外围文件身份与版本鉴定

| 文件原名 | 整理后归档路径 | 版本标识 | 核心定位与技术特征 |
| :--- | :--- | :--- | :--- |
| **`sand_stream_installer_tools_fixed_v127 (2).py`** | `installers/sand_stream_installer_tools_fixed_v127.py` | `1.2.7-session-stream.2`<br>面向 3.18.9 | 介于 v1.2.6 和 v1.3.1 之间的过渡安装器。修复了早期 session stream 工具链挂载与唤醒逻辑，包含 23 个基础 Marker。 |
| **`SandUnified..py`** | `installers/SandUnified_v1.4.0_cursor3.18.25.py` | `1.4.0-unified-cursor-3.18.25`<br>面向 3.18.25 | **3.18.25 大一统单脚本**。将 Client 模式、Eligibility、会员伪装（`MEMBERSHIP_SPOOF`）、MaxMode、UI 解锁、HDRFIX、RPC、子代理 Task 等 33 个 Marker 强行统合在一个大单文件中。 |
| **`SandUnified-3.18.25..zip`** | `archives/SandUnified-3.18.25.zip` | 同上（`1.4.0-unified-cursor-3.18.25`） | 内部包含 `SandUnified.py` 与 `Start-SandUnified.bat`。经比对，内部脚本与外面的 `SandUnified..py` 代码逐行一致。 |
| **`cursor-sand-claimer-1.0.52.vsix`** | `extensions/cursor-sand-claimer-1.0.52.vsix` | 扩展 `1.0.52`<br>内置补丁 `1.4.0` | **IDE 内置一站式插件**。直接集成在 Cursor 内，快捷键 `Ctrl+Alt+S`。支持：Token 识别与领取、`cursor://cursorAuth` 协议无感切号、内置 **57 个 Marker** 的 JS 补丁引擎，且**支持通过 Remote-SSH 为远程服务器 cursor-server 打补丁**。 |
| **`SandClientMode..zip`** | `archives/SandClientMode-v1.8.1-modular.zip` | `v1.8.0 ~ v1.8.1`<br>包结构：`sandclient/` | **重构后的高阶 CLI 客户端工具包**。包含完整的 Python 模块化分层（`cli`, `patches`, `pipeline`, `remote`, `ssh`, `desktop` 等）。支持 17/17 补丁流水线、流量日志分析、模型自称修正，以及 **Remote-SSH 远程 Linux 服务器一键配置补丁与代理**。 |
| **`SandClientMode.zip`**<br>（与 `(2).zip`） | 移除冗余重复下载 | - | 两者哈希与大小完全一致（MD5: `e5e025d65d311bd08158567b95b1856e`），且 `archives/SandClientMode.zip` 中已存在完全相同的原件，判定为浏览器重复下载的冗余文件。 |

---

## 2. 与 `cursor-launcher`（启动器）的核心技术差异

### 2.1 版本分流与自适应机制（启动器优势）
- **启动器（`cursor-launcher`）**：
  - 采用**双轨动态分流制**（`PatchTrack`: `3.18` / `3.19` / `other`），通过 `product.json` 版本族与**单文件特征嗅探**双重兜底。
  - 在 Cursor `3.19.13` 上自动切换至 `class J` + `Ycw` + `promptModelInfo` 架构；在 `3.18.9`/`3.18.25` 上走 Joe Direct + `cre`/`nre`。
  - 即使 Cursor 升级，也不会因为类名或结构改变而打坏文件。
- **散落文件（`SandUnified` / `v127`）**：
  - `SandUnified..py` 虽然适配了 `3.18.25`，但其内部硬编码了针对 3.18 族的 Joe 类名与参数结构，**不支持 3.19 双轨**。如果在 3.19 环境下运行会导致注入失效或报错。
  - `sand_stream_installer_v127` 更是写死仅支持 `3.18.9`。

### 2.2 安全纪律与功能边界（纯净稳定性 vs 激进伪装）
- **启动器（`cursor-launcher`）**：
  - **隔离会员伪装**：坚决不在 `sand_stream` 中混入 `MEMBERSHIP_SPOOF`，绝不拦截 `fetch` 篡改 `teamId`，彻底规避客户端黑屏或封控隐患。
  - **Task V3 + Action V2 严格安全纪律**：
    - Task 强制锁定父级模型 ID、严守 `subagentTypeName` 守卫、阻止子代理无限制递归派发；
    - Action 严格走白名单放行（放行 resume/summarize，去除 `mode-not-supported`）。
- **散落文件（`SandUnified`）**：
  - 将 `SAND_MEMBERSHIP_SPOOF_V1`（篡改前端显示为 Pro/Ultra）、`SAND_MAXMODE_V1`、`SAND_CONTEXT_LIMIT_UI_V1`（伪造长上下文标签）强行打包注入。
  - 这种“套餐伪装”既不增加真实模型能力，又大幅增加了版本更新时的崩溃风险。

### 2.3 运行形态与外围独有亮点
- **Remote-SSH 远程开发服务器支持**（`SandClientMode..zip` 与 `cursor-sand-claimer.vsix` 的独有优势）：
  - 当使用 Cursor Remote-SSH 连到远端 Linux 时，Agent 实际运行在远端的 `cursor-server` 上。
  - `SandClientMode..zip`（v1.8.1）和 `cursor-sand-claimer.vsix` 支持一键为远程 `cursor-server` 注入补丁并配置反向代理回连本机。启动器目前主要覆盖本地桌面环境，远端部署可参考这一思路。
- **IDE 协议级无感切号**（`cursor-sand-claimer.vsix`）：
  - 扩展利用 Cursor 的 `cursor://cursorAuth` 协议，可在编辑器内部通过快捷键实时切换账号。

---

## 3. 叠打与共存纪律

```
┌─────────────────────────────────────────────────────────────┐
│                       禁止叠打警告                           │
│  切勿在已由 cursor-launcher 打过补丁的环境中运行 SandUnified   │
│  或在 cursor-sand-claimer 扩展中点击“打补丁”！               │
└─────────────────────────────────────────────────────────────┘
```

1. **核心互斥**：
   - 启动器采用经过严格测试的 Joe Direct（3.18）/ class J（3.19）+ Task V3 + Action V2；
   - `SandUnified` 会用自己的 `taskToolProps` 覆盖启动器的 Task 守卫；
   - `cursor-sand-claimer` 内置了 57 个 Marker 的庞大 JS 补丁引擎，两套补丁互相覆盖会导致 Cursor 彻底损坏或会话中断。
2. **推荐协作组合**：
   - **日常编码与主要环境**：使用 `cursor-launcher` 启动器（双轨自适应、原生网关代理、进程守护、切号与更新屏蔽）。
   - **扩展轻量辅助**：可安装 `cursor-sand-claimer-1.0.52.vsix`，仅用于**在 IDE 状态栏内查看额度或快速切换 Token**，**严禁点击打补丁**。
   - **远程开发场景**：若需要使用 Cursor 连接 Remote-SSH 服务器，可解压 `archives/SandClientMode-v1.8.1-modular.zip` 按照其说明在 Linux 服务器端配置 `cursor-server`。

---

## 4. 第二批散落文件（2026-09-09）

| 文件原名 | 整理后归档路径 | 版本标识 | 核心定位与技术特征 |
| :--- | :--- | :--- | :--- |
| **`sand_stream_installer_v134.py`** | `installers/sand_stream_installer_v134.py` | `1.3.4-grokbot-box-relay.4`<br>仅 `3.18.9` | Box Relay Stream：Direct 会话 + 经 Grok Bot Box 网关走 InferenceService.Stream；23 个 Client Marker。 |
| **`sand_stream_installer_tools_grokbot_box_relay_v135.py`** | `installers/sand_stream_installer_tools_grokbot_box_relay_v135.py` | `1.4.0-grokbot-box-relay.1`<br>仅 `3.19.13` | 同族 Box Relay，目标切到 3.19.13；无 Linux 3.18.9 sibling 层。 |
| **`sand_stream_installer_tools_grokbot_box_relay_v136(1).py`** | `installers/sand_stream_installer_tools_grokbot_box_relay_v136.py` | `1.4.4-grokbot-box-relay.2-linux31913`<br>原生 `3.19.13`，Linux 兼容 `3.18.9` | 本批最新 Box Relay。3.19.13 走本脚本锚点；Linux 3.18.9 委托 sibling Direct v131，两套锚点不混打。`(1)` 为重复下载后缀，已去掉。 |
| **`Sand客户端模式安装工具20260909.py`** | `installers/sand_client_mode_installer_v1.9.0.py` | `1.9.0`<br>`3.18.9` / `3.19.13` | 双版本客户端模式安装器。含 Box 自动唤醒、唯一名 Sand Relay Agent（find-or-create）、Stream 元数据诊断。 |
| **`SandClaimer-源码分享-1.4.2.zip`** | `archives/SandClaimer-源码分享-1.4.2.zip` | 源码包 1.4.2 | 领取器源码分享；相对 1.3.x 新增 `grok_box.py` / `grok_login.py` / `grok_relay.py`。 |
| **`SandClaimer-源码分享-1.3.2.zip`** | `archives/SandClaimer-源码分享-1.3.2.zip` | 源码包 1.3.2 | 与已解压的 `archives/SandClaimer-源码分享-1.3.1/` 同族更早包。 |
| **`SandClaimer-1.3.3魔改.rar`** | `archives/SandClaimer-1.3.3魔改.rar` | 1.3.3 魔改 | 第三方改包，未解压；仅归档。 |
| **`grok-bot-反代.zip`** | `archives/grok-bot-反代.zip` | Go 插件树 | 顶层仅 `plugin/`（protocol / host / executor / auth / `cpa-grok-bot-plugin`）。体积约 27 MB，含 `__MACOSX` 与 `.git`。 |

与启动器的关系（本批补充）：

- Box Relay 系列把 Stream 指到 Grok Bot Box 网关，而启动器走本机原生网关；**不要叠打**。
- `v134` 写死 3.18.9，`v135` 写死 3.19.13；只有 `v136` 和客户端 `1.9.0` 同时覆盖两个版本族，但仍是外围单脚本，没有启动器的双轨嗅探与 Task V3 / Action V2 纪律。
- `v136` 的 Linux 3.18.9 路径依赖 `installers/sand_stream_installer_tools_grokbot_direct_v131.py` 作为 patch owner，缺该文件则兼容层不可用。

---

## 5. 9/9 之后的关键更新（v136 + Claimer 1.4.2 / 1.4.8）

**深度对照**（规格对齐既有 `notes-installer-132` / `notes-sandclaimer-131`）：

- [notes-box-relay-v136.md](notes-box-relay-v136.md) — 独立 Box Relay 安装器  
- [notes-sandclaimer-142.md](notes-sandclaimer-142.md) — 源码分享 1.4.2（领号 + 内嵌 grok_box）  
- [notes-sandclaimer-148.md](notes-sandclaimer-148.md) — 1.4.8 + 飙车群 1.1.3（挂路由引擎更完整；启动器网关已对齐领票+挂路由）

### 5.1 服务端分水岭

从 **2026-09-09** 起，服务端不再接受「Cursor 登录票 + `sand` 身份」直连 `InferenceService.Stream`（同路径 9/8 正常、9/9 起 401；直连 api2 回 `Sand traffic is not supported on this endpoint`）。外围结论：**只改客户端伪装已经无法计 Bot 额度**；可行路径是请求从 Grok Bot **云端 Box** 带 Bot 票出去。

### 5.2 两份产物的角色分工

| 产物 | 版本真相 | 干什么 | 不干什么 |
|------|----------|--------|----------|
| **独立 v136** | `1.4.4-grokbot-box-relay.2-linux31913` | `setup-all`：EnsureSandBox → Box 内 relay → 注入 `applyAuthorization`（含票自刷新） | 不管领号、不做启动器管家 |
| **Claimer 1.4.2** | `sand_patch=1.4.2`；内嵌 `grok_box=1.4.4-….1`（无 Linux sibling） | 领号 +「一键接入 Grok」（进程内跑 grok_box）；「打补丁」仍是 STREAM_RPC 核，但**不再**在 apply 里注入 Grok 改道 | 不替代启动器；3.19.13 接 Grok 时**禁止**再点「打补丁」 |

独立 v136 与包内 `grok_box.py` **不是同一文件**（相似度约 0.94）。需要 Linux 3.18.9 Box 时用独立 v136 + sibling v131。

### 5.3 对 `cursor-launcher` 的即时含义

1. `launcher/sand_stream.py`（1.3.1）对 Box Relay **零认知** → 误装后 status/restore 解释不清、可能剥不干净。  
2. 日常纪律不变：启动器环境不要跑 v136 / Claimer 补丁 /「一键接入 Grok」。  
3. **未立项**：先真机确认启动器 Direct 在 9/9 后是否仍计额度 → 再决定文案边界或「仅登记/剥离」Box Relay marker；**禁止**先把 EnsureSandBox 整包搬进 apply。

### 5.4 Storm Dock（账号坞，不是补丁器）

开源桌面坞 [tangsj-hub/Storm-Dock](https://github.com/tangsj-hub/Storm-Dock)（v1.3.0，Tauri）。管 Cursor / ChatGPT / Grok Build 账号；另有 `grok_bot` 模块把 Cursor JWT 写入 Grok Bot 桌面 `sand-secrets.json`（Claimer `grok_login.py` 同源）。

- **不**注入 Cursor workbench / agent-host，与启动器补丁核一般不叠打。  
- **不能**替代 v136：它不装 Box 内 relay。桌面写票路正是 Claimer 因 404 废弃的那条。  
- 深度对照：[notes-storm-dock.md](notes-storm-dock.md)

### 5.5 三路收敛 + 本机网关骨架

产品判断见 [notes-bot-three-paths.md](notes-bot-three-paths.md)；实施见 [plan-bot-gateway.md](plan-bot-gateway.md)。

| 路 | 定位 |
|----|------|
| ① 官方 Bot | 真源：在 Bot 里直接调高级模型（网关线稳定后再补宿主脚本） |
| ② Bot 网关 | 主推进：`bot_gateway/` 领票 + Box 挂路由 + 本机转发（仍不写 Cursor） |
| ③ 脚本补丁 | 收缩为 IDE 纪律；不再当计额度主方案 |

`python -m bot_gateway` 默认 `127.0.0.1:8765`；upstream 契约对齐 `grok-box-relay.json`。**不**写 Cursor、**不**跑 EnsureSandBox（后续见 plan）。
