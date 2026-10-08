#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
storyboard_check.py —— 分镜表 / 提示词交付前审查（关卡 6 必跑）

检查项：
  1. 时间码合计 vs 目标时长（默认容差 ±5%）
  2. 镜数是否落在 时长÷3 ~ 时长÷4 区间
  3. 口型镜是否 ≤4s；单镜是否超过 --max-shot
  4. 提示词【SHOT NN】条数 vs 镜数是否一一对应
  5. 台词双指标（给了 --script 时）：
       指标 A：台词出现在产出全文
       指标 B：台词出现在「可执行代码块」正文内（只写核对表 = 违约，最严重）
  6. 禁空词扫描
  7. 光源缺失扫描（写了光的 genomes 但没有物理来源）
  8. 声音列为空提示

用法：
  python storyboard_check.py <分镜表.md> --duration 90 [--script 剧本.txt]
                             [--tolerance 0.05] [--max-shot 12] [--report 报告.md]

退出码：0 = PASS；1 = FAIL（禁止交付）
"""

import argparse
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

EMPTY_WORDS = [
    "唯美", "史诗感", "高级感", "有质感", "电影感", "氛围感", "视觉冲击力",
    "震撼人心", "美感拉满", "极致美学", "高级审美",
]

LIGHT_SOURCE = ["窗", "台灯", "霓虹", "篝火", "火焰", "月光", "日光",
                "夕阳", "阳光", "屏幕", "手电", "路灯", "烛", "反射光",
                "逆光", "侧光", "顶光", "散射光", "天光"]

LIGHT_VAGUE = ["氛围光", "柔和的光", "柔光", "布光", "打光"]

SHOT_HEAD = re.compile(r"【\s*SHOT\s*(\d+[A-Za-z]?)")


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- 分镜表解析

ROW_RE = re.compile(r"^\|\s*(\d{2}[A-Za-z]?)\s*\|(.+)\|\s*$")
TC_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–~]\s*(\d{1,2}):(\d{2})")
DUR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s|秒)")


def parse_rows(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        m = ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 8:
            continue
        rows.append({
            "shot": m.group(1),
            "time": cells[1],
            "dur": cells[2],
            "size": cells[3],
            "move": cells[4],
            "pic": cells[5],
            "dialog": cells[6],
            "sound": cells[7],
            "note": cells[8] if len(cells) > 8 else "",
        })
    return rows


def parse_seconds(s, default=None):
    m = DUR_RE.search(s or "")
    if m:
        return float(m.group(1))
    m = TC_RE.search(s or "")
    if m:
        a, b, c, d = (int(x) for x in m.groups())
        return max(0.0, (c * 60 + d) - (a * 60 + b))
    return default


# ---------------------------------------------------------------- 台词提取

DIALOG_LINE = re.compile(r"^\s*([\u4e00-\u9fa5A-Za-z0-9·\-_ ]{1,12})\s*[：:]\s*(.+)$")


def extract_script_dialogs(text, episode=None):
    """从剧本文本里抽出台词行"""
    dialogs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if len(line) > 200:
            continue
        m = DIALOG_LINE.match(line)
        if not m:
            continue
        role, content = m.group(1).strip(), m.group(2).strip()
        if not role or not content:
            continue
        # 排除明显的非台词字段
        if role in ("场景", "时间", "地点", "人物", "备注", "镜号", "场次") and len(content) < 20:
            continue
        content = content.strip('"“”「」『』')
        if len(content) < 2:
            continue
        dialogs.append((role, content))
    return dialogs


def extract_code_blocks(text):
    """提取 ``` 代码块正文"""
    blocks = []
    parts = re.split(r"^```[a-zA-Z]*\s*$", text, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        blocks.append(parts[i])
    return blocks


def norm(s):
    return re.sub(r"[\s，。、！？；：,\.!?;:\"'“”「」『』·…—\-]+", "", s)


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--duration", type=float, default=None, help="目标成片秒数")
    ap.add_argument("--script", default=None, help="剧本原文路径（用于台词双指标）")
    ap.add_argument("--tolerance", type=float, default=0.05, help="时长容差比例，默认 0.05")
    ap.add_argument("--max-shot", type=float, default=12.0, help="单镜时长上限（秒）")
    ap.add_argument("--lip-max", type=float, default=4.0, help="口型镜时长上限（秒）")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    text = read_text(args.file)
    rows = parse_rows(text)
    blocks = extract_code_blocks(text)
    block_text = "\n".join(blocks)

    errors, warnings, info = [], [], []

    if not rows:
        errors.append("未解析到任何分镜表行（表头需为 | 镜号 | 时间码 | 时长 | 景别 | 运镜 | 画面内容 | 台词 | 声音 | 备注 |）")

    # 1 时长合计
    durations = [(r["shot"], parse_seconds(r["dur"])) for r in rows]
    known = [(s, d) for s, d in durations if d]
    unknown = [s for s, d in durations if not d]
    if unknown:
        warnings.append(f"以下镜头无法解析时长：{'、'.join(unknown)}")
    total = sum(d for _, d in known)
    info.append(f"时长合计：{total:.0f}s（解析到 {len(known)} 个镜头）")
    if args.duration:
        diff = abs(total - args.duration) / args.duration
        if diff > args.tolerance:
            errors.append(
                f"时长合计 {total:.0f}s 与目标 {args.duration:.0f}s 偏差 {diff*100:.1f}%，"
                f"超过容差 {args.tolerance*100:.0f}%"
            )

        # 2 镜数区间
        low, high = args.duration / 4.0, args.duration / 3.0
        n = len(known)
        if n < low:
            warnings.append(f"镜数 {n} 低于建议区间 {low:.0f}–{high:.0f}（若为长镜流需在备注写明依据）")
        elif n > high:
            warnings.append(f"镜数 {n} 高于建议区间 {low:.0f}–{high:.0f}（若为碎切流请确认成本可接受）")
        else:
            info.append(f"镜数检查：{n} 落在建议区间 {low:.0f}–{high:.0f} 内")

    # 3 单镜上限 / 口型镜
    for shot, d in known:
        if d > args.max_shot:
            warnings.append(f"SHOT {shot} 时长 {d}s 超过单镜上限 {args.max_shot}s")
    for r in rows:
        d = parse_seconds(r["dur"])
        if d and "口型" in (r["dialog"] + r["note"]):
            if d > args.lip_max:
                errors.append(f"SHOT {r['shot']} 口型镜 {d}s 超过 {args.lip_max}s（必须拆条）")

    # 4 SHOT 条数对应
    shot_nums = [m.group(1) for m in SHOT_HEAD.finditer(text)]
    if not shot_nums and blocks:
        # 兼容 “镜 01” / “SHOT01” 写法
        shot_nums = re.findall(r"镜\s*(\d{2}[A-Za-z]?)", block_text)
    if rows and shot_nums:
        row_nums = {r["shot"] for r in rows}
        miss = sorted(row_nums - set(shot_nums))
        extra = sorted(set(shot_nums) - row_nums)
        if miss:
            errors.append(f"以下镜号在可执行代码块里没有对应提示词：{'、'.join(miss)}")
        if extra:
            warnings.append(f"代码块里存在分镜表中没有的镜号：{'、'.join(extra)}")
        if not miss and not extra:
            info.append(f"提示词条数 {len(shot_nums)} 与镜数 {len(row_nums)} 一一对应")
    elif rows:
        errors.append("未在产出中找到可执行代码块（``` 包裹的 SHOT 提示词）——台词必须写在代码块正文内")

    # 5 台词双指标
    if args.script:
        script = read_text(args.script)
        dialogs = extract_script_dialogs(script)
        if not dialogs:
            warnings.append("剧本中未提取到台词行，跳过台词双指标检查")
        else:
            full_norm, block_norm = norm(text), norm(block_text)
            missing_a, missing_b = [], []
            for role, content in dialogs:
                nc = norm(content)
                if not nc:
                    continue
                probe = nc[: min(12, len(nc))]
                if probe not in full_norm:
                    missing_a.append(f"{role}：「{content[:20]}」")
                if probe not in block_norm:
                    missing_b.append(f"{role}：「{content[:20]}」")
            info.append(f"剧本台词 {len(dialogs)} 条")
            if missing_a:
                errors.append(f"指标 A 未过（全文缺失台词 {len(missing_a)} 条）：{'；'.join(missing_a[:5])}")
            else:
                info.append("指标 A：全部台词出现在产出全文 ✅")
            if missing_b:
                errors.append(
                    f"指标 B 未过（代码块缺失台词 {len(missing_b)} 条 —— 只写核对表＝台词全丢，最严重）："
                    f"{'；'.join(missing_b[:5])}"
                )
            else:
                info.append("指标 B：全部台词出现在可执行代码块正文 ✅")

    # 6 禁空词
    hits = []
    for w in EMPTY_WORDS:
        for i, line in enumerate(text.splitlines(), 1):
            if w in line:
                hits.append(f"第 {i} 行：{w}")
    if hits:
        errors.append(f"空词扫描命中 {len(hits)} 处（须替换为可拍摄的具体描述）：{'；'.join(hits[:5])}")
    else:
        info.append("空词扫描：0 处")

    # 7 光源缺失
    vague = []
    for i, line in enumerate(text.splitlines(), 1):
        for v in LIGHT_VAGUE:
            if v in line:
                vague.append(f"第 {i} 行：{v}")
    if vague:
        errors.append(f"无源光描述 {len(vague)} 处（须写明光源类型与方位）：{'；'.join(vague[:5])}")
    else:
        info.append("光源检查：未发现无来源光")

    # 8 声音列为空
    silent = [r["shot"] for r in rows if r["sound"] in ("", "—", "-")]
    if silent:
        warnings.append(f"以下镜头声音列为空：{'、'.join(silent[:10])}{'…' if len(silent) > 10 else ''}")

    # 输出
    lines = ["===== 分镜表交付审查报告 =====", f"文件：{args.file}",
             f"目标时长：{args.duration if args.duration else '未指定'}s", ""]
    lines.append("【通过项】")
    lines += [f"  ✓ {i}" for i in info] or ["  （无）"]
    if warnings:
        lines.append("")
        lines.append("【告警 · 建议修复】")
        lines += [f"  ! {w}" for w in warnings]
    if errors:
        lines.append("")
        lines.append("【错误 · 必须修复】")
        lines += [f"  ✗ {e}" for e in errors]
    verdict = "PASS —— 可交付" if not errors else "FAIL —— 禁止交付，回改后重跑"
    lines += ["", f"错误 {len(errors)} 项 ｜ 告警 {len(warnings)} 项", f"结论：{verdict}"]
    report = "\n".join(lines)
    print(report)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report + "\n")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
