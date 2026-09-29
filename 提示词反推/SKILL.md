---
name: 提示词反推
display_name: 提示词反推（无视觉模型兜底）
description_zh: "当用户要求「反推图片提示词 / 这张图是什么提示词生成的」而当前模型不支持读图时的完整兜底方法论：先抓项目自有的提示词物料并本地 OCR，再用 OpenCV 做白底分离与版式切分、分区取色，最后结合剧本/设定文档产出分级的提示词档案（原文级 / 重建级）。触发词：反推提示词、这张图用什么提示词、还原提示词、图片提示词提取、prompt reverse。"
description_en: "Reverse-engineer image prompts without a vision model: harvest in-project prompt material + local OCR, then OpenCV white-background segmentation / layout split / per-band color sampling, then combine with script/design docs to output graded prompts (verbatim vs reconstructed)."
agent_created: true
---

# 提示词反推（无视觉模型兜底）

## 适用场景

用户说「反推这个目录所有图片的提示词」「这张图是怎么生成的」「还原一下提示词」，**而当前会话模型不支持读图**
（DeferredExecute/Read 图片会报 `does not support reading images` / 图片被当成 `[Unsupported Image]`）。

**先做这一步判定**：读 `~/.workbuddy/models.json`，看 `supportsImages` 字段。若全为 false，走本技能；
若有支持读图的模型，优先直接切模型读图（本技能仍可作为交叉验证手段）。

## 核心原则

1. **不许瞎编画面细节。** 没有视觉输入时，任何"人物是什么样"的描述都必须来自可验证证据：
   ① 项目自有提示词物料（最高优先）② 像素测量 ③ 剧本/设定文档。三者都没有 → 明确标注"待确认"，不要猜。
2. **交付物必须分级标注**：🟩【原文】（从物料 OCR 得到的原始提示词）/ 🟨【重建】（模板+设定+测量重建）。
3. 开头就向用户说明方法与限制，并给出"要升级为精确版"的两条路（换多模态模型 / 用户口述 3 条关键特征）。

## 步骤

### 第 0 步：环境排障（Windows 上必做）

- **Bash 工具可能缺 coreutils**（`ls/find/head` 报 command not found）——先导出：
  `export PATH="/c/Users/EDY/.workbuddy/binaries/PortableGit/versions/1.2.0/usr/bin:$PATH"`
- **PowerShell 工具的 stdout 可能被吞**（只回 "Command completed"）→ 优先用 Bash + 完整 PATH。
- 隔离 Python：`C:/Users/EDY/.workbuddy/binaries/python/envs/default/Scripts/python.exe`
- 已装：numpy / Pillow / **opencv(cv2 5.x)** / markitdown / **rapidocr-onnxruntime** / pymupdf / onnxruntime / tokenizers
- **cv2.imread 读不了中文路径** → 必须 `cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)`
- **cv2 5.0 已移除 CascadeClassifier / cv2.objdetect**；有 `cv2.FaceDetectorYN`（需另下 ONNX）。
  可用列投影切分代替人脸检测来判断版式。
- 网络：HF / github raw 不通；**pypi 清华镜像 + bcebos（Paddle 模型库）可用**，pip 装包走
  `-i https://pypi.tuna.tsinghua.edu.cn/simple`。没有可用的云视觉 API（用户未配置 OCR 云密钥）。

### 第 1 步：找项目自有的提示词物料（价值最高，务必先做）

图片所在目录往往只是成品，**提示词物料通常躺在同一个项目里**。按以下线索全盘搜索：

```bash
# 1) 文件名线索
find <项目根> -maxdepth 4 -iname "*提示词*" -o -iname "*资产*" -o -iname "*prompt*" \
  -o -iname "*设定*" -o -iname "*工程*"
# 2) 交付/材料类目录（截图里常有界面上的提示词全文）
ls 交付 材料 交付/材料 交付/*材料 资产截图 生成视频提示词
# 3) 文本/文档类
find <项目根> -maxdepth 4 \( -iname "*.docx" -o -iname "*.pdf" -o -iname "*.md" -o -iname "*.txt" \)
```

典型命中：`ai提示词1~4.png`、`资产截图/*.png`、`资产图.pdf`、`XXX资产管理界面截图`、剧本 docx。

### 第 2 步：本地 OCR 抽取提示词

用 `scripts/ocr_batch.py <目录或文件...>`（内置 rapidocr，中英日韩离线，无需密钥）。
- PDF 先 `pymupdf` 渲染（170 dpi 起，小字用 320 dpi），再 OCR。
- 大图先缩到长边 ≤2600 再 OCR，否则慢且可能漏。
- 结果按 y 分行、x 排序拼回阅读顺序。
- **注意 OCR 错字**：中文模型会把「杨戬→杨哉/杨截/杨戳」「萱花斧→置花笋」「灌江口→泄江口」
  「宝莲灯→宝连灯」等认错；引用"原文"时按上下文校正，并在文档里说明已校正。

### 第 3 步：像素结构测量（客观证据层）

用 `scripts/analyze_layout.py <图片目录>`。它做四件事：

1. **底色判定**：近白像素（min channel > 236）占比 > 20% → 白底资产图；否则为满幅场景图。
2. **版式切分**：白底图按「整列为空」切分 → 输出每个子体的 x/y 范围、宽高比、实心度。
   - 关键判读：**左侧一个大块（面部特写）+ 右侧 2~3 个等高窄块 = 人物三视图资产卡**
     （正/侧/背；侧视块通常最宽）。多份素材实测版式与此完全一致。
   - 单一居中主体 + 高宽比大 → 竖置道具；横跨全画 + 实心度 <25% → 斜置长兵器。
3. **纵向 10 带分区取色**：输出每带的 top3 色（中文色名 + RGB + 占比），
   可反推发色（带1-2）、肤色、甲胄（带4-6）、下装/靴（带8-10）。
4. **3×3 网格色**（场景图）+ 全图主色统计 + 亮度/对比。

### 第 4 步：语义锚点

- 剧本/小说 docx → `markitdown` 转 md，再 grep 资产名，抽取服装、兵器、场景、天气的**原句**。
- 没有 docx 时用文件名 + 项目世界观推断，但必须标"推测"。

### 第 5 步：产出分级提示词档案（Markdown）

每条资产按这个结构写：

```
## N. 文件名 🟩原文 / 🟨重建
**实测**：尺寸｜底色占比｜版式切分｜主色 RGB 占比
🔍 校核结论：测量结果与原提示词是否吻合（例："近黑占26% → 与玄黑袍一致 ✅"）
**提示词**：中文可直接用版（沿用项目模板：风格/人物特征/年龄/性别/体型/脸型/服装/背景要求）
**英文精简版**（可选，60~90 词，供只看英文的工具用）
```

最后必须附：
- **待确认清单**（哪几条是推测）
- **升级路径**（换多模态模型 / 用户补 3 条关键特征）
- 保留中间产物：`ocr_*.txt`、`analyze_*_report.txt` 一起交付。

## 常见坑

| 坑 | 处理 |
|---|---|
| 用户以为你能看图 | 开头直接说明限制，但**先给出已完成的实质工作**，不要只提问 |
| 背景检测把白底判成非白底（四边带众数占比低） | 改用「近白像素占比」判定，别用边缘众数单一条件 |
| 掩膜算成全图（主体 100% 占画） | 说明该图背景非纯色，改用 3×3 网格色描述 |
| 道具图斜置，列切分只出 1 段 | 属正常；用「横跨百分比 + 实心度」描述形状 |
| 提示词物料是图片截图 | 只有本地 OCR 一条路；云 OCR 需密钥，用户通常没配 |
