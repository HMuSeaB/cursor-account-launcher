# 对照笔记：Storm Dock 1.3.0

**对象**：https://github.com/tangsj-hub/Storm-Dock（`main` @ `0833233`，`package.json` / `tauri.conf.json` = **1.3.0**，2026-09-09 发版）  
镜像：https://gitee.com/mqlwyz/storm-dock  
**对照**：本仓库启动器账号管家（切号 / OAuth / 额度）+ [notes-sandclaimer-142.md](notes-sandclaimer-142.md) 的 `grok_login.py` + [notes-box-relay-v136.md](notes-box-relay-v136.md)  
**许可**：MIT；README 声明与 Cursor / OpenAI 无隶属，并写明不允许绕过登录与服务限制。

一句话：**Storm Dock 是本机多工具账号坞（Cursor / ChatGPT / Grok Build），不是 Sand 补丁器。它对 Grok Bot 桌面端的 `sand-secrets.json` 写入，就是 Claimer 1.3.4→1.4.2 已废弃的「登录桌面客户端换 Box 票」那条路的源头实现；9/9 后计 Bot 额度走 v136 EnsureSandBox，不再依赖这套。**

---

## 仓库身份

| 项 | 内容 |
|----|------|
| 形态 | Tauri v2 + Rust + React/Vite 桌面应用 |
| 版本 | **1.3.0**（当天连发 1.2.0 → 1.3.0） |
| 平台 | macOS / Windows（`grok_bot` 其它 OS 直接 unsupported） |
| 数据 | 本地 SQLite `storm-dock.db`；可迁到 Dropbox/iCloud/WebDAV；会话不进前端/导出 JSON/日志 |
| 命令面 | `prepare_launch_grok_bot` / `confirm_launch_grok_bot`；Cursor 官方 OAuth PKCE；切号前备份、写入后校验、失败回滚；未确认不强制杀 Cursor |

### 两套「Grok」不要混

| 模块 | 是什么 | 路径 |
|------|--------|------|
| **`src-tauri/src/grok/`** | **Grok Build（xAI 桌面/CLI）** 账号、OAuth、会话、插件 | README「Grok Build 已支持」 |
| **`src-tauri/src/grok_bot/`** | **Cursor 的 Grok Bot 桌面客户端**（`Grok Bot.exe` / `Grok Bot.app`）登录态注入 | Claimer `grok_login.py` 注释里的「原作者 Storm-Dock」 |

---

## `grok_bot` 与外围 Sand 线的关系（核心）

Storm Dock 把 **Cursor 账号的 access/refresh JWT** 按 Grok Bot 0.44 的格式写进用户目录 `sand-secrets.json`：

- slot = `sha256("sand-account-slot\0" + jwt.sub)` 十六进制  
- 值经 Electron safeStorage 加密（Windows OSCrypt v10 + DPAPI 密钥；macOS Keychain `Grok Bot Safe Storage` + PBKDF2/AES-128-CBC）  
- 写之前若进程在跑：先正常退出再写，再启动客户端，让它自己去开 Box  

这与 Claimer 1.4.2 的 `grok_login.py` **同一协议**。Claimer README 已写明：实测 Box pod 是 VNC/出口代理、**默认没有** `/sand-stream-relay/.../Stream`，桌面登录路 **404**；现默认委托 v136 `EnsureSandBox` 自愈，**不需要装 Grok Bot 桌面客户端**。

因此：

| 问题 | 答案 |
|------|------|
| 能不能当 v136 的替代？ | **不能。** Storm Dock 只解决「Grok Bot 客户端登哪个 Cursor 号」，不装 Box 内 relay、不改 Cursor `applyAuthorization`。 |
| 9/9 后还要不要跟这条路？ | Claimer / v136 已否决为计额度主路径。Storm Dock 仍可当 **Grok Bot 桌面切号** 工具，与启动器 Sand Stream **正交**。 |
| 启动器要不要搬 `grok_bot`？ | **不迁。** 与「不 subprocess 代跑外置脚本、不把桌面 Grok Bot 当网关」纪律一致。 |

v134/v135/v136 安装器里仍有 **读取** `sand-secrets.json` 的 JS（给旧静态 relay / 桌面票路用）。v136 现行主路径是 EnsureSandBox + `grok-box-relay.json` 自刷新，桌面 secrets 是遗留旁路。

---

## 与启动器对照（账号坞，不是补丁核）

### Storm Dock 强在哪（启动器不必因此改核）

| 点 | 说明 | 启动器怎么用 |
|----|------|----------------|
| 多产品坞 | 同一 UI 管 Cursor + ChatGPT + Grok Build | **不迁**；启动器只做 Cursor 生态 |
| Grok Bot 桌面写票 | 完整 OSCrypt/钥匙串 + .lnk 解析 + 退出等待 | 仅作协议备忘；计额度不走这条 |
| 会话/插件浏览 | 按项目看 Cursor/ChatGPT/Grok 会话；管 Skills/MCP/Hooks | 可参考产品形态，不搬进 sand_stream |
| 切号纪律 | 备份 → 校验 → 失败恢复；未确认不杀进程 | 启动器已有管家切号，可对照「确认后再重启」文案 |

### 启动器仍强在哪

| 点 | 说明 |
|----|------|
| Sand Stream 补丁核 | Joe Direct / 3.19 `class J`、Task V3、Action V2、原生网关；Storm Dock **零** workbench/agent-host 注入 |
| 进程守护 / 更新拦截 / 本机代理 | Dock 不管 |
| 9/9 Bot 额度 | 外围已转向 Box Relay；Storm Dock 不提供 EnsureSandBox |

### 叠打

Storm Dock **不打** Cursor JS 补丁，与启动器 Sand Stream **一般不互斥**。仍注意：

1. 两边同时切 Cursor 登录态 → 抢 `state.vscdb` / 会话文件；约定「一次只让一个管家写」。  
2. 用 Storm Dock 启动 Grok Bot 桌面 **同时** 跑 v136 → 两套 Box 来源（桌面开的 Box vs EnsureSandBox），状态难对齐；接 Bot 额度只用 v136/Claimer 一键。  
3. 不要把 Storm Dock 当「打补丁工具」推荐进 `Bot/README` 安装器表。

---

## 不必搬进启动器

| 禁止 | 原因 |
|------|------|
| 整仓 Tauri 坞 / ChatGPT / Grok Build | 产品边界不是 Cursor 启动器 |
| `grok_bot` 写 `sand-secrets.json` 作为默认 Bot 网关 | 上游 Claimer 已因 404 废弃；v136 不依赖桌面客户端 |
| 代启 Grok Bot.exe 当 Stream 出口 | 与原生网关、EnsureSandBox 两条线都冲突 |

**可另开一轮（不夹带 apply）：** 若管家要「同步切 Cursor 号时可选同步 Grok Bot 桌面」，再对照 `grok_bot/mod.rs` 的 slot/加密/退出协议做可选开关——默认关，且文案写明 **这不等于 Bot 额度 / Box Relay**。

---

## 对现有笔记的修正

- Claimer `grok_login.py` 不是自创协议，是 **Storm Dock `grok_bot` 的 Python 复述**。  
- 「桌面 Grok Bot 登录 → 解 gateway-descriptor」失败，责任在 **Box 侧没有 relay 路由**，不是 Storm Dock 写票写错。Storm Dock 把票写对了，推理入口仍 404。  
- 独立 v136 用 Cursor 号直接 `EnsureSandBox`，绕开了对 Storm Dock / Grok Bot.app 的依赖。
