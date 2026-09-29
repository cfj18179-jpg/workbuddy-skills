---
name: 静态资产库搭建
description: 从零搭建「文件夹丢图 → 自动索引 → 分类导航画廊」的零依赖静态资产展示站，含本地热刷新预览与静态托管发布。当用户要建资产管理/素材库/展厅/作品集/图库展示站，或提到「资产库」「素材库」「图片展示站」「静态托管平台」「把资产放上去展示」时使用。
agent_created: true
---

# 静态资产库搭建

把一堆图片资产变成可浏览、可搜索、可发布的展示站。核心是**零依赖**（原生 HTML/CSS/JS），
所以能直接丢到任何静态托管，也没有构建等待。

## 一、成品结构

```
项目根/
├── index.html          入口（无内联脚本，除数据文件）
├── css/style.css
├── js/app.js           左分类树 + 瀑布流画廊 + 灯箱
├── data/
│   ├── asset-index.js  ★ 自动生成：window.ASSET_INDEX = {...}
│   └── asset-index.json  同内容的 JSON（备用）
├── build-index.mjs     递归扫描 assets/ 生成索引
├── serve.mjs           本地预览服务 + 自动重建 + SSE 热刷新
└── assets/             ★ 用户放图的地方，文件夹层级 = 分类层级
```

## 二、五个关键决策（照抄，别重新发明）

1. **索引输出成 JS 变量而不是 JSON 文件**
   `window.ASSET_INDEX = {...}`，用 `<script src>` 加载。
   这样双击 `index.html`（`file://` 协议）也能正常打开，绕开 fetch 的 CORS 限制；
   发布到线上又完全不受影响。同时另存一份 `.json` 备用。

2. **URL 分段编码**
   `'assets/' + rel.split('/').map(encodeURIComponent).join('/')`
   只编码每一段、保留 `/`，否则中文/空格路径和子目录结构一起完蛋。

3. **索引阶段预读图片尺寸 —— 这是不跳动的关键**
   只读文件头即可，别用图像库：
   - PNG：偏移 16/20 大端读宽高
   - GIF：偏移 6/8 小端
   - BMP：偏移 18/22
   - JPEG：遍历段找 SOF0/1/2（`0xC0-0xCF`，排除 `0xC4/0xC8/0xCC`），宽在 `seg+7`、高在 `seg+5`
   - WebP：VP8 / VP8L / VP8X 三种 chunk 分别解析
   - SVG：正则读 `width/height`，没有就用 `viewBox` 的第 3、4 个数
   用 `fs.openSync` + `readSync` 只读前 256KB，别 `readFileSync` 整张图。

4. **瀑布流 = `grid-auto-rows: 8px` + JS 算 span**
   ```css
   .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(var(--card-w),1fr));
           grid-auto-rows:8px; column-gap:18px; row-gap:0; align-items:start; }
   ```
   ```js
   // 卡片插入 DOM 后（此时 clientWidth 才有效）批量计算
   const imgH = card.clientWidth * (file.h / file.w);
   const metaH = card.querySelector('.card-meta').offsetHeight;
   card.style.gridRowEnd = 'span ' + Math.ceil((imgH + metaH + 2 + 18) / 8);
   ```
   有了第 3 步的尺寸，span 在图片加载**之前**就能算准 → 零布局跳动。
   尺寸未知时退回 `img.naturalHeight / naturalWidth`，在 `load` 事件里补算。

5. **懒加载用 IntersectionObserver + 大 rootMargin（约 1600px）**
   不要用原生 `loading="lazy"`（它和 span 预排版的节奏对不上）。
   `root` 指向滚动容器。

## 三、其余要点

- **热刷新**：`serve.mjs` 里 `fs.watch(assetsDir, { recursive: true })` + 防抖 250ms 重建，
  通过 `text/event-stream` 广播 `data: reload`，前端 `EventSource` 收到就 `location.reload()`。
  只在 `/^https?:$/.test(location.protocol)` 时启用。
- **静态服务**：`decodeURIComponent` 后再 `path.join(root, rel)`，必须校验 `filePath.startsWith(root)` 防目录穿越。
  图片给长缓存 `max-age=86400`，html/css/js 给 `no-cache`。
- **分类树**：递归渲染 `<ul>`，`caret` 只负责展开（`stopPropagation`），整行点击负责选中；
  目录点击后展示**递归**的全部图片，并**按子目录分组**显示（否则父目录会显示为空，体验很差）。
- **搜索**：命中范围 = 文件名 + 扩展名 + 分类路径；命中片段用 `<mark>` 高亮。
  高亮时**分段转义**再拼接，不要先转义整体（索引会错位）。
- **健壮性**：`window.matchMedia`、`IntersectionObserver`、`EventSource` 一律先判存在再用 ——
  任何一个缺失都会让 `bindEvents` 抛错、整个初始化中断（这是实测踩过的坑）。
- **主题**：跟随当前 IDE 主题，浅色用 `#f5f6f8` 底 + `#fff` 卡片 + 一个 `--accent`；
  所有颜色收在 `:root` 里，方便用户改主色。

## 四、执行步骤

1. 先问清三件事：**内容类型**（纯图 / 图+视频）、**上架方式**（丢文件夹 / 网页后台上传）、**展示风格**（画廊 / 分类导航 / 文件夹树）。
2. 建目录 + 写 `build-index.mjs`（含尺寸预读）→ 跑一次验证索引结构。
3. 写 `serve.mjs` → `curl -o /dev/null -w "%{http_code}"` 验证 200。
4. 写前端三件套。
5. 造几张示例图放在 `assets/示例·xxx/`（明确标注"示例"，README 里说明怎么删），
   没有示例的空站点用户看不出效果。
6. **验证**（重要，别跳过）：装 jsdom 到隔离工作区
   `cd ~/.workbuddy/binaries/node/workspace && npm install jsdom`，
   写临时 `.cjs` 测试：`new JSDOM(html, { runScripts:'dangerously', pretendToBeVisual:true })`，
   移除 `<script src>` 后手动 `window.eval()` 注入数据与逻辑，
   mock 掉 `clientWidth/offsetHeight`，然后断言树节点数、卡片数、切换/搜索/灯箱行为。
   跑完删除临时测试文件。
7. 写 `README.md`（如何加资产、改分类、改主色、发布）。
8. `present_files` 传 `http://localhost:<port>` 预览 + README。

## 五、Windows 环境注意

- 默认 shell 缺 PATH，命令前先 `export PATH="/usr/bin:/bin:$PATH"`。
- PowerShell 工具会拦截含 `%XX` 的 URL（误判为 cmd 变量），HTTP 验证一律改用 `curl`。
- 传路径给 node 用 `C:/Users/...` 正斜杠格式，MSYS 的 `/c/...` 会被当成 `C:\c\...`。
