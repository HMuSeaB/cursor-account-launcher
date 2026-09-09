# Bot 网关骨架（路②）

本地 HTTP 服务，契约对齐 v136 的 `grok-box-relay.json`。

- **做**：EnsureSandBox 领票、尽量在 Box 挂 `/sand-stream-relay`、本机 `/health` + Stream 透传。
- **不做**：改 Cursor JS、与启动器 Direct 叠打。

详见 `docs/notes-bot-three-paths.md`、`docs/plan-bot-gateway.md`、`docs/notes-sandclaimer-148.md`。

## 运行

```powershell
cd cursor-launcher
python -m bot_gateway provision   # A：领票 + 挂路由 → upstream.json
python -m bot_gateway             # 监听 127.0.0.1:8765
```

## Upstream 配置

默认读：

`%LOCALAPPDATA%\CursorLauncher\bot-gateway\upstream.json`

或环境变量 `BOT_GATEWAY_UPSTREAM` 指向已有 `grok-box-relay.json`。

最小字段：

```json
{
  "version": 1,
  "baseUrl": "https://example-box-gateway.example",
  "token": "short-lived-gateway-token",
  "relayPath": "/sand-stream-relay/aiserver.v1.InferenceService/Stream"
}
```

## 探活

```powershell
curl http://127.0.0.1:8765/health
```

`ready: true` 只表示 JSON 已加载，**不**保证上游能计额度。
