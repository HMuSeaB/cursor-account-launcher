# Cursor Account Launcher

Windows 桌面版 **Cursor 账号启动器**（非官方），基于 Python + pywebview。

## 功能

- 多账号管理、额度查询、一键切号
- **IDE 模式启动**（`--classic`）
- **登录设备管理**：查看会话、踢掉其它设备（保留本机 Web + Desktop）
- **会话守卫**：保留名单 / 踢新设备，后台定时巡检
- **代理注入**：写入 Cursor `settings.json`（不修改 Cursor 网关插件线路设置）

## 快速开始

```powershell
git clone https://github.com/HMuSeaB/cursor-account-launcher.git
cd cursor-account-launcher
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## 使用说明

### 启动 IDE

- **启动 IDE（本机账号）**：默认只带 `--classic` 启动 Cursor，**不改** settings.json
- **切换并启动**：关闭 Cursor → 写入所选账号 Token → 启动（同样默认不写 settings，除非勾选代理自动注入）

### 代理

保存后写入 `%APPDATA%\Cursor\User\settings.json`（**仅代理键**，不动 `cursorYc.*` 等其它项）：

- `http.proxy` / `http.proxySupport` / `http.proxyStrictSSL`
- SOCKS5 时额外写入 `cursorGateway.downloadProxy`

默认 **不会** 在启动 IDE 时写 settings；需要时在界面勾选「启动 IDE 时自动注入」。

默认本地代理：`127.0.0.1:7890`（可在界面修改）

### Token / 设备管理

- 账号卡片 **📋** 一键复制 Token；详情里有完整文本框
- 标签 **WS** = 含 `user_xxx::eyJ…`；**JWT** = 仅 access_token
- 详情 → **同步本机 WS**：从本机 `state.vscdb` 拉取 WS Token（需本机已登录且账号一致）

### 登录设备 / 会话守卫

**设备管理**

- 需要完整 ws token（`user_xxx::eyJ...`）才能拉取设备列表
- 一键「踢掉其它设备」会自动保留本机 Desktop + 最近活跃的 Web

**会话守卫（可选）**

| 模式 | 行为 |
|------|------|
| 保留名单 | 勾选保留 + 本机当前会话；巡检时踢掉其余 |
| 踢新设备 | 启用时建立 baseline；之后只踢新出现的设备 |

相关 API（Cursor 私有接口，可能变动）：

- `GET https://cursor.com/api/auth/sessions`
- `POST https://cursor.com/api/auth/sessions/revoke`
- `GET https://api2.cursor.sh/auth/usage-summary`
- `POST https://cursor.com/api/dashboard/get-aggregated-usage-events`（模型 token 明细）

### 模型用量

账号详情 → 点 **「查看」**（模型用量区块）才会请求当前计费周期的各模型 token 统计（与 [Cursor Billing](https://cursor.com/dashboard/billing) 页一致）；加载后可点 **「刷新」** 重新拉取。刷新额度不会自动请求此项。

### 数据目录

`%LOCALAPPDATA%\CursorLauncher\`

| 文件 | 说明 |
|------|------|
| `accounts.json` | 账号（Windows DPAPI 加密） |
| `session_guard.json` | 会话守卫配置 |
| `proxy.json` | 代理配置 |
| `config.json` | Cursor 安装路径 |

Token、密码等敏感数据**仅存本机**，不会上传。

## 打包 exe

```powershell
cd cursor-launcher
.\build.ps1
```

产物：`dist\CursorLauncher.exe`（约 15 MB）

> 请在本目录直接运行 `.\build.ps1`（不要套一层 `powershell -File`）。脚本会输出 `[build] SUCCESS`；若 exe 正在运行需先关闭，否则 PyInstaller 会报 PermissionError。

**系统要求：** Windows 10/11 + [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)

## 许可

MIT — 非官方工具，仅供个人学习使用，请遵守 [Cursor 服务条款](https://cursor.com/terms)。
