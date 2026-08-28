# Cursor Account Launcher

Windows 桌面版 **Cursor 账号启动器**（非官方），基于 Python + pywebview。

## 功能

- 多账号管理、额度查询、一键切号（本机账号置顶）
- IDE 模式启动（`--classic`）；记住窗口大小与位置
- 减负：轻量启动、运行中削减内存、关闭 IDE、压缩状态库
- Grok Extra High 500k 上下文补丁（可选；改本机 Cursor 文件，需 Node.js）
- 登录设备管理 / 会话守卫
- 代理注入（仅写 Cursor `settings.json` 的代理相关项）

## 快速开始

```powershell
git clone https://github.com/HMuSeaB/cursor-account-launcher.git
cd cursor-account-launcher
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

或直接使用 [Releases](https://github.com/HMuSeaB/cursor-account-launcher/releases) 里的 `CursorLauncher.exe`。

## 使用说明

### 启动 IDE

- **启动 IDE**：默认 `--classic`，不改 settings（除非勾选代理自动注入）
- **切换并启动**：关 Cursor → 写入所选账号 Token → 启动。当前本机账号显示「启动」，不会再切一次
- **减负菜单**（顶栏三条杠）：轻量启动、削减内存（IDE 开着也能用；也可点顶栏运行状态）、关闭 IDE、压缩 `state.vscdb`（须先关 IDE）

### Grok 500k（可选）

设置 → **打上 500k / 还原 256k**。会改本机 Cursor 安装目录中的扩展宿主文件，把 Grok Extra High 客户端看到的窗口从 256k 抬到 500k（不改官方计费）。需本机 Node.js；升级 Cursor 后需重打。改前请完全退出 IDE。

### 代理

保存后写入 `%APPDATA%\Cursor\User\settings.json`（仅代理键）。默认不在启动时注入；需要时勾选「启动 IDE 时自动注入」。默认 `127.0.0.1:7890`。

### Token / 设备

- 详情可分别查看 Access Token 与 WS Token
- 设备管理需要完整 ws token（`user_xxx::eyJ...`）
- 会话守卫：保留名单 / 踢新设备

### 数据目录

`%LOCALAPPDATA%\CursorLauncher\`（账号经 Windows DPAPI 加密，仅存本机）

## 打包

```powershell
.\build.ps1
```

产物：`dist\CursorLauncher.exe`。exe 正在运行时请先关闭再打包。

**系统要求：** Windows 10/11 + [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)

## 许可

MIT — 非官方工具，仅供个人学习使用，请遵守 [Cursor 服务条款](https://cursor.com/terms)。
