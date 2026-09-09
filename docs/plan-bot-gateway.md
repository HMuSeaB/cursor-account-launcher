# 实施计划：Bot 网关骨架（路②）

**目标**：在启动器仓库落地一个**可运行、可测、不写 Cursor** 的本地 Bot 网关骨架，契约对齐 v136 的 `grok-box-relay.json` + Stream 路径。  
**对照**：[notes-bot-three-paths.md](notes-bot-three-paths.md) · [notes-box-relay-v136.md](notes-box-relay-v136.md) · `archives/grok-bot-反代.zip`（CPA 插件，另形态）  
**发版意向**：不 bump 启动器版本；`bot_gateway` 独立模块，默认不挂进 `sand_stream` apply。

---

## 审核要点（已按此执行）

1. **范围**：配置读写、`/health`、Stream 路径占位（有 upstream 则透传二进制 body，无则明确 503）。  
2. **不做**：EnsureSandBox、注入 `applyAuthorization`、会员伪装、subprocess 代跑 v136。  
3. **密钥**：日志与 health **永不打印** token / refresh.accessToken。  
4. **依赖**：仅 Python 标准库（`http.server`），不增 `requirements.txt`。

---

## 步骤与验收

| # | 做什么 | 验收 |
|---|--------|------|
| 1 | 文档：三路对照 + 本计划 | `docs/notes-bot-three-paths.md`、`docs/plan-bot-gateway.md` 可读；外链挂到 outer notes / Bot README |
| 2 | `bot_gateway/config.py`：解析 v1 relay JSON | 缺字段 / 非 https baseUrl → 明确错误；`redacted_summary()` 无密钥 |
| 3 | `bot_gateway/server.py`：listen + `/health` + Stream 路径 | `python -m bot_gateway` 起来；GET health 200；无 upstream 时 POST Stream → 503 JSON |
| 4 | `bot_gateway/upstream.py`：可选 HTTP(S) 透传 | 单测 mock；真机 upstream 本轮不强制 |
| 5 | `tests/test_bot_gateway.py` | `pytest tests/test_bot_gateway.py` 通过 |

---

## 配置契约（与 v136 对齐）

```json
{
  "version": 1,
  "baseUrl": "https://…",
  "token": "…",
  "headers": {},
  "relayPath": "/sand-stream-relay/aiserver.v1.InferenceService/Stream",
  "accountFingerprint": "…",
  "mintedAtMs": 0,
  "refreshAfterMs": 3600000,
  "refresh": {
    "backendUrl": "https://…",
    "accessToken": "…",
    "machineId": "…"
  }
}
```

本机网关默认路径：`%LOCALAPPDATA%\CursorLauncher\bot-gateway\upstream.json`  
亦可 `BOT_GATEWAY_UPSTREAM` 环境变量指向任意 JSON（可直接复用已有 `grok-box-relay.json`）。

本机监听：`BOT_GATEWAY_HOST`（默认 `127.0.0.1`）+ `BOT_GATEWAY_PORT`（默认 `8765`）。

对外暴露路径（与 Box relay 同形，便于以后 Cursor 只改 `baseUrl` 指本机）：

- `GET /health`
- `POST /sand-stream-relay/aiserver.v1.InferenceService/Stream`

---

## 风险

| 风险 | 缓解 |
|------|------|
| 误以为骨架已能计额度 | health / 503 文案写明「stub；需有效 upstream」 |
| 与启动器 Direct 叠打 | 文档红线；骨架不写 Cursor |
| 日志泄票 | redacted_summary；禁止 print config 全文 |

---

## 进度

- A：EnsureSandBox → `upstream.json` — **已做**
- A+：Box 内挂 `/sand-stream-relay`（`box_mount.py`）— **已做**
- B：本机监听 + 与 Direct 互斥 — **已做**
- B+：Cursor `applyAuthorization` 改道到本机 `8765`（独立 marker `SAND_LOCAL_BOT_GATEWAY_AUTH_V1`，可关网关剥离）— **已做**

## 后续

- C：OpenAI `/v1/models` 兼容层（对齐 CPA 插件形态）  
- D：登记/剥离外置 Box Relay marker（v136），方便误装还原  
- 票自动刷新（upstream.refresh）  
- 路①：官方 Bot 宿主脚本整理
