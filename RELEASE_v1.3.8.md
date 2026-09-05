## Summary
- **Sand Stream 双档**：设置里主按钮「启用完整」、次按钮「仅 Stream」；完整档默认可取消「含 Task/子代理」
- 两档都强制 **HDRFIX_V2**（Agent 走 `ide`，其余 `sand`），避免 Agent 路由打架
- 补丁核对齐 1.1.9：条件化 Stream（有 `runInference` 不短路）、RPC 改写、transport→api2、move_exec
- 尽力打：缺 Task/wake 不整单失败，状态里列出缺失层
- **崩溃原因**：设置「日常状态」读取 Cursor 日志，识别插件激活失败、扩展宿主崩溃、GPU、workbench 语法错误
- 探测本机账号：以 JWT `sub` 为准，避免捡到上个账号的缓存邮箱 / WS token；导入时不再把 `user_xxx::jwt` 拆成裸 JWT

## 产物
- `CursorLauncher.exe` / `CursorLauncherSetup.exe`

## Sand 用法
1. 关 IDE → 设置 → **启用完整**（或只要对话则 **仅 Stream**）
2. 不全时看缺失项，不必整单回滚
3. 用启动器重启 Cursor，抓包确认 `aiserver.v1.InferenceService/Stream`
