---
name: image-ocr
display_name: "图片文字识别 OCR"
display_name_en: "Image OCR"
version: 1.0.0
description_zh: "图片文字识别助手：调用腾讯云/阿里云 OCR 接口，从截图、照片、文档图片中提取文字。支持中英日韩等 20+ 种语言、逐行置信度输出、双云服务商切换。当用户发来图片并要求「识别文字」「提取内容」「OCR」「图片转文字」时使用。"
description_en: "Extract text from images via Tencent Cloud or Alibaba Cloud OCR. Supports 20+ languages, per-line confidence, and provider switching. Use when the user asks to recognize, extract, or OCR text from a screenshot or photo."
description: "图片文字识别（OCR）Skill。当用户需要从图片中提取文字内容时调用 —— 例如用户发来一张截图/照片，要求「识别这张图片里的文字」「提取图片内容」「OCR 识别」「图片转文字」。支持腾讯云 OCR（默认）和阿里云 OCR 双后端，是 DeepSeek 等不原生支持图片识别的模型的关键补充能力。"
---

# Image OCR — 图片文字识别

使用腾讯云 / 阿里云 OCR API 从图片中提取文字，弥补 DeepSeek 等模型无法直接「看懂」图片的短板。

## 触发条件

当用户请求中同时包含「图片 / 截图 / 照片」+「识别 / 提取 / 查看 / OCR」等意图时触发。典型场景：

- 用户发来一张图片文件路径，要求识别内容
- 用户说「帮我看看这张图里写了什么」
- 用户想将截图中的文字提取出来用于后续处理

## 工作流程

### Step 1: 确认图片路径

从用户消息中提取图片文件路径。如果用户未提供路径，询问用户。

### Step 2: 检查环境变量

确认对应的云服务凭据已配置。运行前先检查：

```bash
# 腾讯云（默认）
echo ${TENCENTCLOUD_SECRET_ID:-"未设置"}
echo ${TENCENTCLOUD_SECRET_KEY:-"未设置"}

# 阿里云（备选）
echo ${ALIBABA_CLOUD_ACCESS_KEY_ID:-"未设置"}
echo ${ALIBABA_CLOUD_ACCESS_KEY_SECRET:-"未设置"}
```

如果凭据未设置，告知用户前往对应云平台获取 API 密钥：

- 腾讯云: https://console.cloud.tencent.com/cam/capi
- 阿里云: https://ram.console.aliyun.com/manage/ak

并指导用户设置环境变量：

```bash
export TENCENTCLOUD_SECRET_ID="your-secret-id"
export TENCENTCLOUD_SECRET_KEY="your-secret-key"
```

### Step 3: 安装依赖（首次使用）

```bash
# 腾讯云（默认推荐）
pip install tencentcloud-sdk-python

# 阿里云（备选）
pip install alibabacloud_ocr_api20210707
```

### Step 4: 执行 OCR 识别

使用包根目录下的 `ocr.py` 执行识别：

```bash
python3 ocr.py /path/to/image.jpg
```

常用参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--provider` | 服务商: `tencent` / `alibaba` | `tencent` |
| `--lang` | 识别语言: `zh`/`auto`/`en`/`jap`/`kor`/... | `zh` |
| `--json` | 输出 JSON 格式（含置信度等信息） | 纯文本 |

示例：

```bash
# 默认腾讯云，中英混合识别
python3 ocr.py screenshot.png

# 阿里云识别
python3 ocr.py photo.jpg --provider alibaba

# 自动检测语言 + JSON 输出
python3 ocr.py document.png --lang auto --json
```

### Step 5: 返回结果

将识别出的文字内容原样呈现给用户。如果使用了 `--json`，可以额外展示每行文字的置信度信息。

如果识别结果为空或置信度过低，提示用户图片可能不清晰或确实没有文字。

## 云服务商选择指南

| 维度 | 腾讯云 (默认) | 阿里云 |
|------|-------------|--------|
| 安装包 | `tencentcloud-sdk-python` | `alibabacloud_ocr_api20210707` |
| 接口 | GeneralBasicOCR | RecognizeGeneral |
| 本地文件 | 支持 (Base64) | 支持 (binary body) |
| 语言支持 | 20+ 种 | 自动多语言 |
| 免费额度 | 1000 次/月 | 200 次/月 |
| 推荐场景 | 日常使用 | 高精度需求 |

默认使用腾讯云。如果用户已有阿里云凭据，可用 `--provider alibaba` 切换。

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| 缺少凭据 | 环境变量未设置 | 引导用户配置 API 密钥 |
| SDK 未安装 | 缺少 pip 包 | 自动安装依赖 |
| 文件不存在 | 路径错误 | 确认文件路径 |
| 图片无文字 | 图片空白/纯图 | 告知用户未检测到文字 |
| API 调用失败 | 欠费/限频/网络 | 输出错误信息，建议换服务商 |
| 文件格式不支持 | 非图片格式 | 列出支持的格式 |

## 注意事项

- 图片大小建议 < 10MB，过大会影响识别速度
- 腾讯云 OCR 的 Base64 编码后不超过 10MB
- 推荐使用 PNG/JPG 格式，分辨率 600x800 以上效果更好
- 识别结果会保留原始换行结构
- 如需识别特定类型（身份证、银行卡、车牌等），腾讯云和阿里云均提供专门的卡证识别 API，本 skill 可扩展支持
