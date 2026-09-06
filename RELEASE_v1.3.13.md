## Summary
- **Sand-Stream-Installer 1.3.2 兼容**：识别 1.3.2-macos-seal.1 的 9 个新标记（MULTITASK_ROUTE / BACKGROUND_COMPLETION / SUBAGENT_* / GLASS_OVERRIDE），Bot 面板显示残留计数；启用 / 还原会自动把残留迁回原状后再打自家补丁，剥不掉的进缺失明细并提示先跑对方卸载
- **同锚不写坏**：`taskToolProps`、action route、`hre(` Direct 三个同锚点先剥后打；1.3.2 的 Direct 注入自动升级为带 1M 与 Grok 4.6/4.5 互斥的新注入；move_exec 括号 / 分号形态可还原
- **语义不变**：不引入 1.3.2 的激进改法（actionCase 全放行、runOptions 不拦、子代理全模型目录），Task V3 / Action V2 / `supportsSelfSummary:!1` 原样

## 产物
- `CursorLauncher.exe` / `CursorLauncherSetup.exe`
