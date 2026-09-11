# 任务看板：Material You 色彩圆盘与星云暮紫美化

- [x] **需求与视觉意图分析** <!-- id: 0 -->
  - 分析用户提供的图一（莫兰迪温润藕粉暮紫、胶囊按钮）与图二（Material You 动态色彩芯片浮窗、居中对勾）。
- [x] **移除原生的 select 下拉框** <!-- id: 1 -->
  - 从 `web/index.html` 移除 `<select id="selectColorTheme">`。
  - 新增调色盘图标按钮 `#btnColorPalette` 与气泡浮层 `#colorPalettePopover`。
- [x] **精调星云暮紫（violet）暗黑质感** <!-- id: 2 -->
  - 参考图一将暗色模式的紫调微调为深藕粉暮紫（`#181518` / `#252025` / `#ded1d5` / `#d8b4c0`）。
- [x] **实现 Material You 风格色彩芯片** <!-- id: 3 -->
  - `conic-gradient` 四分色圆饼卡片 `.palette-chip` 与居中暗色白勾 `.palette-check`。
  - 顶部增加当前色彩名称标签 `.palette-active-name`。
- [x] **交互事件与持久化** <!-- id: 4 -->
  - 点击按钮展开/收起浮窗，点击芯片无缝换肤，点击浮窗外或按 ESC 键自动关闭。
  - 数据持久化于 `localStorage`，并在顶栏调色盘按钮提供呼吸光点联动。
- [x] **测试验证与发版** <!-- id: 5 -->
  - 通过 `node -c` 检查 JS 语法。
  - 运行并通过全量 239 项 pytest 单元测试。
