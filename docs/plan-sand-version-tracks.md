# 实施计划：按 Cursor 版本分流 Sand 补丁（3.18 优化 + 3.19 双轨）

**目标**：Grok Bot 不再只用一个写死的 `ANCHOR_VERSION = "3.18.9"`。先识别本机 Cursor 版本族，再走对应补丁轨；**3.18.9 / 3.18.25 继续作为一等公民**，并补上 v131 留给 3.18 的缺口。3.19.13 用另一套锚点，避免「界面显示已注入、实际仍走 `RunInference`」。  
**发版意向**：本轮**不 bump** 启动器版本。`MODULE_VERSION` 已提到 `1.3.0`。

对照：[kuk-888/cursor-account-manager](https://github.com/kuk-888/cursor-account-manager) **2.3.20**（2026-09-05）。3.18 仍走 Joe Direct + Task V3 / Action V2；3.19 另套 L1/L2/L6 形态。尽力打 + `missing[]`。

---

## 审核要点（请先拍这几条）

1. **分流方式**：版本族（`product.json`）为主，**单文件内容嗅探**兜底。不做成「只信版本号」或「完全不看版本、两套锚点硬叠」。
2. **3.18 本轮要优化的**：4.6/4.5 产品 prompt 互斥、补 `657.js`/`61.js`/`675.js`、版本提示把 3.18.25 当匹配而不是「新于 3.18.9」。
3. **3.19 本轮做到哪**：L0–L5 + Direct 必须能打上；L6 在 3.19 新形态上尽量保持启动器 V3/V2 语义，**不回退**成 CAM 的 Task V2 / Action V1。对不上的层进 `missing[]`，不整单拒绝。
4. **明确不做**：CAM 的「缺条拒写」、VSIX / 隔离浏览器、会员伪装、把 `supportsSelfSummary` 改成 `true`。

下面「待确认」如果和这四条冲突，以你批注为准。

---

## 现状问题

| 现象 | 原因 |
|------|------|
| 3.18.25 设置页提示「锚点按 3.18.9，可能不全」 | `versionOk = version.startswith("3.18.9")`；3.18.25 被当成偏差 |
| 3.19.13 上旧补丁可显示已注入，Bot 额度用不上 | 3.19 重写本地 Agent 内核；3.18 的 `gate-off` 三元、`Joe`/`cre`/`nre`、Action 原文都对不上 |
| 选 Grok 4.6 仍带 4.5 product prompt | 3.18 Joe 注入里 `isGrok45ProductPrompt:i.includes("grok")`，4.6 也被算进 4.5 |
| 3.18.25 部分锚点在 agent-host 分包里 | v131 写了「缺命中再补 `657.js`/`61.js`/`675.js`」，`TARGET_SPECS` 还没加 |
| 扫描可能漏过改名后的 Direct 锚点 | `_SAND_PATCH_HINTS` 仍含死字面量 `function hre(` |

CAM 2.3.20 已经用「先打 3.18 字面量，再打 3.19 新形态」修了 3.19.13；直连流 metadata 必须是 `{promptModelInfo, useDsv3Harness}`，不能把模型函数整包塞进 `resolvedModelMetadata`。

---

## 产品约定（建议拍板）

1. **版本族，不是单个补丁号。**  
   - 轨 `3.18`：已测 **3.18.9、3.18.25**；其它 `3.18.x` 走同一套正则，缺项进 `missing[]`。  
   - 轨 `3.19`：已测 **3.19.13**；其它 `3.19.x` 走 3.19 形态，未测构建允许不全。  
   - `< 3.18`：仍劝退硬打 L1–L7（3.12 没有 agent-host）；HDRFIX / RPC 能打的照打。  
   - 读不到版本：按文件内容嗅探；嗅探失败默认 `3.18`（保持现网行为），hint 写「版本未知，按 3.18 轨试打」。
2. **同一文件只走一条 Direct 注入。** 3.18 用 Joe + `cre`/`nre`；3.19 用 `class J` + `oe(...)` 包进 `promptModelInfo`。禁止把 3.19 metadata 形态写进 3.18，也禁止把 3.18 `nre(a,o)` 写进 3.19。
3. **卸载与版本无关。** `restore` 必须能清 3.18 与 3.19 全部本模块标记（用户可能升过级、或上次打错轨）。
4. **仍尽力打。** 不跟 CAM 的 `EXPECTED_LIFECYCLE` 缺条拒写。
5. **3.18 的 Task V3 / Action V2 / HDRFIX / RPC / L7 / L8 语义不变**，只修版本识别和 3.18 缺口。
6. **3.19 的 Action 不要把 `mode-not-supported` 请回来。** CAM 3.19 Action 仍对 `userMessageAction` 卡 AGENT 模式；启动器在 3.18 已删掉这条。3.19 新原文上应做「V2 语义的 3.19 变体」，对不上就 `missing`，不要为了命中率装回 V1。

档位不变：`stream` = L0–L4；`full` = 上 + L5，勾选子代理再加 L6–L8。

---

## 分流设计（为什么不选更简单的）

| 方案 | 做法 | 不选原因 / 选用原因 |
|------|------|---------------------|
| A. 只看 `product.json` | `3.18.*` → 3.18 补丁，`3.19.*` → 3.19 补丁 | 版本读失败（`?` / 空）会打错轨；且 Direct 类名是文件级的，不能只信版本 |
| B. 只看内容、两套锚点都试（纯 CAM） | 每文件先 3.18 字面量再 3.19 字面量 | 设置页无法稳定显示「当前轨」；3.18 文件里偶发撞上 3.19 子串时难解释 |
| **C. 混合（采用）** | `resolve_patch_track(version)` 定**默认轨**；每个文件的 Direct / L1 / L6 再按**本文件特征**选注入体 | 版本给 UI 和默认策略；内容防止 3.19 内核改名后版本号还对、锚点已变 |

默认轨规则：

```
3.19.x          → "3.19"
3.18.x          → "3.18"
其它已识别 semver → "other"（只打通用层：HDRFIX / RPC / eligibility / client-type）
读不到            → 嗅探；否则 "3.18"
```

单文件嗅探（Direct 注入选型，优先级高于默认轨）：

- 出现 `class J{constructor(e,t,n,o)` 且带 `.Ycw(` → **3.19 Direct**
- 出现 `new Joe(` 或 3.18 Direct 锚点正则 → **3.18 Direct**
- 都没有 → 本文件不打 Direct（计 `missing`，不写坏）

L1 / L6 同样：先试当前轨的 ORIGINAL，命中再写；未命中再试另一轨的 ORIGINAL（防止「版本显示 3.18、实际已是 3.19 内核」）。**同一 marker 只允许一种 PATCHED 形态存在**；apply 时若已有另一轨的 Direct 字面量，先剥再写当前选型。

---

## 模块与接口

仍只改 Sand Stream 这条线，不新开包。契约加在现有函数上，避免 `app.py` 大改。

```
PatchTrack = Literal["3.18", "3.19", "other"]

SUPPORTED = {
    "3.18": ("3.18.9", "3.18.25"),
    "3.19": ("3.19.13",),
}

resolve_patch_track(version: str, content: str = "") -> dict
    # track, source ("version"|"content"|"default"),
    # tested: bool,  # 是否在 SUPPORTED 列表里
    # hint: str

apply_patch_to_content(..., track: str | None = None) -> (str, PatchStats)
    # track=None 时对本文件嗅探；apply() 传入 layout 默认轨

status / sand_stream_status 增加：
    patchTrack, trackSource, testedBuild, supportedTracks, versionOk
```

`versionOk` 新语义：**当前轨在 `SUPPORTED` 里**（3.18.25 为 True），不再 `startswith("3.18.9")`。

`sand_report.evaluate_compat`：

- `anchorVersion` 改为当前轨的展示名，例如 `3.18.9 / 3.18.25` 或 `3.19.13`。
- `upgrade.relation`：`match`（已测构建）、`same-track`（同族未测，如 3.18.30）、`newer-track`（3.19 相对用户仍停在 3.18 的预期）、`older`、`unknown`。
- leftover 规则按轨换针：3.19 的 `gate-off` 早退、`promptModelInfo` 等加入 `RELATED_NEEDLES`，避免 3.19 原文被标成「版本没有」而不是「可打未打」。

设置页：hint 从「锚点 3.18.9」改为「补丁轨 3.18（已测 3.18.9 / 3.18.25）」或「补丁轨 3.19（已测 3.19.13）」。

---

## 3.18 轨：本轮优化（仍停在 3.18.9 / 3.18.25）

不换 Direct 核，不降 Task/Action。只补 v131 没做完的和 CAM 2.3.20 里**对 3.18 也有用**的点。

| # | 优化 | 落到哪 |
|---|------|--------|
| 1 | **Grok 4.6 / 4.5 产品 prompt 互斥** | `_joe_stream_session_js()`：`grok46 = grok && (4.6\|grok46)`；`isGrok45ProductPrompt: grok && !grok46`；`isGrok46ProductPrompt: grok46`。保留 `agentTokenLimit` 与 `supportsSelfSummary:!1`。旧 Direct 字面量 apply 时剥掉重写。 |
| 2 | **agent-host 分包** | `TARGET_SPECS` 增加 `extensions/cursor-agent-host/dist/657.js`、`61.js`、`675.js`（无 extension 哈希项则 `ext=None`，只扫内容）。CAM 2.3.20 还有 `4884.js`，3.18 未证实有锚点：**本轮加入扫描，没有 leftover 就不写**，不绑 `streamReady`。 |
| 3 | **扫描 hint** | `_SAND_PATCH_HINTS` 去掉对 `function hre(` 的依赖，改为 Direct 锚点公共形态（`return t=>{return n=this,o=void 0,s=function*()`）以及 3.19 特征（`class J{constructor`、`promptModelInfo`），避免 3.18.25 改名后整文件被跳过。 |
| 4 | **版本文案** | 3.18.25 不再提示「新于锚点」。`same-track` 才说「同族未测构建，缺项看明细」。 |
| 5 | **路由文案（可选层）** | 3.18 workbench **如果**已有 `["Routed to "`，才改成 `["本次使用 "` + `/*ROUTE_LABEL_V1*/`。3.18.9 没有该字符串则跳过。3.19 官方已有 Routed to + 点赞行：注入时**不要**再往气泡塞 `> grok-bot route to`（CAM 2.3.20 的坑）。启动器从未打过气泡 hint，只需保证本轮也不加。 |

3.18 Direct 仍禁止：`runInference` 守卫、`supportsSelfSummary:!0`、`promptModelInfo` 包装。

---

## 3.19 轨：要对齐的形态（对照 CAM 2.3.20，不抄整包）

只描述**层与原文差**，实现时对着本机 3.19.13 文件核对压缩名，CAM 字面量当参考不是唯一真值。

| 层 | 3.18（启动器已有） | 3.19（CAM 2.3.20 观察到的差） | 启动器怎么跟 |
|----|-------------------|------------------------------|--------------|
| L1 managed-local | 改 `checkFeatureGate ? eligible : gate-off` 三元 | `gate-off` 会先 `return connect`，只改 eligible 不够；在锚点前插 early-return，原文留下便于卸载 | 新增 3.19 早退写法；restore 两种都卸 |
| L1 runtime load | `checkFeatureGate(Ds)` | 闸门标识改成 `Ms` | 正则已捕获闸门名则复用；否则加 `Ms` 字面量兜底 |
| L1 move_exec | `checkFeatureGate(Us)` | `Js` | 同上 |
| L2 Direct | `new Joe` + `resolvedModelMetadata:nre(a,o)` | `new J` + `Ycw`；metadata 必须 `{promptModelInfo:oe(meta,mid), useDsv3Harness:!1}` | 按文件嗅探选注入体；4.6/4.5 互斥；**尽量保留** `agentTokenLimit`（CAM 3.19 注入没有这项，启动器若 3.19 会话对象仍读 `parameters` 就带上，单测锁 3.18 必须有、3.19 有则更好） |
| L6 Action | V2，无 `mode-not-supported` | 原文变成 `function(e){return e.requestedMode===o.xy.AGENT\|\|...}`；CAM 补丁仍卡模式 | 写启动器自己的 3.19-V2：放行 summarize/resume，**不**恢复 mode 拒绝；对不上就 missing |
| L6 subagent route/session | 3.18 `hasUnsupportedRunOptions` 长串 | 3.19 改成 `isHostedSubagentChild` / `useClientSideSubagent:!0` | 3.19 专用 ORIGINAL/PATCHED，marker 沿用现有 |
| L6 Task | V3（父模型 ID + 子代理禁止再派发） | CAM 是 `Object.assign(Ne({parentModelId...}),{isModelBlocked:()=>!1})` 仍偏 V2 | 优先把 V3 字段编进 3.19 `taskToolProps`；编不进去就 missing，**不要**为了绿条装 CAM V2 |
| 路由 UI | 无 | `Routed to` → `本次使用`；Status 用真实 message | 仅当原文存在时打；restore 还原 |
| 扫描文件 | 无 4884 | CAM 清单含 `4884.js` | 加入 TARGET_SPECS，有锚点才写 |

HDRFIX_V2、L4 RPC、L7、L8：3.19 上**先用现有正则试**。命中则打（3.18 优化不丢）；不命中进 missing，本轮不为它们新发明 3.19 专用核。若真机 3.19 上 HDRFIX 原文变了，另开一轮，不堵这次分流。

---

## 步骤

### 1. 版本族契约 + 单测（先红后绿）
**依赖**：无  
**改**：`launcher/sand_stream.py` 增加 `SUPPORTED` / `resolve_patch_track`；`tests/test_sand_stream.py` 先写失败用例。  
- `3.18.9`、`3.18.25` → track `3.18`，`tested=True`，`versionOk=True`。  
- `3.19.13` → `3.19`，`tested=True`。  
- `3.18.30` → `3.18`，`tested=False`，hint 含「同族未测」。  
- `3.12.30` → `other`。  
- 空版本 + 含 `class J{constructor` 的 content → `3.19`，`source=content`。  
- 空版本 + 仅 `new Joe(` → `3.18`。  
**验收**：新测试先失败（函数不存在），实现后上述断言全绿；现有 `test_version_hint_against_anchor` 改为测新语义（3.18.25 为 ok）。

### 2. 3.18 Direct：4.6/4.5 互斥 + 旧字面量迁移
**依赖**：步骤 1（可并行写测试，合入同一 `apply_patch_to_content`）  
**改**：`_joe_stream_session_js` / `_strip_direct_stream_injection`。  
- 新注入含 `isGrok46ProductPrompt` 且 4.5 与 4.6 互斥。  
- 已装旧 Joe 注入（无 grok46 字段）一次 apply 剥掉重写。  
- 单测继续禁止 `supportsSelfSummary:!0`；3.18 仍含 `agentTokenLimit`。  
**验收**：  
- 现有 `_core_bundle` 全套 3.18 测试仍绿。  
- 新用例：apply 后出现 `isGrok46ProductPrompt`；`isGrok45ProductPrompt` 字符串与 `&&!grok46` 绑定。  
- 旧 `_legacy_direct_stream_injection` 再 apply 后只有一份新注入。

### 3. 3.18 扫描面：分包 + hint
**依赖**：无（可与 1–2 并行）  
**改**：`TARGET_SPECS`、`_SAND_PATCH_HINTS`；`sand_report` leftover 仍按 marker，不因多分包把 `streamReady` 绑死在 657/61/675。  
**验收**：  
- 合成「只在 `657.js` 里有 Direct 锚点」的 layout 单测（可用 tmp 目录假文件）apply 后该文件出现 Direct marker。  
- 无 `function hre(` 但有 Direct 公共形态的 bytes，`_bytes_may_need_sand_patch` 为 True。  
- 空的 `4884.js` 不让 `fullReady` 变 False。

### 4. 报告 / UI：多锚点文案
**依赖**：步骤 1  
**改**：`sand_report.py` 的 `_upgrade_advice` / `versionHint`；`web/app.js` 的 Grok Bot hint。  
- 3.18.9 / 3.18.25：`relation=match`，hint 空或只写轨名。  
- 3.19.13：`match` 到 3.19 轨，**不再**说「新于 3.18.9，压缩名可能已变」这种劝退。  
- 3.12：仍 `older` + 不要硬打 L1–L7。  
**验收**：`tests/test_sand_report.py` 更新；设置页文案无「锚点 3.18.9」作为唯一真值。

### 5. 3.19：L1 + L2 双形态（核心）
**依赖**：1–2  
**改**：`apply_patch_to_content` / `remove_patch_from_content`。  
- managed-local / runtime / move_exec / Direct：3.18 逻辑保留；增加 3.19 ORIGINAL/PATCHED 或正则。  
- Direct 用嗅探选注入体；3.19 metadata 为 `promptModelInfo` 包装。  
- restore 清 3.18 三元补丁、3.19 早退补丁、两种 Direct 字面量。  
**验收**（全合成字符串，不碰真机）：  
- 3.18 `_core_bundle` 行为不变。  
- 3.19 合成：含 `gate-off` 早退锚点时打上 managed-local marker，且原文 `return connect` 片段仍在（可卸载）。  
- 3.19 Direct 锚点 + `class J` / `Ycw`：注入含 `promptModelInfo`、`useDsv3Harness:!1`、`isGrok46ProductPrompt`；**不含** `resolvedModelMetadata:nre(`。  
- 同一文件先打 3.18 Direct 再当 3.19 内容 apply：只剩 3.19 注入。  
- restore 后无 SAND_DIRECT / SAND_MANAGED_LOCAL 标记。

### 6. 3.19：L6 变体 + 路由标签
**依赖**：步骤 5  
**改**：`_apply_l6` / `_strip_l6`；可选 `ROUTE_LABEL`。  
- 3.19 subagent route/session/task/action：独立 ORIGINAL/PATCHED。  
- Action 3.19-V2：白名单含 summarize/resume；断言补丁块内无 `mode-not-supported`（与 3.18 同一产品约束）。  
- Task：能编 V3 就编；单测若只能命中 CAM 式 `isModelBlocked`、编不进父模型 ID，则该层 missing，不把 `fullReady` 在 3.19 上伪装成 True。  
- `["Routed to "` → `["本次使用 "`；restore 还原。  
**验收**：  
- 3.18 `_l6_bundle` 测试仍绿（V3/V2、无 mode-not-supported）。  
- 3.19 合成 Action 原文 apply 后有 marker、有 summarize/resume、无 mode-not-supported。  
- `stream` profile 仍不打 L6 / route label 不绑 `streamReady`。

### 7. apply/status 接线 + 已知 marker
**依赖**：1–6  
**改**：`apply()` 读 `layout.version` 得默认轨，传入每个文件；status 返回 `patchTrack` 等。CAM / 本模块新旧 Direct 字面量都算已知，不当 `external_marker` 拒写。  
**验收**：  
- `sand_stream_status` 合成 mock layout（可测函数 `_status_payload`）含 `patchTrack`。  
- 已含 3.19 Direct marker 的内容 `external_marker_count==0`。

### 8. 文档收尾（仍不发版）
**依赖**：测试绿  
**改**：本计划勾选；`dev-references.local.md` 加一行「Grok Bot 按轨：3.18 / 3.19，对照 CAM 2.3.20」。不写 Release。  
**验收**：`python -m pytest tests/test_sand_stream.py tests/test_sand_report.py -q` 全绿。真机 3.18.9 / 3.18.25 完整档仍 `fullReady` 或可读 missing；有 3.19.13 再点一次启用，抓包确认走 `InferenceService/Stream` 后再谈 bump。

---

## 风险

| 风险 | 缓解 |
|------|------|
| 3.19 压缩名与 CAM 2.3.20 字面量不完全一致 | 步骤 5 以本机/用户 3.19.13 文件核对；CAM 只当参考。对不上进 missing，不整文件乱替换 |
| 3.19 带上 `agentTokenLimit` 导致 metadata 再一次 `metadata-unavailable` | 3.19 注入先做**最小** metadata（CAM 已验证的 `promptModelInfo` 包装）；`agentTokenLimit` 只放在 meta 对象里 CAM 已有的字段旁，真机失败就从 3.19 注入拿掉，**3.18 注入必须保留** |
| 两套 managed-local restore 互相咬 | 先卸 3.19 早退（前缀 `return{...marker}`），再卸 3.18 `try{return{...marker};`；单测 roundtrip 3.18 与 3.19 各一份 |
| 3.18.25 加 657/61/675 误改无关 chunk | 无 leftover 不写；只对已有 SAND 扫描 hint 的文件跑 apply |
| 用户从 3.18 升到 3.19 后旧补丁残留 | apply 先剥所有已知 Direct/L1 形态再按新轨写；status 若 `track=3.19` 且仍只有 `nre(` 注入，标 partial 并提示重新启用 |
| leftover 规则仍用 3.18 针，3.19 被标「版本没有」 | 步骤 4–5 同步加 3.19 needles |
| 方案膨胀把账号 OAuth 塞进来 | 非目标；CAM 隔离浏览器本轮不搬 |

---

## 非目标（本轮不做）

- 不搬 CAM VSIX / 侧栏 / 隔离浏览器 OAuth / 自动续期（账号体系另开计划）  
- 不改成生命周期缺条拒写  
- 不把 3.18 Task/Action 降回 V2/V1  
- 不代写模型墙、不把会员伪装塞进 sand_stream  
- 不新写气泡 `> grok-bot route to`  
- 不为 3.19 重做 L7/L8/HDRFIX 专用核（试打现有正则即可）  
- 不在本轮 bump 启动器版本号、不改切号/额度/踢设备

---

## 建议 commit 拆分

1. `feat(sand): resolve Cursor patch track 3.18/3.19`  
2. `feat(sand): 3.18 grok 4.6/4.5 prompt split + host chunks`  
3. `fix(ui): version hint matches 3.18.25 and 3.19 track`  
4. `feat(sand): 3.19 L1/L2 dual-shape inject and restore`  
5. `feat(sand): 3.19 L6 variants + route label`  
6. `test: sand version-track fixtures`  
7. `docs: plan-sand-version-tracks`

---

## 待确认（已按默认开工）

1. **3.19 L6 范围**：V3/V2 语义能编就编，否则 `missing`，不装 CAM Action V1。  
2. **`4884.js`**：加入扫描、无锚点不写、不绑就绪。  
3. **路由文案**：原文有 `["Routed to "` 才改成「本次使用」；3.18 / 3.19 同样。  
4. **未测的 3.18.x / 3.19.x**：同族试打 + `same-track` 提示，不拒写。

---

## 已确认（来自前序对话，可推翻）

1. 要**检测版本 + 动态补丁方法**，不要继续单锚点 3.18.9。  
2. **继续支持 3.18.9 / 3.18.25**，并为 3.18 做优化，不是只追 3.19。  
3. 本会话只出方案，**说「开工」后再改代码**（已开工并按步骤提交）。

## 本会话进度

- [x] 对照 CAM 2.3.20 与启动器 v131 差距，写成可审核计划  
- [x] 用户批注待确认 1–4（按建议默认）  
- [x] 步骤 1：`resolve_patch_track`  
- [x] 步骤 2：3.18 Grok 4.6/4.5 互斥  
- [x] 步骤 3：agent-host 分包 + 扫描 hint  
- [x] 步骤 4：报告 / 设置页多锚点文案  
- [x] 步骤 5：3.19 L1/L2 双形态  
- [x] 步骤 6：3.19 L6 + 路由标签  
- [x] 步骤 7：apply/status 接线 `patchTrack`  
- [x] 步骤 8：文档收尾（不发版）
