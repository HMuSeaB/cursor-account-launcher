## Summary
- 新增「仅解锁 MAX」：只改 `hideMaxToggle`，已有 YC 模型墙时不必完整解锁
- 侧边栏套餐可改 Pro / Ultra / Team / Pro+ / Free；默认 Pro，不再写死 Team Plan
- 修复完整解锁黑屏：会员正则误命中上千处 `"pro`；`hideMaxToggle:!1;` 分号会截断对象字面量
- 新增「修复黑屏」「修正侧边栏显示」；会员补丁超过 4 处会中止写入
- 记录易错点：模型墙 / MAX / 黑屏是三条线，重装 Cursor 不清用户缓存

## 产物
- `CursorLauncher.exe` 绿色版
- `CursorLauncherSetup.exe` 安装包

## 用法
关 IDE → 设置 → **仅解锁 MAX** → 用启动器重启并新开对话。命中应是 `显示MAX×1~3`，不要出现 `会员×几百`。
