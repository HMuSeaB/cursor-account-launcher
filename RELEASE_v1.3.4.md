## Summary
- workbench 写入统一走备份 → 预检 → 原子写入网关（模型解锁 / 网关路由共用）
- 设置页「日常状态」：网关 / MAX / 500k / 代理四格清单 + 单一「下一步」
- IDE 开着时补丁类按钮硬锁；关 IDE 后可自动继续下一步，少误点
- DLL / 完整解锁等收进高级危险区；一键急救还原走统一备份栈
- CLI：`python scripts/diagnose-workbench.py`

## 产物
- `CursorLauncher.exe` 绿色版
- `CursorLauncherSetup.exe` 安装包

## 推荐用法（网关原生）
1. 关 IDE → 打开设置看顶栏清单  
2. 只点蓝色「下一步」（缺啥补啥：MAX → 500k → 代理）  
3. 用启动器启动 Cursor；日常别开高级危险区  
