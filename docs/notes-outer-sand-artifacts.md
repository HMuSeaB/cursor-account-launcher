# 对照笔记：散落外围 Sand 文件与启动器架构差异分析

**对象**：`za/1/8.24/Bot/` 根目录下原先散落的 7 个文件/压缩包  
**对照**：`cursor-launcher`（启动器）现行架构（双轨 3.18/3.19、Joe Direct、Task V3、Action V2、原生网关、账号管家）  
**归档更新**：散落文件已分类归档入 `Bot/extensions/`、`Bot/installers/`、`Bot/archives/` 并同步更新 `Bot/README.md`。

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
