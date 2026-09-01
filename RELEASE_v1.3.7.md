## Summary
- **Sand Stream 模式**：设置页独立开关，注入 Stream 五件套，Bot 对话走 `InferenceService/Stream`（非 `AgentService/Run`）
- **500k**：`patch-ctxwin` 同时改写 `InferenceService/Stream` 路径（Sand + 500k 场景）
- 与「仅 MAX / 500k」分离；启用前需关 IDE

## 产物
- `CursorLauncher.exe` / `CursorLauncherSetup.exe`

## 推荐（Sand Bot）
1. 关 IDE → 设置 → 启用 Sand Stream  
2. 可选：启用 500k 回包  
3. 网关原生 + 进程代理 → 用启动器重启 Cursor  
4. 抓包确认 `aiserver.v1.InferenceService/Stream`
