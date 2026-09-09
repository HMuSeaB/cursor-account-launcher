## Summary
- **分段导航与账号卡片 UX 升级**：现代化 Segmented Tabs 布局（账号管理 / Grok Bot 与补丁 / 网络代理 / 系统与工具），账号卡片紧凑化操作与更多操作折叠菜单
- **Cursor Agent CLI 独立支持**：支持通过 `crsr_...` API Key 调起终端独立的 Cursor Agent CLI，账号详情可绑定专属 Key，添加账号粘贴 `crsr_` 自动识别并引导启动
- **插件与 CLI MCP 服务管理**：一站式集中管控全局与工作区的 MCP 服务（tc-mcp、Tiancai、池鸢等），支持一键切换禁用/启用，支持带高风险二次确认对话框的彻底删除与数据目录归档
- **防封防掉号安全加固**：添加账号识别拦截纯 acc（短期 JWT）并弹窗提示掉号风险与引导长效 Session Token；账号卡片标黄警告；批量用量刷新加入平滑延时防止单 IP 触发官方 WAF 连坐封号

## 产物
- `CursorLauncher.exe` / `CursorLauncherSetup.exe`
