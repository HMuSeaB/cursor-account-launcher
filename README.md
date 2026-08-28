# Cursor Launcher

私人定制的 **Cursor 启动器**（非 Tauri），专注 Cursor 单平台：

- 多账号管理、额度查询与一键切号
- **IDE 模式启动**（`--classic`，跳过 Agents 窗口）
- **登录会话管理** + **会话守卫**（保留名单 + 定时踢掉其它设备）
- **代理注入**（写入 Cursor `settings.json`）

技术栈：**Python + pywebview**（Windows WebView2），无需 Rust/Tauri 构建链。

## 与现有零散项目的关系

| 来源 | 复用了什么 |
|------|-----------|
| `Cusor-bot-sand` | pywebview 架构、账号存储、本机登录态读写、Cursor 进程启停 |
| [ai-tools-mng](https://github.com/githubgotest001/ai-tools-mng) | Cursor 会话 API（`/api/auth/sessions`）与会话守卫思路 |
| 你之前的 settings | 代理默认值 `127.0.0.1:7890` / SOCKS `7891` |

Sand 补丁、多平台账号等**不包含**在本项目中。

## 快速开始

```powershell
git clone https://github.com/HMuSeaB/cursor-account-launcher.git
cd cursor-account-launcher
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## 功能说明

### 1. 启动 IDE

- 「启动 IDE（本机账号）」：注入代理 → 带 `--classic` 启动 Cursor
- 账号行「启动 IDE / 切号并启动 IDE」：关 Cursor → 写入该账号 token → 可选重置机器码 → 注入代理 → 启动

### 2. 代理注入

保存后会写入 `%APPDATA%\Cursor\User\settings.json`：

- `http.proxy`
- `http.proxySupport`: `override`
- `http.proxyStrictSSL`
- SOCKS5 时额外写 `cursorGateway.downloadProxy`

### 3. 会话管理 / 会话守卫

参考 [ai-tools-mng](https://github.com/githubgotest001/ai-tools-mng) 的 sessions API，守卫策略移植自工作区 **BajieAsk**（`source/ggbond-mobile`）：

| 模式 | 对应 BajieAsk | 行为 |
|------|---------------|------|
| **保留名单** | `autoClean` | 勾选保留 + 本机当前会话；巡检时踢掉其它 |
| **踢新设备** | `autoKick` | 启用时建立 baseline；之后只踢**新出现**的设备 |

接口：

- `GET https://cursor.com/api/auth/sessions`
- `POST https://cursor.com/api/auth/sessions/revoke`

## 数据目录

`%LOCALAPPDATA%\CursorLauncher\`

- `accounts.json` — 账号（Windows DPAPI 加密）
- `session_guard.json` — 各账号保留名单
- `proxy.json` — 启动器代理配置
- `config.json` — Cursor 安装路径

## 打包 exe（无需 Python）

已配置 PyInstaller 单文件打包：

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

产物：`dist\CursorLauncher.exe`（约 15 MB，双击即用）。

账号/代理等数据仍在 `%LOCALAPPDATA%\CursorLauncher\`，与 `python app.py` 共用。

**系统要求：** Windows 10/11，需已安装 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)（Win11 通常自带）。

## 后续可扩展

- [x] 打包为单 exe（PyInstaller）
- [x] 账号用量/套餐查询
- [ ] 系统托盘 + 开机自启守卫
- [ ] 任务栏固定快捷方式自动带 `--classic`

## 许可

MIT — 非官方工具，仅供个人学习使用，请遵守 Cursor 服务条款。账号 Token 等敏感数据仅存本机 `%LOCALAPPDATA%\CursorLauncher\`，不会上传。
