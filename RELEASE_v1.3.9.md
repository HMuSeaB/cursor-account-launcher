## Summary
- **Grok Bot Direct**：官方 `RunInference` 会拒 sand 身份，L2 改为无条件 Joe Direct Stream；仍强制 HDRFIX_V2 + RPC
- **完整档**：Task V3 / Action V2（继承父模型与 1M，去掉 `mode-not-supported`），另加工作区能力与首问加速（Rules Preseed / `push_req_context` 50ms）
- 设置页把 Grok Bot 从急救补丁里拆出来，默认只显示状态，补丁层明细折叠
- 长对话保持 `supportsSelfSummary: false`，避免摘要请求走错路由

## 产物
- `CursorLauncher.exe` / `CursorLauncherSetup.exe`

## Grok Bot 用法
1. 关 IDE → 设置 → **Grok Bot** → **启用完整**（只要对话通路则 **仅对话**）
2. 不全时看「还缺」或展开「补丁层明细」，不必整单回滚
3. 用启动器重启 Cursor，抓包确认 `aiserver.v1.InferenceService/Stream`
