# Cursor Account Launcher

Windows 桌面版 **Cursor 账号启动器**（非官方），基于 Python + pywebview。

## 分层（别一次写爆 Cursor）

启动器是**桌面管家**：账号、切号、代理偏好、减负。对 Cursor 安装目录的改写拆成可选层，**各自启用/还原**，启动 IDE 时默认不写 settings / argv / workbench：

| 层 | 改什么 | 本仓库入口 |
|----|--------|------------|
| 桌面管家 | 账号 Token、进程代理参数、更新拦截 | `app.py` / `launcher/*` |
| 扩展 Agent | `extensionHostProcess.js` 回包改写（500k） | `scripts/patch-ctxwin.mjs` |
| workbench 客户端 | 模型选择器解锁（不依赖 Sand） | `launcher/model_unlock.py` + `launcher/workbench/`（统一备份/预检/写入） |
| 网关 bridge | `43111/__bajie` 等 | **外部插件**；启动器只检测/路由，默认不剥补丁 |

## 功能

- 多账号管理、额度查询、一键切号（本机账号置顶）
- IDE 模式启动（`--classic`）；记住窗口大小与位置
- 减负：轻量启动、运行中削减内存、关闭 IDE、压缩状态库
- 可选：扩展宿主回包改写（AvailableModels / GetServerConfig）；可选：模型选择器解锁
- 主界面补丁自检与一键补齐（网关原生 + 仅 MAX + 500k + 代理）
- 登录设备管理 / 会话守卫
- 代理：settings / argv / 环境变量（仅「保存」写入；启动只带进程参数）；网关路由；可选进程级 `version.dll`（易闪退，非必要别用）
- 禁用 Cursor 自动更新（settings + Windows 更新器拦截）

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

### 模型选择器解锁（启动器自有）

设置顶部有 **日常状态** 四格（网关 / MAX / 500k / 代理）和蓝色「下一步」：IDE 开着会锁补丁按钮，关掉后可自动继续。日常按「下一步」即可；DLL / 完整解锁等在高级危险区。

设置 → **仅解锁 MAX / 完整解锁 / 还原 / 修复黑屏**。改本机 Cursor 的 `workbench.*.main.js`。

已有 YC 网关模型墙时，**优先点「仅解锁 MAX」**（只改 `hideMaxToggle`）。完整解锁才含 FREE 锁、命名视图、会员 fetch 伪装。

- FREE 模型锁 + 全量 picker / 实验 treatment 短路
- 命名视图门闩（不再强求内部名 `grok-4.5`）
- 目录 hydrate：补 `defaultOn`、`namedModelSectionIndex`（网关自定义模型常用）
- **显示 MAX Mode**：关掉 `hideMaxToggle`（token 计价账号会被藏开关）
- 侧边栏套餐可改 Pro / Ultra / Team / Pro+ / Free（只改客户端显示，不是真套餐）

**不**伪装 Sand。Bot/Sand 专属模型仍要 Sand/号池。须先关 IDE；启用后用启动器重启并新开对话。升级 Cursor 后需重打。备份：`%LOCALAPPDATA%\CursorLauncher\model-unlock\backups\`。

#### 易错点（模型墙 / MAX / 黑屏）

1. **三件事别混**：模型列表靠 YC 网关 + `%APPDATA%\Cursor\...\state.vscdb` 缓存；MAX 开关靠 `hideMaxToggle` 补丁；重装 Cursor 只换程序，不清用户数据。
2. **有模型墙不等于有 MAX**：token 计价（`hasTokenBasedPricing`）会藏 MAX。要开关就点「仅解锁 MAX」，不必完整解锁。
3. **对象字面量里不能写 `hideMaxToggle:!1;`**：分号会截断属性，workbench 解析失败 → **黑屏**。正确是 `hideMaxToggle:!1/*MARKER*/`。
4. **会员正则必须写成 `"(?:pro|ultra|…)"`**：写成 `"pro|ultra|…"` 会误命中上千处 `"pro` 字符串 → **黑屏**。正常命中应是 `显示MAX×1~3`、`会员×0 或 ×1`；出现 `会员×几百/上千` 立刻停、点「修复黑屏」或重装 Cursor。
5. **`enterprise` 会显示 Team Plan**：侧边栏文案来自 `applicationUser.membershipType`，和 `cursorAuth/stripeMembershipType` 可能不一致。改显示先关 IDE，再点「修正侧边栏显示」。这只是显示，不会变成真 Ultra/Team。
6. **必须用本仓库最新 `python app.py` 或本版本 exe**：旧 exe 仍可能打坏文件。打补丁前先完全退出 `Cursor.exe`。
7. **黑屏急救**：关 IDE → 启动器「修复黑屏」或「还原」→ 再用启动器启动。修不好就重装 Cursor（用户数据一般还在）。

### 模型回包改写（启动器自有）

设置 → **启用回包改写 / 还原官方**。挂钩本机 Cursor 的 `extensionHostProcess.js`，在进程内改写：

- `AvailableModels`（Grok Extra High 窗口 256k→500k）
- `GetServerConfig`（全局上下文兜底）
- Agent / TokenLimit 相关流式回包

不依赖混淆网关插件。需本机 Node.js；改前请完全退出 IDE。升级 Cursor 后需重打。日志：`%TEMP%\cursor-ctxwin.log`。

解锁选模型 ≠ 改上下文窗口；两者可同时启用。

### 代理

FlClash 开着（推荐 SOCKS5 `127.0.0.1:7891`）。路由二选一：

| 模式 | 适用 |
|------|------|
| 打了补丁，走网关原生 | **推荐**；不改 workbench，启动时带进程代理参数 |
| 没打网关补丁 | 会改 workbench 改回官方 API（风险高，需确认） |

**防误触：** Cursor 开着时点「保存」只记启动器偏好，不改 Cursor 文件。真正写入前会确认，并自动备份 settings/argv。误触后点 **「一键还原误触」** 可撤回（含尽量恢复 workbench、删除 DLL、关闭代理开关）。

进程 DLL（Antigravity 同款）**非必要别用**，且要先关 IDE：

| 按钮 | 作用 |
|------|------|
| 写入 DLL | 安装到 Cursor 目录（有闪退风险） |
| 删除 DLL | 删除（会先备份） |
| 还原 DLL | 从备份装回 |
| 还原补丁 | 恢复 workbench 备份（重装 Cursor 后勿用） |
| 一键还原误触 | 还原代理快照 + workbench 备份 + 卸 DLL |

黑屏/闪退时：关 IDE → **一键还原误触** → 再开。exe 版关启动器时若弹 `_MEI` 警告，点确定即可。

### 禁用自动更新

设置 → **禁用自动更新** → **立即应用**（需先关 IDE）。写入 `update.mode: none`，并重命名 `inno_updater.exe`。用启动器启动 IDE 时会自动维持。升级 Cursor 会覆盖补丁/DLL，建议保持禁用。

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
