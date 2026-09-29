# 图片文字识别 OCR（Image OCR）

一个 AI 助手图片文字识别能力扩展 Skill：调用**腾讯云 OCR**（默认）或**阿里云 OCR**，从截图、照片、扫描件中提取文字，弥补 DeepSeek 等不原生支持视觉输入的模型「看不懂图」的短板。

## 它解决什么问题

| 没有本 Skill | 装上本 Skill 后 |
|---|---|
| 模型收到图片路径只能"盲猜"内容 | 直接调用云端 OCR，把图里的文字原样提取出来 |
| 截图里的表格、报错、代码要手动抄 | 一条命令输出全部文字，可继续喂给模型处理 |
| 只能用一家云服务，换云要改代码 | 双后端热切换：腾讯云 / 阿里云一个参数搞定 |

## 核心能力

- **双云服务商**：腾讯云 `GeneralBasicOCR`（默认）/ 阿里云 `RecognizeGeneral`，`--provider` 一键切换
- **多语言识别**：中、英、日、韩等 20+ 种语言，支持 `auto` 自动检测
- **逐行置信度**：`--json` 输出每行文字及其置信度，方便后续做质量过滤
- **保留版式**：识别结果保留原始换行结构，直接可用于文档还原
- **宽格式支持**：PNG / JPG / JPEG / BMP / GIF / TIFF / WebP / PDF

## 快速开始

### 1. 配置云凭据（二选一，按需）

**腾讯云（默认，免费额度 1000 次/月）**

到 [腾讯云 API 密钥控制台](https://console.cloud.tencent.com/cam/capi) 创建密钥，然后：

```bash
export TENCENTCLOUD_SECRET_ID="your-secret-id"
export TENCENTCLOUD_SECRET_KEY="your-secret-key"
```

**阿里云（免费额度 200 次/月）**

到 [阿里云 AccessKey 管理](https://ram.console.aliyun.com/manage/ak) 创建密钥，然后：

```bash
export ALIBABA_CLOUD_ACCESS_KEY_ID="your-access-key-id"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your-access-key-secret"
```

### 2. 安装依赖（首次使用）

```bash
# 腾讯云（默认推荐）
pip install tencentcloud-sdk-python

# 阿里云（备选）
pip install alibabacloud_ocr_api20210707
```

### 3. 运行识别

```bash
# 最简用法：腾讯云识别截图，输出纯文本
python3 ocr.py screenshot.png

# 用阿里云识别
python3 ocr.py photo.jpg --provider alibaba

# 自动检测语言 + JSON 输出（含逐行置信度）
python3 ocr.py document.png --lang auto --json
```

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `image`（位置参数） | 图片文件路径 | 必填 |
| `--provider` | OCR 服务商：`tencent` / `alibaba` | `tencent` |
| `--lang` | 识别语言：`zh` / `auto` / `en` / `jap` / `kor` / ... | `zh` |
| `--json` | 输出 JSON（含逐行置信度、语言、图片角度等） | 纯文本 |

### JSON 输出示例

```json
{
  "provider": "tencent",
  "full_text": "会议纪要\n2026年9月3日",
  "lines": [
    { "text": "会议纪要", "confidence": 99 },
    { "text": "2026年9月3日", "confidence": 98 }
  ],
  "language": "zh",
  "angle": 0
}
```

## 服务商对比

| 维度 | 腾讯云（默认） | 阿里云 |
|------|-------------|--------|
| 接口 | GeneralBasicOCR | RecognizeGeneral |
| 本地文件 | 支持（Base64） | 支持（binary body） |
| 语言支持 | 20+ 种，需指定 | 自动多语言 |
| 免费额度 | 1000 次/月 | 200 次/月 |
| 推荐场景 | 日常高频使用 | 高精度 / 多语种混排 |

## 错误排查

| 现象 | 原因 | 处理 |
|------|------|------|
| 提示缺少凭据 | 环境变量未设置 | 按上方步骤配置 `export` |
| 提示未安装 SDK | pip 包缺失 | `pip install` 对应 SDK |
| 文件不存在 | 路径错误 | 核对图片路径 |
| 未识别到任何文字 | 图片空白或纯图案 | 换更清晰的图片 |
| API 调用失败 | 欠费 / 限频 / 网络 | 查看错误信息，或 `--provider` 换服务商重试 |
| 格式警告 | 非常见图片格式 | 仅支持 PNG/JPG/BMP/GIF/TIFF/WebP/PDF |

## 使用建议

- 图片控制在 **10MB 以内**（腾讯云 Base64 编码后同样不超过 10MB）
- 分辨率 **600×800 以上**识别效果更好
- 密钥属于敏感凭据，建议只通过环境变量注入，不要写进代码或提交到仓库
- 如需身份证、银行卡、车牌等专用卡证识别，腾讯云/阿里云均有专门 API，可在此 Skill 基础上扩展

## 目录结构

```
image-ocr/
├── SKILL.md        # Skill 定义与触发规则（AI 助手读取的入口）
├── README.md       # 本文件：产品介绍与使用说明
├── workbuddy.json  # 开放平台展示元数据（名称、中英描述）
├── meta.json       # 运行时依赖声明（Python 版本、SDK、环境变量）
├── _icon.svg       # 图标
└── ocr.py          # OCR 执行脚本（腾讯云/阿里云双后端）
```

## 版本

- **1.0.0** — 首个发布版本：腾讯云/阿里云双后端、多语言、JSON 置信度输出
