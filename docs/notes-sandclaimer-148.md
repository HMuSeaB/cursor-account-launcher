# 对照笔记：SandClaimer 1.4.8 + 飙车群源码 1.1.3

**对象**：
- `za/1/8.24/Bot/archives/SandClaimer-源码分享-1.4.8.zip`
- `za/1/8.24/Bot/archives/飙车群源码1.1.3_简洁.zip`（内层 `cursor bot v3/`）

**对照**：1.4.2 笔记 · [notes-box-relay-v136.md](notes-box-relay-v136.md) · 本仓库 [`bot_gateway/`](../bot_gateway/)  
**归档**：两包已从 Bot 根目录移入 `archives/`。

一句话：**1.4.8 把「打补丁」收成薄封装，计额度整段交给内嵌 `grok_box`（`1.4.6-grokbot-box-relay.1`）：EnsureSandBox → Box 内挂 `/sand-stream-relay` → 注入 Cursor。飙车群 1.1.3 是同族 Claimer 简包（`sand_patch=1.13` + `grok_box=1.4.4-….2`）。启动器网关线对齐「领票+挂路由」，仍不自动注入 Cursor。**

---

## 版本真相

| 包 | 产品 `TOOL_VERSION` | 引擎 `grok_box` | Cursor |
|----|---------------------|-----------------|--------|
| SandClaimer 1.4.8 | `sand_patch.py` → **1.4.8** | **1.4.6-grokbot-box-relay.1** | 写死 **3.19.13** |
| 飙车群 1.1.3 简洁 | `sand_patch.py` → **1.13**（包名写 1.1.3） | **1.4.4-grokbot-box-relay.2** | **3.19.13** |
| 独立 v136（本机归档） | — | **1.4.4-….2-linux31913** | 3.19.13 + Linux 3.18.9 sibling |

1.4.8 相对 1.4.2：`sand_patch` 文首写明 **9/9 后旧 STREAM_RPC 自研锚点整段移除**；`install` = `grok_box.provision_and_install`。README 里仍有「找外置 v136」口径，**以源码为准：进程内跑 grok_box**。

飙车群：目录名 `cursor bot v3`，功能面仍是领号+切号+补丁+内嵌 grok_box；无 `embed_icon` / `package_all` 等完整打包脚本，属「简洁」发行。

---

## 对启动器网关（路②）可搬什么

| 搬 | 不搬 |
|----|------|
| `BOX_RELAY_PROVISION_PROMPT` + `createAgent` + `sendPrompt`（先开 `/events`）+ Connect 帧探测 | `provision_and_install` 里的 Cursor `applyAuthorization` 注入 |
| EnsureSandBox 领票写 `upstream.json` | 旧 STREAM_RPC / LOCAL_ACTIONS「打补丁」核 |
| agent 复用状态（防重复扣费） | 会员伪装 / sand_advanced |

本仓库已落到：`bot_gateway/provision.py`（领票）+ `bot_gateway/box_mount.py`（挂路由）。UI「领取并挂路由」= 领票+挂路由；「开本机网关」= 本机监听且禁 Direct。

---

## 叠打

- Claimer 1.4.8「一键接入」会 **写 Cursor**；启动器网关模式 **不要**再点那套。  
- 飙车群若仍走完整补丁面板，与 Direct / 本机网关同样互斥。  
- 只要领号：用 Claimer 导入/领取即可。
