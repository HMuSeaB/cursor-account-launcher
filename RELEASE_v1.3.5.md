## Summary
- 主界面「补丁自检」+ **一键补齐**（仅 MAX → 500k → 网关原生代理）
- Cursor 升级后提示重打；启动器检查 GitHub 是否有新版本
- workbench 写入前/后预检加强（括号平衡、长度），失败自动回滚快照
- 旧 bajie / model-unlock 备份迁入统一 `workbench/` 栈
- 设置页去掉重复入口，完整解锁更深藏；补丁 API 抽到 mixin
- 增加真实 workbench 片段回归测试

## 产物
- `CursorLauncher.exe` 绿色版
- `CursorLauncherSetup.exe` 安装包

## 用法
打开启动器看顶栏：缺啥点「一键补齐」。IDE 开着会先关再补。
