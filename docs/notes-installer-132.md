# 对照笔记：Sand-Stream-Installer 1.3.2-macos-seal.1

**对象**：`za/1/8.24/Bot/archives/Sand-Stream-Installer-v1.3.2-fixed(1)`（内层 `sand_stream_installer.py`；外层 `(1)` 是重复下载解包壳）。
**对照**：`Bot/installers/sand_stream_installer_tools_grokbot_direct_v131.py`（v1.3.1）+ 本仓库 `launcher/sand_stream.py`（模块 1.3.1）。
**实施**：[plan-sand-stream-v132.md](plan-sand-stream-v132.md)（登记 / 剥离 / 叠打纪律）。审计结论：**两个安装器注入代码均无外联**（唯一 URL 常量 `SAND_ONBOARDING_URL = https://cursor.com/bot/onboarding?product=grok-bot` 定义了但全文件未引用），流量走 Cursor 自身传输层。

一句话：**1.3.2 是「已领资格账号的修复器」+ macOS 重签变体；相对 v1.3.1 它删掉了启动器最有价值的那批层（L7/1M、Task V3、Action V2 白名单、resume/wake），换成更激进的全放行 + 全模型目录子代理；安全体系（外来 marker 检测/卸载）反而是 v1.3.1 的真子集。启动器只做登记与迁移，不搬任何打点。**

---

## 1.3.2 相对 1.3.1 的实质变化

### 删掉的（启动器已有且更强，勿回退）

| 项 | 说明 |
|----|------|
| L7 整层 | MAX_TOKENS/1M、Rules+Skills V4、MCP filesystem、User Rules 全部消失；Direct 注入里的 `agentTokenLimit` 也删了 → 1.3.2 无 1M 覆盖 |
| Task V3 | 「锁父模型 + 禁子代理再派发（`subagentTypeName` 守卫）+ 丢自定义子代理」被反向替换 |
| Action V2 白名单 | 换成 `!1` 恒假 = actionCase **全放行**（BACKGROUND_COMPLETION 现行版；它的 LEGACY 变体反而还是白名单） |
| resume / wake | 无对应物，靠 `defaultSubagentsRunInBackground` + 全放行盖场景 |

### 换上的（九个新 marker，启动器只登记不外打）

| Marker | 形态 | 为什么不搬 |
|--------|------|------------|
| `SAND_MULTITASK_ROUTE_V1` | mode 检查加 `userMessageAction` 限定并放行 MULTITASK | 可参考的**白名单式**写法；真机出现 MULTITASK `mode-not-supported` 时按自家 Action V2 方式扩（OPT-A，未立项） |
| `SAND_BACKGROUND_COMPLETION_V1` | `"!1"/*m*/?"action-not-supported"` 全放行 | 与白名单约定冲突 |
| `SAND_SUBAGENT_RUN_OPTIONS_V1` | `hasUnsupportedRunOptions` 门恒假 | 会废掉「子代理禁再派发」（约定 #5） |
| `SAND_SUBAGENT_FEATURES_V1` | 开 `useClientSideSubagent` + `enableMultitaskMode` + `defaultSubagentsRunInBackground`；LEGACY 还含 `longRunningJobs:!0` | LEGACY 含全局闸；现行的 multitask/后台默认与启动器 wake 语义未验证 |
| `SAND_SUBAGENT_CAPTURE_V1` / `CONFIG_V1` / INVOKE（无独立 marker） | 把父级 `inferenceClient` 捕获进子代理（`function(e,t,H)` / `let P` / `}(t,e.agentToolsClient,e.inferenceClient)`） | OPT-B 前置技巧，仅记录 |
| `SAND_SUBAGENT_TASK_V1` | `taskToolProps:void 0` → 巨对象：父模型 + **state.vscdb 动态目录**（只读 sqlite `ItemTable` → `reactiveStorageServiceImpl...applicationUser` → `aiSettings` + `availableDefaultModels2`，筛 `supportsAgent` 启用项），每个子代理建真 Joe 会话；无 `subagentTypeName` 守卫；`isModelValid:()=>!0` | 与已拍板 Task V3 语义相反；LEGACY 硬编码 claude-fable-5 / kimi-k2.5 |
| `SAND_GLASS_OVERRIDE_V1` | `isGlass?"sand":"sand"/*m*/` | 已有 `SAND_GLASSFIX_V1`，两套玻璃改写难还原 |

### 工程面

- **macOS seal**：`xattr` 去隔离 → `codesign --force --deep --sign -` → verify；install/uninstall 之后各签一次；**重签在文件已写入之后**，签名失败时盘上已是改过的文件。Windows 无签名。
- **版本门**：写死 3.18.9，无 3.19；无 stream/full 分档、无 `missing[]`，约 15 项计数门「全或无」。
- **一进一退**：进的是「先剥后打」（install plan 先 remove 自家再 apply，幂等）+ 状态页展示子代理模型列表；**退的是安全体系**——没有 v1.3.1 的 `KNOWN_SAND_MARKERS` 注册表和 `ANY_SAND_MARKER_RE` 全量扫描，只查 CLIENT/ELIGIBILITY 两个 guard 形状。
- **同串 marker**：CLIENT/ELIGIBILITY/MOVE_EXEC 与启动器同串，不构成外来冲突；区分只能靠**字面量形态**（如 MOVE_EXEC 括号 `p=(!0/*SAND_MOVE_EXEC_V1*/)`）。

---

## 叠打矩阵

| 机器状态 | 该怎么做 |
|----------|----------|
| 只用启动器 | 设置里启用完整/仅 Stream。**不要**跑 1.3.2（同锚互斥：`taskToolProps`、action route、`hre(` Direct；它大概率计数门拒绝或叠写） |
| 已装 1.3.2 → 换启动器 | 首选：先跑 1.3.2 自己的 uninstall（它能清自己）→ 再启用启动器。兜底：启动器「还原/启用」会自动剥 1.3.2 字面量（模块 1.3.1 起），剥不掉的进提示 |
| 已装启动器 → 误跑了 1.3.2 | 它看不见启动器 marker，可能叠写；用启动器「还原 Sand Stream」清场后重新启用 |
| 只要领号 | 用 Claimer 的导入/领取/导出，关掉它的补丁面板（见 notes-sandclaimer-131.md） |

1.3.2 自家的 uninstall **清不掉** v1.3.1 的任何补丁，也清不掉启动器的（RPC/HDRFIX/双轨它都不认识）——所以「先用原工具卸载」只对它自己那一代有效。

---

## 启动器侧已落地的兼容（模块 1.3.1）

1. 9 个新 marker 登记为 `SAND_V132_MARKERS`；status 透出 `installer132: {tool, detected, counts, files}`，不计入 `external_marker_count`、不拒写。
2. `_strip_v132()`：apply 与 restore 入口都先剥 13 组字面量对（含 LEGACY 白名单变体）+ SUBAGENT_TASK 骨架正则（`taskToolProps:\{.*?\}/*SAND_SUBAGENT_TASK_V1*/`）+ GLASS_OVERRIDE 正则（回 ORIGINAL `isGlass?"glass":"ide"`）。
3. 1.3.2 的 Direct 注入体与启动器 `_legacy_direct_stream_injection()` **逐字相同**（无 `agentTokenLimit`、`isGrok45ProductPrompt:i.includes("grok")`），现有 `_strip_direct_stream_injection` 精确清单 + 兜底正则天然覆盖，apply 先剥后写自家（含 grok46 互斥 + 1M）。
4. MOVE_EXEC 括号形态 `p=(!0/*SAND_MOVE_EXEC_V1*/)` 与 LEGACY `p=!0;/*m*/` 进剥离清单；marker 同串仍算自家命中。
5. apply/restore 结束后若 `installer132.detected` 仍为真（骨架对不上等），message 追加「建议先运行该工具自己的卸载」。

## 未验证 / 待真机

- 3.18.9 真机上 1.3.2 打过的机器，roundtrip 后 product.json / 扩展哈希是否仍有偏差（理论上有 `sync_product_checksums` + `_update_extension_hashes` 兜底）。
- 1.3.2 的 `defaultSubagentsRunInBackground` / `enableMultitaskMode` 与启动器 wake（`SAND_SUBAGENT_COMPLETION_WAKE_V1`）在同装场景下的行为——已按「启动器 restore 全清」规避，不做同装验证。
