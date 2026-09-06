## Summary
- **模型墙只检查不代写**：一键补齐只打 MAX / 500k / 代理；YC / Sub2API 必须用扩展面板
- **读不到版本不再当升级**：`product.json` 坏了会回退读 `Cursor.exe` 文件版本，不再把 `"?"` 当成一次升级
- **侧边栏 Pro 不怕点**：设置里单独「写入侧边栏」——只改 `state.vscdb` 的 `applicationUser.membershipType`，不改 workbench、不写 stripe；已经是目标套餐则跳过。完整解锁仍折叠，那条才会改程序文件

## 产物
- `CursorLauncher.exe` / `CursorLauncherSetup.exe`

## 侧边栏显示
1. 关 IDE → 设置 → **写入侧边栏**（默认 Pro Plan）
2. 用启动器重启 Cursor
3. 账单页仍显示真套餐，不要为了显示去点完整解锁
