# Cursor Account Launcher

Windows 桌面版 **Cursor 账号启动器**（非官方），基于 Python + pywebview。

## 功能

- 多账号管理、额度查询、一键切号
- **IDE 模式启动**（`--classic`）
- **登录设备管理**：查看会话、踢掉其它设备（保留本机 Web + Desktop）
- **会话守卫**：保留名单 / 踢新设备，后台定时巡检
- **代理注入**：写入 Cursor `settings.json`

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

- **启动 IDE（本机账号）**：注入代理 → 带 `--classic` 启动 Cursor
- **切换并启动**：关闭 Cursor → 写入所选账号 Token → 注入代理 → 启动

### 代理

保存后写入 `%APPDATA%\Cursor\User\settings.json`：

- `http.proxy` / `http.proxySupport` / `http.proxyStrictSSL`
- SOCKS5 时额外写入 `cursorGateway.downloadProxy`

默认本地代理：`127.0.0.1:7890`（可在界面修改）

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
powershell -ExecutionPolicy Bypass -File build.ps1
```

产物：`dist\CursorLauncher.exe`（约 15 MB）

**系统要求：** Windows 10/11 + [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)

## 许可

MIT — 非官方工具，仅供个人学习使用，请遵守 [Cursor 服务条款](https://cursor.com/terms)。
