# 对照笔记：CPA Grok Bot 插件 0.5.6 源码

**对象**：`za/1/8.24/Bot/archives/cpa-grok-bot-plugin-0.5.6-src.zip`（约 78 KB）  
**对照**：`archives/grok-bot-反代.zip`（约 27 MB，含 vendor / `.git`）· 本仓库 [`bot_gateway/`](../bot_gateway/)  
**宿主**：CLIProxyAPI（CPA）v7 插件，`provider=grok-bot`

一句话：**把 Grok Bot / Sand 接到 CPA，对外是 OpenAI `/v1/chat/completions` 与 Anthropic `/v1/messages`。Cursor JWT 走 EnsureSandBox → Box `/sand-stream-relay/.../Stream`。不改 Cursor、不装 Bot 桌面端。CPA 插件加载器只支持 Unix，本机 Windows 启动器不能直接加载这份 `.so`。**

---

## 包内真相

| 项 | 内容 |
|----|------|
| 模块 | `local/cpa-grok-bot-plugin`，Go 1.24，单包 `package main` |
| 版本常量 | `types.go` → `pluginVersion = "0.5.6"` |
| 客户端伪装 | Grok Bot `0.44.0`，`sand` / `sand-desktop`，namespace `prod` |
| 能力 | ModelProvider + AuthProvider + Executor（chat-completions 进出） |
| 不含 | 编译好的 `.so` / `.dylib`；不含 Cursor JS 注入 |

相对旧包 `grok-bot-反代.zip`：这是**可阅读的干净源码树**；旧包是整棵 `plugin/` + 体积膨胀。协议核相同：EnsureSandBox protobuf field 10/11/4/13、Relay 路径与 v136 / 启动器 `DEFAULT_RELAY_PATH` 一致。

---

## 三条授权怎么走流量

| 方式 | 配置 | 上游 |
|------|------|------|
| A Cursor Token（推荐） | `auths/grok-bot-cursor.json`，`auth_method=cursor` | `useBoxRelay` → EnsureSandBox → Box Stream |
| B 浏览器 PKCE | CPA 管理界面，`redirectTarget=sand` | 文档写走 `api2` Stream / RunInference |
| C User Token | `user_token` 换 session | 同上，直连 `api2` |

9/9 之后 B/C 的 `api2` sand Stream 基本不可用；**真能计 Bot 额度的是 A（Box 中继）**。插件 **不** `createAgent` / 不改 Box `host-main.cjs`：Box 没挂过 `/sand-stream-relay` 时，和启动器只领票一样会 404。挂路由仍要 v136 / Claimer 1.4.8 / 启动器「领取并挂路由」。

---

## 对启动器网关（路②）

| 可对照 | 不要搬 |
|--------|--------|
| OpenAI `/v1/models` + chat completions 外壳（计划 C） | CPA 插件 ABI、CGO `.so`、在 Windows 加载器上硬接 |
| `encodeEnsureSandBoxWake` = `{16,1}`、解析 field 10/11/4/13 | 在启动器里再开一套 CPA |
| 识图 / tools 提示词模拟（Box 上原生 tools 会 `resource_exhausted`） | 本轮不需要 |

本仓库已有：领票、挂路由、本机 8765、Cursor 改道。CPA 0.5.6 是**另一客户端**：请求进 CPA，不进 Cursor IDE。与 Direct / 本机网关注入 **不要叠打同一账号的 Cursor 安装**；CPA 本身不写 Cursor。

Windows 上要用这份插件：在 Linux/macOS 或 Docker 里跑 CPA，不把启动器当宿主。
