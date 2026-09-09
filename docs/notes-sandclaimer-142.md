# 对照笔记：SandClaimer 1.4.2

**对象**：`za/1/8.24/Bot/archives/SandClaimer-源码分享-1.4.2.zip`（`sand_patch.TOOL_VERSION = "1.4.2"`）  
**对照**：同目录 1.3.1 解压树 + [notes-sandclaimer-131.md](notes-sandclaimer-131.md)；本仓库 `launcher/sand_stream.py`（`MODULE_VERSION = 1.3.1`）  
**Box 引擎**：包内 `grok_box.py` = 近亲 v136（`TOOL_VERSION = "1.4.4-grokbot-box-relay.1"`，仅 `3.19.13`）；独立脚本见 [notes-box-relay-v136.md](notes-box-relay-v136.md)  
**用途**：以后看 Claimer 1.4.x 先读这份；**不要**把整包当启动器升级源。  
**审计**：白名单源码分享包；token 仍只打 Cursor 官方 + 公开 DoH；账号落 `%LOCALAPPDATA%\SandClaimer`。群里 Nuitka exe 若不是此包编的，另审。

一句话：**1.4.2 主业仍是领资格；本机「打补丁」核还是 STREAM_RPC / LOCAL_ACTIONS（现宣称覆盖 3.18.9~3.19.13）；9/9 后计 Bot 额度改走内嵌 grok_box（委托 Box Relay），与「打补丁」互斥。启动器主业仍是管家 + 原生网关 Direct——两套不能叠打。**

---

## 相对 1.3.1 的实质变化

### 新增文件

| 文件 | 角色 |
|------|------|
| `grok_box.py` | 内嵌 Box Relay 引擎（近 v136）；`provision_and_install` / `uninstall` |
| `grok_login.py` | 早期「登录 Grok Bot 桌面客户端写 sand-secrets」路；协议复述自 [Storm Dock `grok_bot`](notes-storm-dock.md)；**保留参考，默认不用** |
| `grok_relay.py` | 解密 `gateway-descriptor.json` → 写 `grok-box-relay.json`；**默认不用**（桌面票路 404） |
| `embed_icon.py` | 打包辅助 |

### 产品口径（README / `app.py`）

1. **9/9 服务端**：拒收 Cursor 登录票 + sand 身份直连 Stream（详见 v136 笔记）。  
2. **「一键接入 Grok」**：进程内跑 `grok_box.provision_and_install()`（前置：Cursor=3.19.13、已登录有额度号；macOS 要 node）。  
3. **「打补丁」不再注入 Grok 改道**：`_inject_grok_runtime_auth` 仍留在 `sand_patch.py`，但 apply 路径**不再调用**；`applyAuthorization` 改道整块交给 grok_box / 外置 v136，避免抢锚。  
4. **用法纪律（官方自述）**：3.19.13 接 Grok → 只点「一键接入 Grok」；**别再点「打补丁」**（两者都改 Cursor，会互相覆盖）。  
5. `sand_patch` 版本门：`SUPPORTED_CURSOR_MIN/MAX = 3.18.9 ~ 3.19.13`，推荐构建 `3.19.13`（SHA `dd066f33…`）。

### 补丁核相对 1.3.1（未翻案的部分）

仍在、且与启动器冲突的核心未变：

| Marker / 能力 | 含义 | 对启动器 |
|---------------|------|----------|
| `SAND_STREAM_RPC_V1` | 剥 Joe / 改 attempt 入口 stream | **与 L2 Direct 相反** |
| `SAND_LOCAL_ACTIONS_V1` / `SAND_SUBAGENT_LOCAL_V1` | 放宽本地 action / 子代理 | 与 Action V2 **同锚** |
| `SAND_MEMBERSHIP_SPOOF_V1` / `MAXMODE` / `MODEL_UNLOCK` 等 | 显示层 | 启动器隔离在 `model_unlock` |
| `HDRFIX` / `GLASSFIX` / RPC 系 | Claimer 自有 | 启动器已有 HDRFIX_V2 等，叠打危险 |
| 1.3.3+ 双形状正则 | 5 条必需规则兼 3.18 / 3.19 锚点 | 说明 Claimer 补丁轨在追 3.19，但核仍是 STREAM_RPC，不是启动器 Direct |

1.3.1 笔记里的「不必搬 / 叠打」结论 **对 1.4.2 的「打补丁」按钮仍然成立**。

---

## 各自优势

### 启动器强在哪（相对 1.4.2）

| 点 | 说明 |
|----|------|
| L2 核 | Joe Direct / 3.19 `class J`；Claimer「打补丁」仍偏 STREAM_RPC |
| 双轨 + 尽力打 | Claimer 补丁仍偏计数/版本门；Box 一键更是写死 3.19.13 |
| Task V3 / Action V2 纪律 | Claimer LOCAL_ACTIONS 与产品约定冲突 |
| 管家能力 | 切号/额度/代理/更新拦截；Claimer = 领号 + 切号 + 补丁/Grok 按钮 |
| 会员伪装隔离 | Claimer 仍可写进同一套 sand_patch |

### 1.4.2 强在哪（不必因此改核）

| 点 | 说明 | 启动器怎么用 |
|----|------|----------------|
| **领取** | trial / 团队 / 三池 / 导出 | **不迁** |
| **Box Relay 一键** | 内嵌 grok_box，对准 9/9 后 Bot 额度 | **不迁整包**；见 v136 笔记「另开评估」 |
| **补丁报告** | `patch_report` 逐步/逐规则 | 报告层可参考，不搬安装编排 |
| **DoH / CDP** | 领号场景 | 另工具 |
| 废弃桌面登录路的记录 | `grok_login`/`grok_relay` 说明为何 404 | 避免启动器重蹈「桌面 Grok Bot 取票」 |

---

## 劣势 / 坑（1.4.2 对启动器）

1. **「打补丁」仍会卸/盖启动器 Direct**（STREAM_RPC 逻辑未废）。  
2. **「一键接入 Grok」与启动器抢 `applyAuthorization`**；启动器 restore **不认识** Box Relay marker。  
3. **UI 上两个会改 Cursor 的按钮**：用户极易叠打；必须以文案/设置互锁，启动器侧也要会报残留。  
4. 内嵌 `grok_box` **落后独立 v136 半拍**（无 `.2-linux31913` / 无 Linux sibling）。需要 Linux 3.18.9 Box 时用独立 v136 + v131，不要指望 Claimer 内嵌引擎。  
5. README 写「会在下载目录找外置 v136」；当前 `app.py` 实际是 **进程内 import grok_box**——以源码为准，外置路径是文档残留口径。  
6. 探针 / 配置路径仍可能落在 `SandClientMode` / `SandClientModeStream` 下；别当分享材料。

---

## 不必搬进启动器

在 1.3.1「禁止表」之上追加：

| 禁止 | 原因 |
|------|------|
| 内嵌整份 `grok_box.py` | 与原生网关产品线冲突；版本还不是最新独立脚本 |
| 默认启用 EnsureSandBox 开箱 | 失败面、账号/额度耦合、与管家状态机两套真相 |
| 复活 `grok_login` / Storm Dock 桌面客户端路当网关 | 上游已判定 Box 无 relay → 404；写票工具与计额度不是一回事 |
| 因 1.4.2 有 3.19 正则就采纳 STREAM_RPC | 核仍然反 L2 |

**可另开一轮：**

- 仅登记/剥离 `SAND_GROK_BOX_RELAY_AUTH_V1`（含静态 V141 与自刷新块），status 提示「先跑 Claimer 退出 Grok / v136 uninstall」。  
- 真机验证：启动器 Direct 在 9/9 后是否仍计额度；据此改产品文案，而不是先搬 Box。

---

## 叠打

| 机器状态 | 该怎么做 |
|----------|----------|
| 只用启动器 | 启用完整/仅 Stream。不要点 Claimer「打补丁」或「一键接入 Grok」。 |
| 只要领号 | Claimer 导入/领取/导出；**关掉补丁面板与 Grok 按钮**。 |
| 只要 3.19.13 Bot 额度（外围） | Claimer「一键接入 Grok」**或**独立 v136；不要同时「打补丁」。 |
| 已打 Claimer 补丁 → 换启动器 | 先 Claimer **回退**，再启动器启用。 |
| 已一键 Grok → 换启动器 | 先「退出 Grok」/ v136 uninstall，再启动器还原并启用。 |
| 已装启动器 → 误点了任一按钮 | 对应工具卸载 → 启动器还原 → 再启用。 |

`restore` 目标（启动器侧，尚未落地）：Direct 新旧字面量、STREAM_RPC、Task/Action、L7/L8、LOCAL_ACTIONS（能剥则剥）、**外加** Box Relay auth 块。
