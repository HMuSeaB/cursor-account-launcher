## Summary
- 修复「补丁自检失败：Circular reference detected」
- 原因：`autofix` 结果里又嵌了整份 diagnostic，而 diagnostic 又挂回 `autofix`，形成环；pywebview 序列化时报错
- 已去掉嵌套，并加回归测试防止再犯

## 产物
- `CursorLauncher.exe` / `CursorLauncherSetup.exe`
