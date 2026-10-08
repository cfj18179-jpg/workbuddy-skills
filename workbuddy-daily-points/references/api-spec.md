# 接口与登录态规范（WorkBuddy每日积分）

本文件供 Skill 执行时参考，包含登录态文件格式、签到接口、旅行接口、字段含义与错误码。
所有接口均通过本机已登录 WorkBuddy 客户端的 `accessToken` 鉴权，**只读**登录态，绝不修改。

---

## 1. 登录态文件

由 WorkBuddy PC 客户端登录后生成。**注意：新版本客户端已把敏感字段改为加密存储**（见下方"字段加密"节），不再是全明文 JSON。

### 路径（按操作系统自动探测）

| 系统 | 路径 |
|------|------|
| Windows | `%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`（旧版可能在 `%APPDATA%` 同路径下） |
| macOS | `~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info` |
| Linux | `~/.config/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info` |
| 兜底 | `~/.workbuddy/auth/workbuddy-desktop.info` |

### 关键字段

```json
{
  "auth": {
    "accessToken": "<JWT>",
    "tokenType": "Bearer",
    "domain": "www.codebuddy.cn",
    "expiresAt": 1735689600000
  }
}
```

- `auth.accessToken`：鉴权令牌（JWT）。**任何输出都不得打印真实值**，脚本仅脱敏为 `eyJhbG...xxxx`。
- `auth.domain`：**签到接口域名以此为准**。实测值为 `www.workbuddy.cn`，切勿硬编码其他域名（会 404）。
- `auth.expiresAt`：过期时间（epoch 毫秒/秒）。脚本兼容 13 位毫秒与 10 位秒；为空则跳过过期检查。

### 字段加密（2026-09-26 起）

新版客户端把 `accessToken` / `refreshToken` / `nickname` / `phoneNumber` 等字段替换为信封对象：

```json
{ "$wbEncrypted": 1, "envelope": "<canonical base64>" }
```

信封内层（base64 解码后）为 `{"suite":"1","keyId":"<16位hex>","nonce":"...","authTag":"...","ciphertext":"..."}`，即 AES-GCM。
密钥由客户端通过 `AtRestCrypto` 管理（另有 `scheme: "asym-v1"` 的非对称变体），**不对本机第三方脚本开放**。
因此脚本读到 `accessToken` 为对象时**不得**尝试爆破密钥或嗅探 IPC，只能改走下方的明文替代来源；
三类来源都不可用时如实报错（`status=error` + `NO_PLAINTEXT_HINT`）。

### 明文替代来源（v1.4.0 优先级顺序）

1. **主文件明文**（来源标记 `main`）——未升级的旧客户端，直接可用。
2. **IDE 扩展写入的凭据**：同目录下的 `Tencent-Cloud.coding-copilot.info`（`*coding-copilot*.info` 通配），
   由 WorkBuddy 的 IDE 扩展（VS Code / Cursor 插件）写入，`auth.accessToken` 为**明文 JWT**，
   `auth.domain` 通常为 `www.codebuddy.cn`。该文件随 IDE 登录自动续期（`expiresIn` 60 天、`refreshExpiresIn` 90 天），
   时效性优于历史快照，**是 macOS / Linux 上最可靠的路径**。实测同一账号的该凭据可直接调用
   `www.workbuddy.cn` 与 `www.codebuddy.cn` 的签到接口（均返回 `code:0`）。
   来源标记 `ide-credential:<文件名>`。
3. **历史快照**（来源标记 `snapshot:<文件名>`）——`workbuddy-desktop.<ISO时间戳>.<pid>.<uuid>.info`，
   旧版桌面客户端遗留的明文备份，会随时间失效，属过渡方案。

> **账号校验（强制）**：复用 2 / 3 之前，必须比对 `account.uid` 或 `account.uin` 与主文件是否有交集，
> 不一致则一律跳过。多账号机器上快照/扩展凭据可能属于**另一个账号**，混用会导致领错账号。
> **跨域说明**：`domain` 取自主文件 `auth.domain`；实测 `www.workbuddy.cn` 与 `www.codebuddy.cn` 双向通用，
> 但**旅行接口固定 `www.workbuddy.cn` 且路径无 `/v2` 前缀**。

---

## 2. 签到接口

基础地址：`https://<auth.domain>/v2`

### 2.1 状态查询（只读）

```
POST /v2/billing/meter/checkin-activity-status
Authorization: Bearer <accessToken>
Content-Type: application/json
```

响应（示例）：

```json
{
  "code": 0,
  "data": {
    "today_checked_in": false,
    "streak_days": 12,
    "daily_credit": 100,
    "total_credit": 1340
  }
}
```

### 2.2 领取签到

```
POST /v2/billing/meter/daily-checkin
Authorization: Bearer <accessToken>
Content-Type: application/json
```

成功响应：

```json
{ "code": 0, "credit": 100, "streak_days": 13, "data": { "credit": 100, "daily_credit": 100 } }
```

已签到响应（幂等，非错误）：

```json
{ "code": 10001, "msg": "今天已签到，请明天再来" }
```

---

## 3. 派猫猫旅行接口

基础地址：`https://www.workbuddy.cn`

> **与签到不是同一个域名，且路径不带 `/v2` 前缀**——这是最容易踩的坑。
> 用 `auth.domain`（`www.codebuddy.cn`）或误加 `/v2` 都会 404。
> 旅行接口仅需 Bearer Token，无需设备指纹。

### 3.1 旅行状态（只读）

```
GET /activity/growth/buddy/travel/status
Authorization: Bearer <accessToken>
```

响应示例：

```json
{
  "code": 0,
  "data": {
    "state": "idle",
    "location": { "id": 1, "name": "咖啡馆" },
    "reward_credit": 0,
    "arrive_at": 1757500000,
    "server_now": 1757490000,
    "daily_limit_reached": false,
    "record_id": 123
  }
}
```

状态三态：

| `state` | 含义 | 可执行动作 |
|---|---|---|
| `idle` | 空闲 | 未达每日上限时可 `depart` |
| `traveling` | 旅行中 | 无；用 `arrive_at - server_now` 算到达倒计时 |
| `arrived` | 已到达，待领取 | 可 `claim` 领取积分 |

### 3.2 领取旅行积分（写）

```
POST /activity/growth/buddy/travel/claim
Content-Type: application/json

{}
```

成功：`{"code":0,"data":{"reward_credit":8}}`。

### 3.3 派出 Buddy（写）

```
POST /activity/growth/buddy/travel/depart
Content-Type: application/json

{"location_id": 1}
```

成功：`{"code":0,"data":{"location":{"id":1,"name":"咖啡馆"},"arrive_at":1757500000}}`。

### 3.4 可选地点

`GET /activity/growth/buddy/travel/config` 返回 `data.locations`。
实测四个地点为咖啡馆 / 商场店铺 / 健身房 / 古镇客栈，时长与积分区间完全相同（随机 1-4 小时、5-10 积分），**收益无差异**，`location_id` 缺省时随机选一个。

### 3.5 派遣前置检查（硬规则）

调用 `depart` 前必须先读 `status` 并同时满足：

1. `state == "idle"`
2. `daily_limit_reached` 为假

任一不满足即跳过派遣，**不发任何写请求**。

---

## 4. 错误码 / 状态码对照

| HTTP | code | 含义 | 脚本处理 |
|------|------|------|----------|
| 200 | 0 | 领取成功 | `action=claimed`，展示积分/连续天数 |
| 400 | 10001 | 当天已签 | `action=skip_already_signed`（幂等跳过，非失败） |
| 非 2xx | — | 网络/服务端错误 | 读取响应体；若含"已签到"仍判为已签，否则 `status=error` |
| — | — | `accessToken` 缺失/过期 | `status=error`，提示重新登录客户端 |
| — | — | `accessToken` 为 `$wbEncrypted` 加密信封 | 转用明文替代来源（`main` → `ide-credential:` → `snapshot:`）；全部不可用时 `status=error` + `NO_PLAINTEXT_HINT`，不崩溃 |

> **旅行接口的降级约定**：只读接口（`status`）失败时置 `travel.available=false` 并静默跳过，绝不改变签到结论；写接口（`claim` / `depart`）返回非 0 码时，把服务端 `msg` 如实记入 `travel.auto_log`，同样不影响签到状态与退出码。

---

## 5. 积分余额字段候选名

不同版本接口返回的余额字段名不统一，脚本按以下候选名 + 嵌套层级兜底提取，写入结果 `balance` 字段（找不到则返回 null，不影响签到）：

- 候选键：`total_credit` / `total_credit_balance` / `total_points` / `points_balance` / `credit_balance` / `balance` / `remain_credit` / `score` / `integral` / `totalCredit` / `pointsBalance`
- 候选层级：顶层 / `data` / `data.result`
