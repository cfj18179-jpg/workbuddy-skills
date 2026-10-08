---
name: workbuddy-daily-points
display_name: WorkBuddy每日积分
display_name_en: WorkBuddy Daily Points
description: 每日自动领取 WorkBuddy「Buddy 加油站」积分的技能（接口直签，无需点击 GUI，跨平台 Windows / macOS / Linux）。当用户说"领取 WorkBuddy 积分 / 每日签到 / 自动签到 / 签个到 / 打卡 / 查积分 / 查签到状态 / 派猫猫旅行 / 派 Buddy 出门 / 旅行积分 / 猫猫回来了吗 / 检查签到环境 / 设置每天自动领积分"时使用。原理是读取本机已登录 WorkBuddy 的 accessToken，直接调用官方签到接口完成领取，并支持派猫猫旅行全自动闭环（先领后派）。
description_zh: 读取本机 WorkBuddy 登录态，直接调用官方接口完成「Buddy 加油站」每日签到领取积分（无需点击 GUI），并支持派猫猫旅行（查状态 / 领旅行积分 / 派 Buddy 出门，默认随签到执行全自动闭环）。可配合 WorkBuddy 自动化设置每日定时领取。凭据优先取主登录态明文；若主文件已被客户端加密，则自动复用同账号下由 IDE 扩展写入的明文凭据（需该机器曾用 WorkBuddy IDE 扩展登录过同一账号），否则请在客户端手动签到。
description_en: Claims daily WorkBuddy Buddy Station credits via the official API using the local auth token (no GUI clicks), cross-platform. Also supports Buddy Travel (query status, claim travel credits, dispatch Buddy) in a fully automatic claim-then-dispatch loop. Works with WorkBuddy automations for scheduled daily claims. Credentials come from the local plaintext auth file when available; if that file is encrypted by the client, the skill reuses the same-account plaintext credential written by the WorkBuddy IDE extension (requires that machine to have signed in to the same account via the IDE extension). Otherwise manual sign-in in the client is required.
category: 效率工具
version: 1.4.0
author: ruish
agent_created: true
---

# WorkBuddy每日积分（接口直签 · 签到 + 派猫猫旅行）

WorkBuddy「Buddy 加油站」每日签到本质是一次带本地登录 Token 的 HTTP 接口请求，**不需要**模拟点击「个人信息 → Buddy 加油站 → 签到」的 GUI 流程。

本 Skill 自带脚本 `scripts/daily_points.py`，仅用 Python 标准库（urllib/json/os），零第三方依赖，跨平台。

> 接口规范、登录态格式、字段与错误码见 `@references/api-spec.md`。
> 本文件只保留 Skill 元数据与执行所需关键信息。

## 关键事实（实测验证，WorkBuddy v5.3.x）

- **登录态文件**：
  - Windows: `%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`（旧版可能在 `%APPDATA%`）
  - macOS: `~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`
  - Linux: `~/.config/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`
  - 兜底: `~/.workbuddy/auth/workbuddy-desktop.info`
- ⚠️ **格式已变更（2026-09-26 实测）**：新版本客户端把敏感字段改为**客户端加密存储**，`accessToken` 不再是明文字符串，而是
  `{"$wbEncrypted": 1, "envelope": "<base64>"}`（envelope 内层为 `{suite,keyId,nonce,authTag,ciphertext}`，AES-GCM）。
  解密所需的密钥由客户端自身持有（`AtRestCrypto` 由 `key` 参数注入，keyId 形如 16 位 hex），
  **脚本无法也不应尝试解密**。
- **凭据来源优先级（v1.4.0 起）**：
  1. 主文件明文 `accessToken`（来源 `main`）；
  2. **IDE 扩展写入的明文凭据** `Tencent-Cloud.coding-copilot.info`（同目录，明文 JWT，随 IDE 登录自动刷新）；
  3. 同目录明文历史快照 `workbuddy-desktop.<时间戳>.<pid>.<uuid>.info`（旧版桌面客户端遗留）。
  - ②③ 都**必须先通过账号一致性校验**（`account.uid` 或 `account.uin` 与主文件任一相同）才启用，
    账号不一致一律跳过，**绝不跨账号混用**；输出里标注 `token_source: ide-credential:<文件名>` /
    `snapshot:<文件名>` 与对应 `token_note`。
  - `--diagnose` 可查看候选：`ide_credentials`（`token_field` / `account_match` / `expired` / `usable`）
    与 `plaintext_snapshots`（`uin_match` / `expired` / `usable`）。
  - ② 是**跨平台可靠路径**（Windows / macOS / Linux 表现一致），③ 只在跑过旧版客户端的机器上存在。
- 三类来源全部不可用时返回 `NO_PLAINTEXT_HINT`（含可操作做法），以 `status=error` 正常退出
  （v1.0.1 起不抛 TypeError 崩溃；v1.4.0 起提示语已含 IDE 扩展方案）。
- 文件内 `auth.domain`（**接口域名以此为准**，实测 `www.workbuddy.cn`；切勿硬编码其他域名）。
- **签到状态查询（只读）**：`POST https://<domain>/v2/billing/meter/checkin-activity-status`
- **领取签到**：`POST https://<domain>/v2/billing/meter/daily-checkin`
  - 成功：`code:0`，领 100 积分；已签：`code:10001`（幂等，不会重复发，非错误）。
- **派猫猫旅行（域名不同！无 `/v2` 前缀！）**：`https://www.workbuddy.cn`
  - 状态：`GET /activity/growth/buddy/travel/status`（`state`: idle / traveling / arrived）
  - 领取：`POST /activity/growth/buddy/travel/claim`（仅 arrived 时）
  - 派遣：`POST /activity/growth/buddy/travel/depart`（body `{"location_id": 1-4}`，仅 idle 且未达每日上限时）
  - 四个地点收益完全相同（随机 1-4 小时、5-10 积分），缺省随机即可。

## macOS / Linux 兼容性（脚本 v1.4.0 实测校对）

脚本为**纯标准库 + 跨平台路径逻辑**，在 macOS 上可直接运行，需注意四点：

| 关注点 | 结论 | 说明 |
|---|---|---|
| Python 解释器 | ✅ | 用 WorkBuddy 托管 Python（`~/.workbuddy/binaries/python/.../bin/python3`）。**不要**用 macOS 自带 `/usr/bin/python3`（可能未装、且缺 CA 证书） |
| 登录态路径 | ✅ | 首选 `~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`；若客户端 userData 目录名不是 `CodeBuddyExtension`（Electron 取 app name 所致），脚本会在 `~/Library/Application Support/*/Data/Public/auth/` 下**自动通配补扫**（最多 5 条） |
| SSL 证书 | ⚠️ | macOS 上最易踩 `CERTIFICATE_VERIFY_FAILED`。脚本优先用 `certifi` 的 CA 包（装了就用），否则回落到系统默认；托管 Python 一般自带来路正确的 CA |
| 权限 | ✅ | `~/Library/Application Support` 与 `~/.workbuddy` 均不受 macOS TCC 保护，**不会**弹「访问文稿/桌面」授权框 |
| 跨平台调用 | ✅ | 路径一律 `os.path.join` 拼接，`sys.platform` 分支决定扫描根；无 Windows 专有 API、无硬编码盘符 |

> 结论：**代码层面 macOS 可正常运行**；**能否真正领到积分取决于该机器有没有明文凭据**，
> 与操作系统本身无关，见下节。

## ⛔ 凭据限制：能否自动领取，取决于「本机有没有明文凭据」

**根因（已确认，非 bug）**：新版客户端把 `accessToken` 以 AES-GCM 信封加密存储，而解密用的
**32 字节静态密钥（at-rest key）不落盘**——它只在客户端运行时通过**本地 IPC** 下发给它自己的子进程
（源码里的 `[CredentialBootstrap]` 流程，socket 权限 0600）。因此**任何第三方脚本按设计都无法解密主文件**。
这是客户端的凭据保护机制，**不是登录过期，也不是网络问题**，且**与操作系统无关**。

但同一账号下通常还有**明文**凭据可以合法复用，v1.4.0 会自动查找（见上「凭据来源优先级」）：

| 机器情形 | 结果 |
|---|---|
| 主文件仍是明文（未升级的旧客户端） | ✅ 直接可用（`main`） |
| 主文件已加密，但该机器**用 WorkBuddy IDE 扩展登录过同一账号** | ✅ 自动复用扩展明文凭据（`ide-credential:…`）——**macOS / Linux 的推荐路径** |
| 主文件已加密，且该机器**跑过旧版桌面客户端**（留有明文快照） | ✅ 复用历史快照（`snapshot:…`，过渡方案） |
| **全新安装**、且从未用 IDE 扩展登录（新电脑典型） | ❌ 无任何明文凭据可用 |

> 判定方法：在该机器运行 `--diagnose`，看 `token_source` 是否为 `main`，
> 以及 `ide_credentials` / `plaintext_snapshots` 里有没有 `usable: true` 的条目。

**可行的替代做法**：① 在该机器用 WorkBuddy 的 **IDE 扩展（VS Code / Cursor 插件）登录同一账号**，
之后本技能即可自动领取（一次登录长期有效，扩展会自行续期）；
② 在客户端「Buddy 加油站」手动签到（每天 100 积分，最省事）；
③ 把每日自动化留在仍有明文凭据的设备上跑；④ 旅行积分同样可在客户端界面领取。

> ⚠️ 本技能**只读取客户端自己以明文写入的文件**：不解密信封、不提取密钥、不嗅探 IPC、不改写任何文件。
> 读取到的凭据仅用于调用官方签到 / 旅行接口，不会发往其他地址；输出中一律脱敏，不回显完整 token。

## 脚本参数

- （无参数）签到 + 派猫猫旅行全自动闭环（**默认**，先领后派）
- `--no-travel` 只签到，跳过旅行
- `--check-only` 仅查询状态（只读，不领取、不派遣）
- `--travel-only` 只跑旅行闭环（不签到）
- `--location N` 指定派遣地点 1-4（缺省随机）
- `--diagnose` 环境自检（Python / 平台 / 登录态 / token / 明文快照候选 / 接口连通，只读）
- `--version` / `--help`

脚本输出单行 JSON（含 `status` / `action` / `summary` / `balance` / `travel` / `token_source` 字段），退出码成功 0 / 失败 1，**全程不打印真实 token**（仅脱敏 `eyJhbG...xxxx`）。

## 执行流程（照做即可）

1. **定位登录态并校验**：用 `--diagnose` 自检；若文件不存在或 token 过期，如实告知用户"请先在 WorkBuddy 客户端登录"，**不要**伪造或猜测。
2. **执行领取**：直接用托管 Python 运行脚本（无参数跑完整闭环；用户只要积分数字时用 `--no-travel`）。把 JSON 里的 `summary` 转述给用户，不要回显任何凭据。
3. **创建定时自动化**（用户要求"每天自动领"时）：用 `automation_update`（mode=create）创建 recurring 自动化：
   - name：`WorkBuddy每日积分 · 自动签到`
   - rrule：`FREQ=DAILY;BYHOUR=9;BYMINUTE=0`
   - status：`ACTIVE`
   - 提示词：`运行命令 "<python路径>" "<技能目录>/scripts/daily_points.py"，把输出 JSON 的 summary 字段简要汇报给我；若 status 为 error 则说明原因。不要在汇报中包含任何 token。`（运行时把 `<python路径>` 替换为本机托管 Python 绝对路径）
4. **验证**：首次运行后提醒用户到「Buddy 加油站」界面核对积分 +100；当天已手动签到会自动跳过。

## 安全约束（务必遵守）

- **只读**凭据文件（主登录态、IDE 扩展凭据、历史快照），绝不修改、删除或外传 `accessToken` / `refreshToken`。
- **不做**任何绕过凭据保护的尝试：不解密 `$wbEncrypted` 信封、不提取 at-rest key、不嗅探 IPC / 不抓包。
- 任何输出（终端、日志、汇报）都不得包含真实 token。
- **跨账号校验必须生效**：复用 ②③ 来源前必须核对 `account.uid` / `account.uin`，不一致一律跳过。
- 不要在网页版尝试签到（网页版无签到入口，仅 PC 客户端专属）。
- 派遣前必须确认 `state==idle` 且 `daily_limit_reached` 为假，否则不发写请求。

## 排错要点

- `code=10001` 是"今日已签"，非错误，正常跳过。
- **`status=error` + "accessToken 已加密，且本机没有可用的替代明文凭据"**（`NO_PLAINTEXT_HINT`）：
  说明该机器既无 IDE 扩展凭据、也无明文快照。at-rest key 无盘上副本、按设计不可解密。
  → 告知用户首选做法是**在该机器用 WorkBuddy IDE 扩展登录同一账号**（登录一次即可长期自动领取），
  或直接在客户端「Buddy 加油站」手动签到；**不要**反复重试或尝试绕过凭据保护。
- **`token_source: ide-credential:Tencent-Cloud.coding-copilot.info`**：主登录态已加密，本次复用 IDE 扩展的
  明文凭据。属正常可用状态，不影响领取；`token_note` 与 `summary` 会如实标注来源。
- **`token_source: snapshot:...`**：走历史快照明文回退，属过渡态（旧版客户端遗留，会随时间失效）；
  客户端重新登录后恢复明文则自动优先主文件。
- **`token_source: main`**：正常明文主登录态，无需说明来源。
- **`status=error` + "accessToken 已改为客户端加密存储"**：v1.2.0 之前的老提示语，
  本质同上是凭据格式问题，不是登录过期，也不是网络问题。
- **macOS 报 `CERTIFICATE_VERIFY_FAILED`**：改用托管 Python 运行，或 `pip install certifi` 后重试（脚本会用其 CA 包）。
- 签到 404 = 用错域名（脚本自动读本机 `auth.domain`；实测 `www.workbuddy.cn` 与 `www.codebuddy.cn` 均可）。
- **旅行接口 404 先查两件事**：域名必须是 `www.workbuddy.cn`，且路径**不能带 `/v2`**。
- "今日派遣次数已用完"是服务端每日限额，次日恢复，不是故障。
- 旅行中无法提前召回（官方无召回接口），到达后下次运行自动补领。
- 自动化没跑先查：电脑是否开机、客户端是否退出、网络是否可用。
