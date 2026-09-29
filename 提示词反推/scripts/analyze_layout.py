# -*- coding: utf-8 -*-
"""白底分离 + 版式切分 + 分区取色（判定资产卡是三视图还是单主体）
用法: python analyze_layout.py <图片目录|图片文件> [...]
注意: cv2.imread 读不了中文路径，必须用 imdecode(np.fromfile(...))
"""
import os
import sys
import numpy as np
import cv2

SRC = sys.argv[1] if len(sys.argv) > 1 else "."

FILES = []
if os.path.isdir(SRC):
    for f in sorted(os.listdir(SRC)):
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")): FILES.append(os.path.join(SRC, f))
else:
    FILES = [SRC]

def cn(rgb):
    r, g, b = [int(v) for v in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    v = mx / 255.0; s = 0 if mx == 0 else (mx - mn) / mx
    if v < 0.13: return "近黑"
    if s < 0.12:
        if v > 0.90: return "纯白"
        if v > 0.68: return "浅灰白"
        if v > 0.40: return "中灰"
        return "深灰"
    if mx == r: h = (60 * ((g - b) / (mx - mn))) % 360
    elif mx == g: h = 60 * ((b - r) / (mx - mn)) + 120
    else: h = 60 * ((r - g) / (mx - mn)) + 240
    if h < 12 or h >= 345: return "正红" if s > 0.55 else ("暗红/酒红" if v < 0.55 else "粉红")
    if h < 26: return "橙红/朱红"
    if h < 42: return "金色" if (v > 0.62 and s > 0.4) else "橙/琥珀"
    if h < 62: return "明黄" if v > 0.7 else "土黄/黄棕"
    if h < 88: return "黄绿/橄榄"
    if h < 150: return "翠绿"
    if h < 195: return "青/青蓝"
    if h < 250: return "宝蓝"
    if h < 292: return "紫"
    return "品红"

def pal(pix, k=4):
    if len(pix) < 40: return []
    q = (pix // 20 * 20 + 10).astype(np.uint8)
    cnt = {}
    for row in q.reshape(-1, 3):
        key = (int(row[0]), int(row[1]), int(row[2])); cnt[key] = cnt.get(key, 0) + 1
    tot = sum(cnt.values())
    return [{"rgb": list(kk), "name": cn(kk), "pct": round(vv / tot * 100, 1)}
            for kk, vv in sorted(cnt.items(), key=lambda x: -x[1])[:k]]

BANDS = ["头顶/发", "面部", "颈肩", "胸甲", "胸口下", "腰腹", "胯/裙", "大腿", "小腿", "足/底"]

for f in FILES:
    p = os.path.join(SRC, f)
    img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
    if img is None: continue
    h0, w0 = img.shape[:2]
    sc = min(1.0, 1500 / max(h0, w0))
    if sc < 1: img = cv2.resize(img, (int(w0 * sc), int(h0 * sc)), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.int16)
    mn = rgb.min(axis=2); nw = float((mn > 236).mean())
    print("=" * 78)
    print(f"### {os.path.basename(p)}  {w0}x{h0}  近白像素占比 {nw*100:.1f}%")
    if nw < 0.20:
        # 场景图：3x3
        print("  → 判定为【场景/满幅图】(无纯白底)")
        for gy in range(3):
            row = []
            for gx in range(3):
                c = rgb[int(h*gy/3):int(h*(gy+1)/3), int(w*gx/3):int(w*(gx+1)/3)].reshape(-1, 3).mean(axis=0)
                row.append(f"{cn(c)}{tuple(int(v) for v in c)}")
            print("     " + " | ".join(row))
        print("  主色: " + " | ".join(f"{c['name']}{tuple(c['rgb'])} {c['pct']}%" for c in pal(rgb.reshape(-1, 3), 6)))
        continue
    mx = rgb.max(axis=2)
    mask = ((mn < 240) | ((mx - mn) > 16)).astype(np.uint8)
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k3, 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)), 2)
    # 列切分
    colsum = (mask > 0).sum(axis=0)
    active = colsum > max(2, int(h * 0.01))
    segs, start, gap = [], None, 0
    for x in range(w):
        if active[x]:
            if start is None: start = x
            gap = 0
        elif start is not None:
            gap += 1
            if gap > w * 0.02:
                segs.append((start, x - gap)); start = None; gap = 0
    if start is not None: segs.append((start, w - 1))
    segs = [s for s in segs if s[1] - s[0] > w * 0.02]
    print(f"  → 判定为【白底资产图】横切出 {len(segs)} 个子体")
    for i, (sx0, sx1) in enumerate(segs):
        sub = mask[:, sx0:sx1+1]
        rows = np.where(sub.sum(axis=1) > max(1, int((sx1-sx0)*0.01)))[0]
        if len(rows) < 5: continue
        y0, y1 = rows.min(), rows.max()
        bh, bw = y1-y0+1, sx1-sx0+1
        area = float(sub[y0:y1+1].mean())*100
        print(f"    子体{i+1}: x {sx0/w*100:.1f}%~{sx1/w*100:.1f}% (宽 {bw/w*100:.1f}%)  y {y0/h*100:.1f}%~{y1/h*100:.1f}% (高 {bh/h*100:.1f}%)  高/宽={bh/bw:.2f}  实心度 {area:.0f}%")
        for b in range(10):
            by0 = int(y0 + bh*b/10); by1 = max(by0+1, int(y0 + bh*(b+1)/10))
            px = rgb[by0:by1, sx0:sx1+1][mask[by0:by1, sx0:sx1+1] > 0]
            if len(px) < 40: continue
            print(f"       {BANDS[b]:>6}: " + " / ".join(f"{c['name']}{tuple(c['rgb'])} {c['pct']}%" for c in pal(px, 3)))
    print("  全图主色: " + " | ".join(f"{c['name']}{tuple(c['rgb'])} {c['pct']}%" for c in pal(rgb.reshape(-1, 3), 6)))
