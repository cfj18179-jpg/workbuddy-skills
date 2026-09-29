# -*- coding: utf-8 -*-
"""把「本地离线资产预览 HTML」优化为可分享/可发布的网页版。

用法：
    # 只体检，不产出
    python optimize_site.py --probe --src-html "E:\\...\\全资产预览.html"

    # 生成分享版
    python optimize_site.py --src-html "E:\\...\\全资产预览.html" \
                            --out "E:\\...\\全资产预览_分享版" --quality 78
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from urllib.parse import unquote

from PIL import Image

IMG_EXT = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')
JSON_BLOCK = re.compile(
    r'(<script[^>]*type="application/json"[^>]*>)(.*?)(</script>)', re.S)


def find_json_block(html):
    m = JSON_BLOCK.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(2).replace('<\\/', '</'))
    except Exception:                                    # noqa: BLE001
        return None
    return m, data


def iter_refs(data):
    """产出 (容器dict, 字段名) —— 值为 URL 编码相对路径。"""
    for a in data:
        if not isinstance(a, dict):
            continue
        for key in ('txt', 'text', 'file', 'path'):
            if isinstance(a.get(key), str):
                yield a, key
        for v in a.get('variants', []) or []:
            if isinstance(v, dict):
                for key in ('src', 'filename', 'file'):
                    if isinstance(v.get(key), str):
                        yield v, key


def probe(html, root):
    hit = find_json_block(html)
    if not hit:
        print('!! 未找到可解析的 application/json 数据块，需改用全局替换策略')
        return None
    m, data = hit
    print(f'资产数: {len(data)}')
    cats = {}
    for a in data:
        c = a.get('category', '?')
        cats[c] = cats.get(c, 0) + 1
    print('分类分布:', json.dumps(cats, ensure_ascii=False))
    if data:
        print('资产字段:', ','.join(data[0].keys()))
        vs = data[0].get('variants') or [{}]
        print('变体字段:', ','.join(vs[0].keys()))

    srcs, txts, others = [], set(), []
    for a in data:
        for v in a.get('variants', []) or []:
            if isinstance(v.get('src'), str):
                srcs.append(v['src'])
        if isinstance(a.get('txt'), str):
            txts.add(a['txt'])
    for a, key in iter_refs(data):
        val = a[key]
        if val.lower().endswith(IMG_EXT) and key != 'src' and key != 'filename':
            others.append(val)

    print(f'变体 src 总数: {len(srcs)}   去重后: {len(set(srcs))}')
    print(f'提示词 txt 引用: {len(txts)}')
    total_png = html.count('.png') + html.count('.PNG')
    print(f'全文 ".png" 出现次数: {total_png}   （src+filename 应为 {len(srcs) * 2}）')
    if total_png != len(srcs) * 2:
        print('   ! 计数不符 —— 提示词正文里可能含 .png 字样，必须走 JSON 字段改写，禁止全局替换')

    miss = []
    for s in srcs:
        p = os.path.join(root, unquote(s).replace('/', os.sep))
        if not os.path.exists(p):
            miss.append(unquote(s))
    print(f'图片缺失: {len(miss)}')
    for x in miss[:10]:
        print('   MISS', x)
    return m, data


def build(src_html, out_root, quality, max_w, method):
    root = os.path.dirname(os.path.abspath(src_html))
    html = open(src_html, encoding='utf-8').read()
    hit = find_json_block(html)
    if not hit:
        print('ERROR: 未找到 application/json 数据块')
        sys.exit(1)
    m, data = hit

    os.makedirs(out_root, exist_ok=True)

    # 1) 收集并转换图片
    tasks = sorted({unquote(v['src']) for a in data
                    for v in (a.get('variants') or [])
                    if isinstance(v.get('src'), str) and v['src'].lower().endswith(IMG_EXT)})
    print(f'待转换图片: {len(tasks)}')
    t0, tin, tout, fails = time.time(), 0, 0, []
    for i, rel in enumerate(tasks, 1):
        src = os.path.join(root, rel.replace('/', os.sep))
        dst = os.path.join(out_root, (os.path.splitext(rel)[0] + '.webp').replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            im = Image.open(src)
            if im.mode != 'RGB':
                im = im.convert('RGB')
            if im.width > max_w:
                im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
            im.save(dst, 'WEBP', quality=quality, method=method)
            tin += os.path.getsize(src)
            tout += os.path.getsize(dst)
        except Exception as e:                            # noqa: BLE001
            fails.append((rel, str(e)))
        if i % 40 == 0 or i == len(tasks):
            print(f'  [{i}/{len(tasks)}] {time.time()-t0:5.1f}s  out={tout/1048576:6.1f}MB', flush=True)
    print(f'转换完成: {tin/1048576:.1f}MB -> {tout/1048576:.1f}MB '
          f'({tout/tin*100 if tin else 0:.1f}%)  失败 {len(fails)}')
    for r, e in fails[:10]:
        print('  FAIL', r, e)

    # 2) 拷贝被引用的提示词文件
    copied, missing_txt = 0, []
    targets = {unquote(a['txt']) for a in data if isinstance(a.get('txt'), str)}
    for extra in ('交付说明.txt',):
        p = os.path.join(root, extra)
        if os.path.exists(p):
            targets.add(extra)
    for rel in sorted(targets):
        src = os.path.join(root, rel.replace('/', os.sep))
        if not os.path.exists(src):
            missing_txt.append(rel)
            continue
        dst = os.path.join(out_root, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    print(f'提示词拷贝: {copied}   缺失: {len(missing_txt)}')
    for x in missing_txt[:10]:
        print('  MISS TXT', x)

    # 3) 改写引用后缀
    n_img = n_txt = 0
    for a in data:
        for v in a.get('variants', []) or []:
            for key in ('src', 'filename'):
                val = v.get(key)
                if isinstance(val, str) and val.lower().endswith(IMG_EXT):
                    v[key] = os.path.splitext(val)[0] + '.webp'
                    n_img += 1
    print(f'改写引用: 图片 {n_img} 处, 提示词 {n_txt} 处')

    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    html = html[:m.start()] + m.group(1) + payload + m.group(3) + html[m.end():]

    # 4) 界面文案
    n = sum(1 for a in data for _ in (a.get('variants') or []))
    html = re.sub(r'本地离线预览[^<"]*', f'在线预览 · {n} 张图片 · 全部资产已交付', html)
    html = html.replace('px · PNG', 'px · WebP').replace('px · JPG', 'px · WebP')

    with open(os.path.join(out_root, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html)

    size = sum(os.path.getsize(os.path.join(r, x))
               for r, _, fs in os.walk(out_root) for x in fs)
    print(f'\n输出: {out_root}')
    print(f'  总大小 {size/1048576:.1f}MB   (原始 {tin/1048576:.1f}MB)')
    print('  下一步: python verify_site.py --root "' + out_root + '"')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src-html', required=True)
    ap.add_argument('--out')
    ap.add_argument('--probe', action='store_true')
    ap.add_argument('--quality', type=int, default=78)
    ap.add_argument('--max-width', type=int, default=2048)
    ap.add_argument('--method', type=int, default=5)
    a = ap.parse_args()

    root = os.path.dirname(os.path.abspath(a.src_html))
    html = open(a.src_html, encoding='utf-8').read()
    if a.probe:
        probe(html, root)
        return
    if not a.out:
        print('ERROR: 未指定 --out（或用 --probe 只体检）')
        sys.exit(1)
    build(a.src_html, a.out, a.quality, a.max_width, a.method)


if __name__ == '__main__':
    main()
