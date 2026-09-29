# -*- coding: utf-8 -*-
"""通用批量 OCR（本地 rapidocr，无需密钥）
用法:
  python ocr_batch.py <目录或文件> [更多...] [--pdf 文件.pdf] [--out 输出前缀]
输出: 当前目录下 <前缀>_ocr.txt 与控制台
"""
import os, sys, io
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

ocr = RapidOCR()
EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")


def ocr_pil(pil, max_side=2600):
    w, h = pil.size
    if max(h, w) > max_side:
        s = max_side / max(h, w)
        pil = pil.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    res, _ = ocr(np.array(pil.convert("RGB")))
    if not res:
        return []
    items = [{"y": float(min(p[1] for p in b)), "x": float(min(p[0] for p in b)),
              "t": t, "s": round(float(sc), 2)} for b, t, sc in res]
    items.sort(key=lambda d: (round(d["y"] / 16), d["x"]))
    return items


def collect(targets):
    files = []
    for t in targets:
        if os.path.isdir(t):
            for f in sorted(os.listdir(t)):
                if f.lower().endswith(EXTS):
                    files.append(os.path.join(t, f))
        elif os.path.isfile(t):
            files.append(t)
    return files


def main():
    args = sys.argv[1:]
    out_prefix = "ocr"
    pdfs, targets = [], []
    i = 0
    while i < len(args):
        if args[i] == "--out":
            out_prefix = args[i + 1]; i += 2
        elif args[i] == "--pdf":
            pdfs.append(args[i + 1]); i += 2
        else:
            targets.append(args[i]); i += 1

    results = {}
    for p in collect(targets):
        key = os.path.basename(os.path.dirname(p)) + "/" + os.path.basename(p)
        try:
            items = ocr_pil(Image.open(p))
            results[key] = items
            print(f"[OK] {key} -> {len(items)} blocks", flush=True)
        except Exception as e:
            results[key] = [{"err": str(e)}]
            print(f"[ERR] {key} {e}", flush=True)

    for pdf in pdfs:
        try:
            import pymupdf
            doc = pymupdf.open(pdf)
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=320 if i < 4 else 200)
                items = ocr_pil(Image.open(io.BytesIO(pix.tobytes("png"))))
                results[f"{os.path.basename(pdf)}/p{i+1}"] = items
                print(f"[OK] {pdf} p{i+1} -> {len(items)} blocks", flush=True)
        except Exception as e:
            print(f"[ERR] pdf {pdf} {e}", flush=True)

    with open(out_prefix + "_ocr.txt", "w", encoding="utf-8") as fh:
        for k, v in results.items():
            fh.write("=" * 80 + f"\n### {k}\n")
            for it in v:
                fh.write(it.get("t", it.get("err", "")) + "\n")
            fh.write("\n")
    print("DONE -> " + out_prefix + "_ocr.txt")


if __name__ == "__main__":
    main()
