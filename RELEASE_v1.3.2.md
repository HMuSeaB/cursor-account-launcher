## Summary
- Cursor 运行中点「保存」只记偏好，不再热改 settings / argv / workbench（避免误触后只能重装）
- 真正写入前自动备份；新增「一键还原误触」（还原快照、尽量恢复网关补丁、卸 DLL、关闭代理开关）
- `http.noProxy` 改为数组；启动 IDE 不再偷偷注入文件
- 网关原生为默认路由；改回官方 / 写入 DLL 需二次确认

## 产物
- `CursorLauncher.exe` 绿色版
- `CursorLauncherSetup.exe` 安装包

## 误触急救
关 IDE → 启动器代理页 → **一键还原误触** → 再用启动器启动
