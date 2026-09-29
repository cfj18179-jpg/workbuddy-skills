---
name: 资产预览站优化发布
description: 把「本地离线资产预览 HTML」（自包含 index.html + 场景/人物/道具 等图片子目录 + 提示词 txt）优化成体积可控、可对外分享的网页版：解析内嵌 JSON 数据 → 原图批量转 WebP → 改写引用 → 拷贝提示词 → 校验完整性 → 再交给 sites 发布。触发词：预览站发不出去、资产预览分享、离线预览转在线、html 太大发不了、chatgpt.site 打不开。
agent_created: true
---

# 资产预览站优化发布

## 什么时候用

用户的资产交付类 HTML（Codex / 脚本生成的「全资产预览.html」）情况是：

- **本地能看，别人打不开** —— 典型是发布到了 `*.chatgpt.site` 之类的受限托管，Cloudflare 直接对非授权来源返回 `403 / Sorry, you have been blocked`（正文是拦截页，不是站点内容）。
- **整包体积过大发不出去** —— 本地 PNG 原图动辄 500MB~1GB（1672×941 的 3D 渲染图约 1.5~3MB/张），无法直接上传发布。

这类站点的结构高度一致：**单个自包含 HTML + 几个分类图片子目录 + 每资产一个提示词 txt**，且 HTML 里内嵌一个 `type="application/json"` 的数据块（通常 `<script id="assetData">`），每条记录形如：

```json
{"name":"乔月家客餐厅","category":"场景","episodes":"...","description":"...",
 "txt":"%E5%9C%BA%E6%99%AF/xxx.txt","fullText":"...",
 "variants":[{"label":"正面","src":"%E5%9C%BA%E6%99%AF/xxx_%E6%AD%A3%E9%9D%A2.png",
              "filename":"xxx_正面.png","prompt":"...","width":1672,"height":941}]}
```

`src` / `txt` 是 **URL 编码的相对路径**。所以改造只需动数据、不动 UI 逻辑。

## 核心原则

1. **改数据不改代码**：只替换 JSON 里的 `src` / `filename` 后缀和少量界面文案，绝不重写渲染逻辑（分页、懒加载、键盘导航、筛选都保留）。
2. **必须先摸清引用计数再动手**：`.png` 出现次数应当**恰好等于 图片数 × 2**（`src` + `filename`）。若不等，说明提示词正文里也含 `.png` 字样，此时**禁止全局替换**，必须走 JSON 解析后逐字段改写。
3. **图片保持原生分辨率**，只换编码（PNG → WebP）。资产审片看的就是细节，不要为了体积缩图；体积靠 WebP 就够（实测 **616.8MB → 33.0MB，约 5.3%**，肉眼几乎无差）。
4. **发布前必须单独征得同意**：把几百张客户交付级资产图公开到互联网是重大动作，不能因为「用户说发不出去」就自作主张上线。本地做完先给用户看，再问。

## 标准流程

### Step 1 — 定位工程目录

在用户机器上按关键词找（`tianwen` / `穿书` / `资产` / `预览` 等），定位到含 `*预览*.html` 的项目根目录，确认三个兄弟目录（如 `场景/` `人物/` `道具/`）。**先跑结构盘点**：各目录 png/txt 数量、根目录文件清单、总字节数。

### Step 2 — 解析数据块并核对引用

用 `scripts/optimize_site.py --probe` 只做体检、不产出：

- 解析内嵌 JSON，打印资产数、分类分布、字段名、变体字段名；
- 统计 `.png` 总数 vs `src`/`filename` 计数（判断能否安全全局替换）；
- 校验每个 `src` 解码后在磁盘上是否存在（应为 0 缺失）。

### Step 3 — 转换 + 改写

```bash
python scripts/optimize_site.py --src-html "E:\...\全资产预览.html" --out "E:\...\全资产预览_分享版" --quality 78
```

脚本做四件事：PNG→WebP（`method=5`）、拷贝被引用的 txt（含根目录 `交付说明.txt`）、JSON 字段后缀改写、少量 UI 文案改写（"本地离线预览"→"在线预览 · N 张图片"、`px · PNG`→`px · WebP`）。JSON 重新序列化时必须 `ensure_ascii=False` 并把 `</` 转义成 `<\/`，否则会提前闭合 `<script>`。

### Step 4 — 校验

```bash
python scripts/verify_site.py --root "E:\...\全资产预览_分享版"
```

必须全部通过：图片引用 0 缺失、提示词 0 缺失、残留 `.png` 引用为 0、`.webp` 引用数 = 图片数 × 2。

### Step 5 — 本地预览

用 present_files 打开分享版 `index.html`（相对路径引用会被本地预览服务正常解析）。**让用户先看效果**。

### Step 6 — 征询是否发布

本地完工后**停下来问一次**，说明：会上线成公开链接、任何人拿到链接都能看、涉及 N 张交付级资产图。得到明确同意后才调用 `发布应用` / `workbuddy_sites_deploy`（`directory` = 分享版目录，`language=static`，传 `appName` 与 `userAskedToPublish: true`）。

## 参数取值参考

| 参数 | 建议值 | 说明 |
|---|---|---|
| WebP quality | **78** | 78 已肉眼无差；68 可再省三成但有边缘劣化风险 |
| method | 5 | 6 更小但慢一倍，收益很小 |
| 缩放 | **不缩放** | 保持 1672×941 原生尺寸 |
| 单图预期体积 | 56~204KB | 平均约 110KB；若远超说明图是超大分辨率，需复核 |

## 坑

- **别用 90° 正侧 / 3/4 侧面描述资产**——那是用户的分镜术语，与本站无关；只管文件与数据。
- **别把 `filename` 留着 `.png`**：它被 `download` 属性用作下载文件名，内容已是 webp，留着会下出一个名不副实的文件。
- 目录名含中文没问题，但发布工具的 `directory` 传绝对路径，别传相对路径。
- `bash` 环境可能缺 `cat` / `tail` / `dirname`：写脚本用 Write 工具，不要用 heredoc；删文件用 `node -e "fs.unlinkSync"`。
- `--dir` 类批量分析有 200 张上限，本流程走的是显式 JSON 引用清单，不受此限。
