---
name: image-viewer
version: 1.0.0
display_name: 图析
display_name_en: image-viewer
description_zh: "图析（图像画面几何分析）：分析静态图片的画面与几何特征，适用截图、照片、图表、UI 界面：识别并 analyze 画面类型、明暗主题、主色、布局几何结构，支持单图、批量目录对比、两图一致性。触发词：看截图、这是什么画面、图片布局几何、分析 UI 界面。仅用于 analyze image file（Only for image file），不做 OCR、人脸识别、视频、图片生成（not for those）。"
description_en: "Image Geometry Analyzer: Analyzes the visual and geometric features of static images — for screenshots, photos, charts, and UI screens: identifies picture type, light/dark theme, dominant colors, and layout geometry structure. Supports single-image analysis, batch directory comparison, and two-image consistency checks. Trigger words: analyze this screenshot, what is this picture, image layout geometry, analyze UI screen. Only for analyzing image files; not for OCR, face recognition, video, or image generation."
description: 图析（图像画面几何分析）：分析静态图片的画面与几何特征，适用截图、照片、图表、UI 界面：识别并 analyze 画面类型、明暗主题、主色、布局几何结构，支持单图、批量目录对比、两图一致性。触发词：看截图、这是什么画面、图片布局几何、分析 UI 界面。仅用于 analyze image file（Only for image file），不做 OCR、人脸识别、视频、图片生成（not for those）。
agent_created: true
---

# 图片查看与分析 Agent

本技能用于在当前模型无法直接查看图片时，对单张或多张静态图片进行结构化分析。通过三层策略（Agent 多模态调度 → Python PIL 像素分析 → 上下文推断）确保在任意环境下都能产出可靠的内容描述与结构判断。

## 依赖与需求 (Dependencies and Requirements)

- **Python 3**：脚本 `scripts/analyze_image.py` 依赖 Python 3 与 `Pillow`（PIL）库。
- **安装方式**：如脚本报 `PIL/Pillow not installed`，执行 `pip install Pillow`（见「边界情况与错误处理」）。

## 三层分析策略（按优先级）

### 策略 1：Agent 多模态调度（首选）

当具备能读取图片的多模态 Agent 时，调度其读取图片：

```text
Agent prompt 模板：
请读取以下图片文件，逐张描述其内容：
- 文件路径：{image_paths}
- 每张图片需要描述：
  1. 画面类型（截图/照片/图表/UI界面）
  2. 主要视觉元素（文字、UI组件、图标、人物）
  3. 关键文字内容（尽可能详细）
  4. 颜色特征（深色/浅色主题、主色调）
- 输出格式：图片文件名 | 类型 | 详细内容描述
- 只输出分析结果，不修改任何文件
```

**降级**：Agent 调度可能失败（如 400 canceled），此时自动降级到策略 2，无需中断。

### 策略 2：Python PIL 像素分析（可靠兜底）

使用 `scripts/analyze_image.py` 进行结构化分析。该脚本无需 AI 模型，100% 可执行。

脚本支持**单张分析**与**批量目录分析**两种模式：

**单张分析**（输出完整结构化 JSON）：

```bash
python3 scripts/analyze_image.py image.jpg
python3 scripts/analyze_image.py image.jpg --output result.json --detail high
```

**批量目录分析**（扫描文件夹内全部支持的图片，输出标准化对比表）：

```bash
python3 scripts/analyze_image.py --dir ./screenshots/ --output batch.json --detail medium
```

**两图对比**（UI 截图回归、图表变体、渲染一致性核验）：

```bash
python3 scripts/analyze_image.py --compare ./before.png ./after.png --output compare.json
```

- `--detail` 支持 `high|medium|low`，控制采样精度。
- **批量模式（--dir）**：自动扫描指定目录下所有受支持图片（png/jpg/jpeg/webp/gif/bmp/tif/tiff），对每张提取紧凑汇总行（文件名、尺寸、宽高比、明暗主题、是否含文本、画面类型推断），输出统一可比对的结构化结果，供批量对比排序使用。
  - **单文件损坏降级**：任何一张图片解码失败/文件损坏都不会中断整批分析。该文件会被记录为单条 `error: "corrupted or unreadable image"` 条目，并在顶层输出 `error_count` 与 `degraded: true` 提示，其余正常文件照常分析完毕。
- **对比模式（--compare）**：对两张图片计算结构相似度，输出 `similarity_score`（0-100）、`mean_pixel_diff`、完全相同/显著差异像素占比与 verdict（identical/similar/different），用于 UI 版本回归或图表变化检测。

脚本输出结构（`--detail` 支持 high/medium/low）：

```json
{
  "file": "screenshot.jpg",
  "dimensions": {"width": 1920, "height": 1080},
  "aspect_ratio": 1.78,
  "analysis": {
    "color": {
      "brightness": {"dark_pct": 65, "mid_pct": 25, "light_pct": 10, "dominant": "dark"},
      "is_dark_theme": true,
      "hue_dominance": {"red_pct": 3, "green_pct": 5, "blue_pct": 15, "gray_pct": 60}
    },
    "layout": {"header_likely": true, "content_starts_at_pct": 8.5},
    "edge_density": {
      "avg_edge_density": 7.2,
      "likely_screenshot_of_text": true,
      "text_rich_zones": 8,
      "flat_zones": 4
    },
    "screen_type": {
      "clues": ["dark_theme", "has_ui_chrome", "likely_code_editor"],
      "best_guess": "代码编辑器/终端截图 (暗色主题)"
    },
    "zones": [{"row": 2, "col": 3, "avg_color": "rgb(90,200,120)", "brightness": 136.7, "saturation": 110.0}]
  }
}
```

**像素分析能做什么**：判断深色/浅色主题、检测 UI 框架（header/footer/toolbar）、识别文本密集区域、检测特征色（红/绿/蓝/橙/黄占比）、推断画面类型（截图/文档/代码/图表/普通照片）、判断图片是否为纯色/低纹理画面。脚本会将接近单一纯色、几乎无边缘细节的图片优先识别为「纯色/低纹理画面」，不会误判为带 UI 框架的应用截图。

**像素分析不能做什么**：读取具体文字内容（需 OCR，未集成）、理解图表含义、识别人脸/物体。这些场景应明确告知用户能力边界，而不是强行解读。

### 策略 3：上下文推断

当图片已在对话历史中、且此前摘要已包含描述时，直接使用摘要中的信息重建画面内容，无需重复分析，以节省计算。

## 标准输出模板

无论走哪条策略，最终描述应遵循统一结构，确保多张图片输出一致、可对比：

```text
文件：<文件名>
- 画面类型：<截图/照片/图表/UI/纯色块/代码编辑器等>
- 主题：<深色/浅色>
- 尺寸：<宽>x<高>，宽高比 <x.xx>
- 主要特征：<文字密集区、UI组件、主色、内容区域描述，2-4 条>
```

批量分析时，按上述模板逐张列出，最后可加一行对比小结。

## 完整操作流程

### 单张图片分析

1. 确认图片路径存在且可读。
2. 尝试策略 1（Agent 调度）。
3. 失败则运行策略 2（PIL 分析）获取像素特征。
4. 整合像素特征 + 已有上下文，按「标准输出模板」给出描述。

### 多张图片批量分析

1. 若图片集中在同一目录，直接运行 `scripts/analyze_image.py --dir` 并传入该目录路径，一键分析并获取标准化对比表（推荐）。
2. 若图片分散在不同位置，先收集路径，再逐张运行单张模式收集 JSON。
3. 读取所有结果，按标准化汇总行的特征（明暗主题、是否含文本、画面类型）排序与对比。
4. 若策略 1 可用，优先用 Agent 读文本密集的截图；否则直接用像素结果整合。

### 图片对比分析

当需要核验两张图是否一致（UI 版本回归、图表前后对比、多截图对比确认）：

1. 运行 `scripts/analyze_image.py --compare` 并传入两张图片路径，获取结构相似度结果。
2. 依据 `similarity_score` 与 verdict（identical/similar/different）判断差异程度。
3. 若 verdict 为 different，结合两张图各自的画面类型与主题判断差异性质（主题反转、内容替换、或仅是尺寸/裁剪差异），如实报告。

## 边界情况与错误处理

- **文件不存在 / 路径错误**：脚本返回 `{"error": "File not found: ..."}`。先核实路径，报告用户并提供正确路径，不强行分析。
- **空白/纯色图片**：像素分析会给出统一亮度、低文本密集区与少量 zones。应如实判断为「纯色/低纹理画面，几乎无内容区域」，不要臆造文字或物体。
- **Pillow 未安装**：脚本输出 `{"error": "PIL/Pillow not installed..."}`。先用 `pip install Pillow` 安装并重试。
- **Agent 调度失败**：按降级逻辑自动切到策略 2，并在最终输出中说明使用了像素分析兜底。
- **图片内容过简**（如纯色块）：不要报错，仍产出结构化结果，明确表示「内容区域为空集或极少」。
- **脚本异常**：若脚本报错，先检查 Python/Pillow 版本与图片是否损坏；确认图片格式受支持（PNG/JPEG 等），必要时换图重试。
- **超大目录**：批量模式设有分析上限（`MAX_DIR_ANALYZE=200` 张）。当目录内受支持图片超过上限时，脚本只处理前 200 张并置 `partial_processed: true`，明确告知结果是「截断扫描」而非完整结果，避免内存/时间失控。如确需全量，可分目录或缩小范围分批处理。
- **能力边界**：需要识别具体文字（OCR）、识别人脸/物体、理解图表语义时，明确告知超出当前像素分析能力，建议配合能直接读图的方案。

## 与 cross-model-visual-analysis 的协作

| 能力 | image-viewer | cross-model-visual-analysis |
|------|-------------|---------------------------|
| 静态图片分析 | ✅ 专注 | ✅ 支持 |
| 视频帧提取 | ❌ | ✅ ffmpeg |
| 文案→画面映射 | ❌ | ✅ 工作流 B |
| 标题卡生成 | ❌ | ✅ Python PIL |
| 像素级分析 | ✅ 强化脚本 | ✅ 基础模板 |
| Agent 调度 | ✅ 含降级逻辑 | ✅ 含降级逻辑 |

两个技能互补：`cross-model-visual-analysis` 负责视频全流程，`image-viewer` 负责静态图片的深度分析。当检测到请求属于视频/文字/人物识别类而非静态图片分析时，应拒绝触发或指明交由 cross-model-visual-analysis。

## 注意事项

1. **PIL 依赖**：脚本需要 Pillow 库，首次使用需 `pip install Pillow`。
2. **批量分析**：优先用策略 3（上下文推断）避免重复分析，但若上下文缺失仍需实际分析。
3. **Agent 限制**：Agent 调度不是每次都能成功，PIL 兜底是稳定保障。
4. **结果整合**：PIL 分析给出的是「画面结构」，需结合上下文才能理解完整内容。
5. **诚实边界**：像素分析无法读取具体文字或识别物体，输出时应如实标注，不臆造内容。
6. **不含项目数据**：本技能只封装分析方法和脚本，不包含任何项目特定数据。
