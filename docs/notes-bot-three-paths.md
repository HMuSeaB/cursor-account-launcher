# 对照笔记：Bot 额度三条路

**对象**：9/9 服务端改口径之后，如何继续使用 Grok Bot / Sand 高级模型。  
**关联**：[notes-box-relay-v136.md](notes-box-relay-v136.md) · [notes-sandclaimer-142.md](notes-sandclaimer-142.md) · [notes-sandclaimer-148.md](notes-sandclaimer-148.md) · [notes-storm-dock.md](notes-storm-dock.md) · [plan-bot-gateway.md](plan-bot-gateway.md)  
**代码**：[`bot_gateway/`](../bot_gateway/)（领票 + 挂路由 + 本机转发 + Cursor 改道注入）。

## A 是什么（领票 + 挂路由）

本地网关 **不会自己变出额度**。它只是把 Cursor 的 Stream 请求转到某个 HTTPS 上游。

A 做的事：用你 **当前 Cursor 已登录账号** 的 token，调用官方 `GrokBotService/EnsureSandBox`，拿到：

- Box 的 `baseUrl`（云端网关地址）
- 一张 **短时 gateway token**
- 可选的 `x-anyrun-network-token`

写入 `%LOCALAPPDATA%\CursorLauncher\bot-gateway\upstream.json`。随后（默认）走 `box_mount`：`createAgent` → `sendPrompt` 让 Box 在 `host-main.cjs` 挂上 `/sand-stream-relay/...`，并用 Connect 空帧探测是否就绪。

A **不是**：改 Cursor 安装目录。若仍长期 404，看 Box Agent 是否拒改 / host 未重启；可复用同一 agent 状态避免重复扣费。

## B 是什么（本机改道）

B 在 `127.0.0.1:8765` 监听与 Box 相同的 Stream 路径，并打开「网关模式」：此时 **禁止再打 Direct**。启用时会：

1. 写 `%LOCALAPPDATA%\CursorLauncher\bot-gateway\listen.json`（`baseUrl=http://127.0.0.1:8765`）
2. 在 `cursor-agent-host` / `cursor-always-local` 的 `applyAuthorization` 注入独立 marker `SAND_LOCAL_BOT_GATEWAY_AUTH_V1`（仅 InferenceService.Stream）
3. 启动本机网关进程；关网关时剥离该注入

须先关 Cursor 再开/关。若已有 Direct 或 v136 `SAND_GROK_BOX_RELAY_AUTH_V1`，拒绝启用。


---

## 三路总表

| 路 | 一句话 | 代表材料 | 启动器关系 |
|----|--------|----------|------------|
| **① 官方 Bot 完善** | 人在 Grok Bot 客户端里直接选高级模型（Fable / Opus 等），靠 Bot 自己的 host + accessToken | 群聊截图（列模型 / apply / 验 `response_info.model`）；Storm Dock 切 Bot 登录态 | **正交**。不管 IDE 补丁；可作「真源对照」 |
| **② Bot 网关反代** | 把 Bot/Box 能力暴露成可调用入口；Cursor（或其它客户端）只改道到网关 | v136 Box Relay、`grok-box-relay.json`、`archives/grok-bot-反代.zip`（CPA 插件）、本仓库 `bot_gateway/` | **可选旁路**。与 `sand_stream` Direct **互斥**；禁止叠打 |
| **③ 脚本补丁** | 改 Cursor workbench / agent-host 的 marker | `Bot/installers/*`、Claimer「打补丁」、启动器 `sand_stream` / Task V3 / Action V2 | **IDE 纪律层**。9/9 后「本机 sand 直连计额度」已基本死 |

截图里「38 models via accessToken」「Claude Fable 5.1 1M Max」「看服务端回的模型字段」属于 **路①**；`ERROR_OUTDATED_CLIENT` / checksum 是官方 Bot host 细节，不是 Cursor JS 补丁问题。

---

## 为什么②比③更省事（产品判断）

1. **锚点不跟 Cursor 小版本碎**：网关协议相对稳定；③ 每个 3.18→3.19 都要重锚。  
2. **失败面集中**：票刷新 / EnsureSandBox / 上游 401 在一处修；③ 是 N 个 marker × M 个文件。  
3. **与启动器边界清晰**：启动器继续做管家 + IDE 纪律；额度走网关时 **只接网关，不叠 Direct**。  
4. **① 是真源**：Bot 里跑不通的模型，网关转发也救不了——先在①验证，再接到②。

---

## 推荐顺序（已拍板方向）

1. **② 做稳本地网关骨架**（本轮：`bot_gateway` 健康检查 + 配置契约 + Stream 路径 stub）。  
2. **① 当对照**：Bot 里能跑通的模型 / 头，才是网关该转发的。  
3. **③ 收缩**：启动器保留 Task/Action/原生体验补丁；外围大一统脚本进档案，不再加码「伪装计额度」。

未立项（见 plan）：CPA `/v1/models` 兼容层、外置 v136 marker 一键剥离、路①宿主脚本。

---

## 叠打红线（三路共用）

```
禁止：启动器 Direct + v136/本机网关改道 + Claimer「打补丁」任意两者同时写 Cursor。
允许：只用启动器管家切号；额度另开 Bot（①）或只接一条网关（②）。
```
