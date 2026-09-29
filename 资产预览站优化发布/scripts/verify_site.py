# -*- coding: utf-8 -*-
"""校验优化后的分享版站点：所有图片 / 提示词引用能否在磁盘上找到。

用法：
    python verify_site.py --root "E:\\...\\全资产预览_分享版"
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import unquote

JSON_BLOCK = re.compile(
    r'<script[^>]*id="assetData"[^>]*type="application/json"[^>]*>(.*?)</script>', re.S)
JSON_BLOCK_ANY = re.compile(
    r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', re.S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    idx = os.path.join(root, 'index.html')
    if not os.path.exists(idx):
        print('ERROR: index.html 不存在:', idx)
        sys.exit(1)
    html = open(idx, encoding='utf-8').read()

    m = JSON_BLOCK.search(html) or JSON_BLOCK_ANY.search(html)
    if not m:
        print('ERROR: 未找到 JSON 数据块')
        sys.exit(1)
    data = json.loads(m.group(1).replace('<\\/', '</'))

    ok_img, ok_txt = 0, 0
    miss_img, miss_txt = [], []
    n_variants = 0
    for a_ in data:
        for v in a_.get('variants', []) or []:
            n_variants += 1
            p = os.path.join(root, unquote(v['src']).replace('/', os.sep))
            if os.path.exists(p):
                ok_img += 1
            else:
                miss_img.append(unquote(v['src']))
        if a_.get('txt'):
            p = os.path.join(root, unquote(a_['txt']).replace('/', os.sep))
            if os.path.exists(p):
                ok_txt += 1
            else:
                miss_txt.append(unquote(a_['txt']))

    n_png = len(re.findall(r'\.png"', html, re.I))
    n_webp = len(re.findall(r'\.webp"', html, re.I))
    size = sum(os.path.getsize(os.path.join(r, x))
               for r, _, fs in os.walk(root) for x in fs)

    print(f'资产 {len(data)} 项 / 变体 {n_variants} 张')
    print(f'图片引用  {ok_img} 命中 / {len(miss_img)} 缺失')
    print(f'提示词    {ok_txt} 命中 / {len(miss_txt)} 缺失')
    print(f'残留 .png 引用 {n_png}    .webp 引用 {n_webp}   （webp 应为变体数×2）')
    print(f'目录总大小 {size/1048576:.1f}MB')

    bad = bool(miss_img or miss_txt or n_png or n_webp != n_variants * 2)
    for x in miss_img[:10]:
        print('  MISS IMG', x)
    for x in miss_txt[:10]:
        print('  MISS TXT', x)
    print('结果:', 'FAIL —— 需修复' if bad else 'PASS —— 可以发布')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
