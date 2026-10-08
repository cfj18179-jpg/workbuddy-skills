#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
segment_check.py —— 分镜时序切条校验 / 切条规划

背景：曾把「单条时长上限」误当成「目标段长」，把 1-1 场 26 秒硬拆成 13+13 两条，
      且切完后没做「相邻条合并检查」，凭空多出 3 条。

本脚本做两件事：
  A. 校验模式（默认）：读已写好的提示词/分镜文件，自动检查
     ① 是否有条超过单条上限
     ② 是否存在「同场次 + 合计≤上限」却未合并的相邻条（红）
     ③ 总时长是否与声明集时长一致
     ④ 条数是否明显多于理论下限（切条过碎告警）
  B. 规划模式（--plan）：按「镜号 时长 场次」清单，用贪心从上限倒推最优切条，
     并打印建议的合并/拆分方案。

用法：
  python segment_check.py --file 提示词.md [--limit 29] [--expected-total 120]
  python segment_check.py --plan shots.txt --limit 29

shots.txt 每行： 镜号 时长 场次      例：01 4 1-1
退出码：0 = 通过；1 = 有问题（超限 / 有可合并对 / 总时长不符）
"""

import argparse
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def read_text(path):
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


# ---------------------------------------------------------------- 解析

# 例：### 分镜时序1 ｜ 镜 01-08 ｜ 26s ｜ 1-1 拳场
SEG_RE = re.compile(
    r"分镜时序\s*(\d+)\s*[｜|]\s*镜\s*([0-9]{1,3})\s*[-‑–~至]\s*([0-9]{1,3})"
    r"\s*[｜|]\s*([0-9]+(?:\.[0-9]+)?)\s*s\s*[｜|]\s*(.+)"
)
SCENE_RE = re.compile(r"(\d+)\s*[-－]\s*(\d+)")


def parse_segments(text):
    segs = []
    for line in text.split("\n"):
        if "分镜时序" not in line:
            continue
        m = SEG_RE.search(line)
        if not m:
            continue
        no, s, e, dur, scene_field = m.groups()
        sm = SCENE_RE.search(scene_field)
        scene = f"{sm.group(1)}-{sm.group(2)}" if sm else scene_field.strip()
        segs.append({
            "no": int(no), "shot_from": int(s), "shot_to": int(e),
            "dur": float(dur), "scene": scene, "raw": line.strip(),
        })
    return segs


def parse_plan(path):
    shots = []
    for line in read_text(path).split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"[\s,，]+", line)
        if len(parts) < 3:
            continue
        try:
            shot, dur, scene = parts[0], float(parts[1]), parts[2]
        except ValueError:
            continue
        shots.append({"shot": shot, "dur": dur, "scene": scene})
    return shots


# ---------------------------------------------------------------- 核心

def merge_candidates(segs, limit):
    """返回 [(i, j, 合计时长)]：同场次且合计 ≤ 上限、却未合并的相邻条"""
    out = []
    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        if a["scene"] == b["scene"] and a["dur"] + b["dur"] <= limit:
            out.append((i, j := i + 1, a["dur"] + b["dur"]))
    return out


def plan(shots, limit):
    """贪心：同场次内尽量并到上限；跨场次必须断开"""
    out, cur = [], []
    for sh in shots:
        if cur and (sh["scene"] != cur[0]["scene"] or sum(x["dur"] for x in cur) + sh["dur"] > limit):
            out.append(cur)
            cur = []
        if cur and sum(x["dur"] for x in cur) + sh["dur"] > limit:  # 同场次但超限
            out.append(cur)
            cur = []
        cur.append(sh)
    if cur:
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser(description="分镜时序切条校验/规划")
    ap.add_argument("--file", help="受检的提示词/分镜文件")
    ap.add_argument("--plan", help="规划模式：镜号 时长 场次 清单文件")
    ap.add_argument("--limit", type=float, default=29.0, help="单条时长上限（秒），默认 29")
    ap.add_argument("--expected-total", type=float, default=None, help="声明的集时长，用于对账")
    ap.add_argument("--report", default=None, help="报告输出路径（.md）")
    args = ap.parse_args()

    R, problems = ["# 分镜时序切条校验报告", ""], []

    if args.plan:
        shots = parse_plan(args.plan)
        total = sum(s["dur"] for s in shots)
        groups = plan(shots, args.limit)
        R += [f"- 模式：规划（输入 `{args.plan}`）", f"- 上限：{args.limit:g}s", f"- 镜数：{len(shots)}｜总时长：{total:g}s",
              f"- 理论最少条数：{-(-total // args.limit):.0f}", ""]
        R += ["## 建议切条", "", "| 条 | 镜号 | 时长 | 场次 |", "|---|---|---|---|"]
        for k, g in enumerate(groups, 1):
            R.append(f"| {k} | 镜{g[0]['shot']}-{g[-1]['shot']} | {sum(x['dur'] for x in g):g}s | {g[0]['scene']} |")
        R.append("")
        print("\n".join(x for x in R if x is not None))
        if args.report:
            open(args.report, "w", encoding="utf-8").write("\n".join(R))
        sys.exit(0)

    if not args.file:
        ap.error("需要 --file 或 --plan")

    segs = parse_segments(read_text(args.file))
    if not segs:
        print("❌ 未在文件中解析到「分镜时序」标题行，无法校验。")
        print("   期望格式：### 分镜时序1 ｜ 镜 01-08 ｜ 26s ｜ 1-1 拳场")
        sys.exit(1)

    total = sum(s["dur"] for s in segs)
    lo = -(-total // args.limit)

    R += [f"- 受检：`{args.file}`", f"- 单条上限：{args.limit:g}s", f"- 条数：{len(segs)}｜合计：{total:g}s",
          f"- 理论最少条数：{lo:.0f}", ""]
    R += ["## 切条清单", "", "| 条 | 镜号 | 时长 | 场次 | 是否超限 |", "|---|---|---|---|---|"]
    for s in segs:
        over = "❌ 超限" if s["dur"] > args.limit else "✅"
        R.append(f"| {s['no']} | 镜{s['shot_from']:02d}-{s['shot_to']:02d} | {s['dur']:g}s | {s['scene']} | {over} |")
        if s["dur"] > args.limit:
            problems.append(f"条{s['no']}（镜{s['shot_from']:02d}-{s['shot_to']:02d}）时长 {s['dur']:g}s 超过上限 {args.limit:g}s")
    R.append("")

    cands = merge_candidates(segs, args.limit)
    R += ["## 相邻可合并检查（同场次 + 合计 ≤ 上限 → 必须合并）", ""]
    if cands:
        R += ["| 条 | 合计 | 处理 |", "|---|---|---|"]
        for i, j, t in cands:
            R.append(f"| 条{segs[i]['no']} + 条{segs[j]['no']} | {t:g}s | ❌ 应合并为一条 |")
            problems.append(f"条{segs[i]['no']}+条{segs[j]['no']} 同属 {segs[i]['scene']} 场、合计 {t:g}s ≤ 上限，应合并")
    else:
        R.append("✅ 无残余可合并对。")
    R.append("")

    if args.expected_total is not None:
        R += ["## 总时长对账", ""]
        if abs(total - args.expected_total) < 0.01:
            R.append(f"✅ 合计 {total:g}s = 声明 {args.expected_total:g}s")
        else:
            R.append(f"❌ 合计 {total:g}s ≠ 声明 {args.expected_total:g}s")
            problems.append(f"总时长 {total:g}s 与声明 {args.expected_total:g}s 不符")
        R.append("")

    if len(segs) >= lo + 2:
        R += ["## 切条过碎告警", "",
              f"⚠️ 条数 {len(segs)} ≥ 理论下限 {lo:.0f} + 2，切条可能过碎（除非场次/影调边界强制拆分），建议逐条复核。", ""]
    R += ["---", "", "**判定**：" + ("✅ 通过" if not problems else "❌ 不合格，必须回改"), ""]

    print("=" * 56)
    print("分镜时序切条校验")
    print("=" * 56)
    print(f"条数 {len(segs)}｜合计 {total:g}s｜单条上限 {args.limit:g}s｜理论下限 {lo:.0f} 条")
    print("\n".join("  " + s["raw"].replace("### ", "") for s in segs))
    print()
    if problems:
        print("❌ 问题清单：")
        for p in problems:
            print("  - " + p)
    else:
        print("✅ 通过：无超限、无残余可合并对"
              + (f"、总时长与声明一致" if args.expected_total is not None else ""))
    if len(segs) >= lo + 2:
        print(f"⚠️ 条数 {len(segs)} 偏多（下限 {lo:.0f}），请确认不是因为切条过碎")
    if args.report:
        open(args.report, "w", encoding="utf-8").write("\n".join(R))
        print(f"\n报告已写入：{args.report}")
    sys.exit(0 if not problems else 1)


if __name__ == "__main__":
    main()
