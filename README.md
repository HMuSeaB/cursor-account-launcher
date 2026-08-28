# Cursor Account Launcher

Windows 桌面版 **Cursor 账号启动器**（非官方），基于 Python + pywebview。

## 功能

- 多账号管理、额度查询、一键切号（本机账号置顶）
- IDE 模式启动（`--classic`）；记住窗口大小与位置
- 减负：轻量启动、运行中削减内存、关闭 IDE、压缩状态库
- Grok Extra High 500k 上下文补丁（可选；改本机 Cursor 文件，需 Node.js）
- 登录设备管理 / 会话守卫
- 代理：settings / argv / 环境变量；可选进程级 `version.dll`（手动写入/删除/还原）

## 快速开始

```powershell
git clone https://github.com/HMuSeaB/cursor-account-launcher.git
cd cursor-account-launcher
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

或直接使用 [Releases](https://github.com/HMuSeaB/cursor-account-launcher/releases) 里的安装包 `CursorLauncherSetup.exe`（安装时可勾选「创建桌面快捷方式」），或不经安装的 `CursorLauncher.exe`。绿色版 exe 首次打开也会询问是否放到桌面。

## 使用说明

### 启动 IDE

- **启动 IDE**：默认 `--classic`，不改 settings（除非勾选代理自动注入）
- **切换并启动**：关 Cursor → 写入所选账号 Token → 启动。当前本机账号显示「启动」，不会再切一次
- **减负菜单**（顶栏三条杠）：轻量启动、削减内存（IDE 开着也能用；也可点顶栏运行状态）、关闭 IDE、压缩 `state.vscdb`（须先关 IDE）

### Grok 500k（可选）

设置 → **打上 500k / 还原 256k**。会改本机 Cursor 安装目录中的扩展宿主文件，把 Grok Extra High 客户端看到的窗口从 256k 抬到 500k（不改官方计费）。需本机 Node.js；升级 Cursor 后需重打。改前请完全退出 IDE。

### 代理

FlClash 开着（推荐 SOCKS5 `127.0.0.1:7891`）。设置里 **保存** 只写 settings / 环境变量。

进程 DLL（Antigravity 同款，不用 TUN）需 **手动** 操作，且要先关 IDE：

| 按钮 | 作用 |
|------|------|
| 写入 DLL | 安装到 Cursor 目录 |
| 删除 DLL | 删除（会先备份） |
| 还原 DLL | 从备份装回 |
| 还原补丁 | 恢复 workbench 备份（重装 Cursor 后勿用） |

黑屏时：关 IDE → **删除 DLL** → 再开。exe 版关启动器时若弹 `_MEI` 警告，点确定即可。

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

产物：

- `dist\CursorLauncher.exe`（绿色版）
- `dist\CursorLauncherSetup.exe`（需本机 [Inno Setup 6](https://jrsoftware.org/isinfo.php)；安装向导有「创建桌面快捷方式」选项，默认勾选，可取消）

exe 正在运行时请先关闭再打包。图标由 `scripts/make_icon.py` 在打包前生成。

**系统要求：** Windows 10/11 + [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)

## 许可

MIT — 非官方工具，仅供个人学习使用，请遵守 [Cursor 服务条款](https://cursor.com/terms)。
