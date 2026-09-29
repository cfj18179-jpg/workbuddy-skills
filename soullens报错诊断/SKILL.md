---
name: soullens报错诊断
display_name: SoulLens 报错诊断（灵境桌面端）
description_zh: "诊断灵境 SoulLens（Windows 桌面 AI 创作工具）生成图片/视频失败的原因：定位 appdata 与 E:\\SoulLens 下的任务记录、主进程日志、渲染进程诊断日志，读取真实错误码（如 EXECUTION_ROUTE_CONNECTION_UNAVAILABLE / submission_unconfirmed / 401 Invalid token / Cloudflare 524），核对本地 Provider 与 API Key 配置，输出可执行的修复步骤。触发词：SoulLens 报错、soullens 生成失败、灵境报错、视频生成报错原因、生成图片失败、查询报错原因。"
description_en: "Diagnose generation failures in SoulLens (Lingjing) Windows desktop app: locate task records / main log / renderer diagnostics, read real error codes, audit local provider & API-key config, and produce actionable fixes."
agent_created: true
---

# SoulLens 报错诊断（灵境桌面端）

灵境 SoulLens 是 Windows Electron 桌面端 AI 创作工具（内部名 `soullens-backend`），本地跑一个 Python aiohttp 后端 + 本地 PostgreSQL。
它的报错信息**几乎从不显示在界面上**，界面只会给一句含糊提示，真实错误全在日志里。本技能就是「把真实错误挖出来」。

## 核心原则

1. **界面提示永远是二手的**，只用来定位时间点；真实错误一定在 `diagnostics/*.jsonl` 的 `detail` 字段里。
2. **先判断是「通道层」还是「模型层」问题**。用本地路由解析接口一秒定性（见第 2 步），别一上来就怀疑提示词或模型。
3. **绝不在输出里打印密钥明文**。核对 Key 只看「前缀 + 长度 + 是否含空格/非 ASCII」三个指标，就足以识别「整行粘贴」这类错误。
4. `generation-tasks/tasks.json` **不一定会持续落盘**（曾出现记到某天就停更的情况），近期报错必须从 diagnostics 里找。

## 关键路径

| 内容 | 路径 |
|---|---|
| 应用数据目录 | `C:\Users\<用户名>\AppData\Roaming\SoulLens` |
| 主进程日志 | 同上 `\desktop-main.log`（按启动轮转，只保留最近几天） |
| 渲染进程诊断日志 | 同上 `\diagnostics\renderer-diagnostics-*.jsonl`（★信息最全，含完整 error detail + breadcrumbs） |
| 应用层任务记录 | 同上 `\generation-tasks\tasks.json`（132+ 条，含 `phase` / `error` 全文） |
| 设置（明文） | `E:\SoulLens\settings\settings.json` |
| 密钥（加密） | `E:\SoulLens\settings\secrets.json` |
| 诊断时读到的缓存副本 | `AppData\Roaming\SoulLens\desktop-settings-bootstrap.json`（可能比 `E:\SoulLens` 那份旧） |
| 数据根目录 | `E:\SoulLens`（`projects/ output/ input/ .postgresql/ api-providers/`） |
| 本地后端 | `http://127.0.0.1:8189`（前端 `http://127.0.0.1:4189`） |

> 应用装在 `D:\软件\灵境\SoulLens`（`resources\app.asar`）；后端 exe 在 `resources\backend\soullens-backend\`。
> `settings.api-provider` 是**全局选中的 Provider**，排查时必看——它经常和模型实际归属的 Provider 不一致。

## 工作流

### 第 1 步：提取真实错误

扫 `diagnostics/*.jsonl`（按 mtime 取最近 2–3 个），只保留 `level in (error/warn/fatal)` 的记录，
打印关键字段 `timestamp / level / source / category / event / message / detail / taskId / nodeId / nodeType`，
**跳过 `breadcrumbs`**（噪音极大）。`detail.rawError` 和 `detail.code` 是根因所在。

### 第 2 步：一秒定性——通道层 or 模型层

若后端在跑，直接打路由解析接口：

```bash
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"model":"<出问题的模型 key>"}' \
  http://127.0.0.1:8189/api/execution-routes/resolve
```

- 返回 `{"ok":false,"status":400,"code":"EXECUTION_ROUTE_CONNECTION_UNAVAILABLE",...}`
  → **通道层问题**，请求根本没发出去，重试/换模型/换分辨率全部无效，去第 3 步查 Key。
- 返回正常路由 → 才轮到查模型参数、额度、敏感词。

### 第 3 步：核对 Provider 与 Key

读 `settings.custom-api-providers[]`，逐条输出 `id / name / enabled / apiKey 前缀 / apiKey 长度 / baseUrl`，
并加一条汇编判定：**合法的 key 应当是 `sk-` 开头、纯 ASCII、无空格**。

常见异常形态（可据此直接下结论）：

| 形态 | 含义 |
|---|---|
| `API` 开头、含空格、含非 ASCII（如 `API Key：sk-…`） | **用户把「API Key：xxx」整行粘进了密钥框**，含中文全角冒号 → 必挂 |
| 空字符串 | 该通道未配置 |
| 前缀正常但长度异常（如 `sk-` 但 116 字符） | 可能粘多了内容 |
| 多个 Provider 的 Key 完全相同 | 复制粘贴时带过来的，一起查一起修 |

同时读 `settings.custom-video-models-by-provider` / `custom-image-models-by-provider`，
确认**出问题的模型到底注册在哪几个 Provider 下**——只在坏通道下有注册的模型，必须先把该通道修好才能用。

### 第 4 步：看是否还有并发问题

主日志里 grep 这三类，别漏：

- `Failed to decrypt setting secret: <名字>` → Electron `safeStorage.decryptString` 失败（换 Windows 账户/换机/重装后 DPAPI 密钥变更），**必须重新登录**该账号，否则相关通道一直 401。
- `GET https://api.soullens.org/v1/models` → `401 Unauthorized` / `Invalid token` → Soullens 官方通道 token 失效。
- `524` / `origin_response_timeout` → Cloudflare 层面，Soullens 服务端超时，属服务端抖动，稍后重试即可。

### 第 5 步：产出修复步骤

按「主修复 / 备选 / 附带修复」三段写。备选方案通常是：**本机往往有另一条历史一直能用的通道**
（查 `tasks.json` 里 `phase=succeeded` 的近期任务，看它们用的 `provider` 和 `adapter`），
让用户把模型切到那条通道即可绕开。

## 已知错误码对照

| 错误码 / 关键词 | 含义 | 处理 |
|---|---|---|
| `EXECUTION_ROUTE_CONNECTION_UNAVAILABLE` (400) | 路由解析到的 Provider 无可用连接 | 修该 Provider 的 API Key / 或换通道 |
| `submission_unconfirmed` / `GENERATION_TASK_SUBMISSION_UNCONFIRMED` | 提交后无法确认是否成功（超时、断连） | 去 API 服务端核对任务状态；524 类等 120s 后重试 |
| `upstream_terminal` + `Invalid token` (401) | 上游 key 无效 | 换/补 Key |
| `insufficient_user_quota` (403) | 中转站余额不足 | 充值 |
| `model_not_found` / `No available channel for model …` (503) | 中转站没有该模型的分组 | 换模型或换通道 |
| `size total pixels must be between …` (400) | 出图尺寸超限 | 调分辨率 |
| Cloudflare `524 origin_response_timeout` | 源站 120s 未响应 | 服务端问题，稍后重试 |
| `Failed to decrypt setting secret` | 本地凭据解密失败 | 重新登录账号 |

## 数据安全

- 全程**只读**。不要修改 `settings.json` / `secrets.json` / `tasks.json`——改配置交给用户在界面里做。
- 输出报告时**不得包含密钥明文**，用掩码形态（ASCII 字母数字替换为 `x`，其余原样保留）表示。
- 可以查询运行中的本地后端接口（`127.0.0.1:8189`），那是只读诊断。
