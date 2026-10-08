#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pitch_check.py —— 五案提案校验（关卡 2 后必跑）

用途：确认「五案提案」是真的五案，而不是同一案换个说法。

检查项：
  1. 提案卡数量是否为 N（默认 5）
  2. 每案必须字段是否齐全（导演概念 / 镜头语法取向 / 节奏曲线 / 开场三镜 / 优势 /
     代价与风险 / 预估成本 / 选它的理由 / 不选它的理由）
  3. 代号是否重复、是否有画面感的名字（禁止「方案一」这类）
  4. 开场三镜样例是否为实数样例（含 Xs 秒数与至少 3 行），且五案首镜不重复
  5. 平均镜头时长是否有区分度（五案不能全是同一个秒数）
  6. 镜头语法取向关键词相似度（两两比对，过高判雷同）

用法：
  python pitch_check.py <提案文件.md> [--n 5] [--report 报告.md]

退出码：0 = PASS；1 = FAIL（禁止进入关卡 3）
"""

import argparse
import re
import sys
from itertools import combinations

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CARD_RE = re.compile(r"=====\s*提案卡\s*\[?([A-Za-z0-9一-龥]+)\]?\s*《?([^》\n]*)》?\s*=====")

REQUIRED_FIELDS = [
    "一句话导演概念",
    "镜头语法取向",
    "节奏曲线",
    "开场三镜样例",
    "对本片的优势",
    "代价与风险",
    "预估成本",
    "选它的理由",
    "不选它的理由",
]

# 互斥五轴：每轴两端，用于算「取向极性」（-1 / 0 / +1）
AXIS_POLARITY = {
    "节奏轴": (
        ["长镜", "滞缓", "缓慢", "缓推", "极少切换", "平均镜头时长 8", "平均镜头时长 9",
         "平均镜头时长 10", "平均镜头时长 12", "平均镜头时长 15", "长 withholds"],
        ["碎切", "快切", "密集", "跳切", "平均镜头时长 1", "平均镜头时长 2", "平均镜头时长 2.5"],
    ),
    "距离轴": (
        ["大远景", "远景", "环境为主", "空镜", "留白", "渺小", "全景"],
        ["特写", "近景", "微相", "微表情", "大特写", "局部插入"],
    ),
    "运动轴": (
        ["固定机位", "固定镜头", "机位不动", "三脚架"],
        ["手持", "跟拍", "斯坦尼康", "呼吸感", "环绕", "跟移"],
    ),
    "视角轴": (
        ["客观", "旁观", "第四面墙", "过肩", "正反打"],
        ["主观", "POV", "第一人称", "前景遮挡"],
    ),
    "形式轴": (
        ["写实", "自然", "生活流", "即兴", "纪实"],
        ["形式感", "对称", "高对比", "色块", "荷兰角", "黑色电影", "风格化"],
    ),
}

BAD_NAMES = ["方案一", "方案二", "方案三", "方案四", "方案五", "方案1", "方案2", "方案3"]


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def split_cards(text):
    matches = list(CARD_RE.finditer(text))
    cards = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        cards.append({
            "code": m.group(1),
            "name": m.group(2).strip(),
            "body": text[start:end],
        })
    return cards


def check_fields(card):
    missing = [f for f in REQUIRED_FIELDS if f not in card["body"]]
    return missing


def extract_opening_three(card):
    """返回开场三镜样例的行列表"""
    body = card["body"]
    idx = body.find("开场三镜样例")
    if idx < 0:
        return []
    # 取到下一个必填字段为止
    tail = body[idx:]
    for f in REQUIRED_FIELDS:
        if f == "开场三镜样例":
            continue
        p = tail.find(f)
        if p > 0:
            tail = tail[:p]
    lines = [l.strip() for l in tail.splitlines() if l.strip()]
    return [l for l in lines if re.match(r"^[-*]?\s*镜\s*\d", l)]


def extract_avg_duration(card):
    m = re.search(r"平均镜头时长[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)\s*(?:s|秒)", card["body"])
    if m:
        return float(m.group(1))
    m = re.search(r"镜头语法取向[\s\S]{0,200}?([0-9]+(?:\.[0-9]+)?)\s*(?:s|秒)", card["body"])
    return float(m.group(1)) if m else None


def axis_vector(card):
    """返回每轴的极性：-1 = 偏向 A 端点，+1 = 偏向 B 端点，0 = 未标注或两端都提到"""
    body = card["body"]
    vec = []
    for kws_a, kws_b in AXIS_POLARITY.values():
        ha = sum(1 for k in kws_a if k in body)
        hb = sum(1 for k in kws_b if k in body)
        if ha and not hb:
            vec.append(-1)
        elif hb and not ha:
            vec.append(1)
        else:
            vec.append(0)
    return vec


def polarity_similarity(a, b):
    """两案取向的相似度：在双方都有明确极性（非 0）的轴上，取值一致的比例。
    返回 (相似度, 可比轴数)。可比轴数过少说明标注不清，另作告警。"""
    pairs = [(x, y) for x, y in zip(a, b) if x != 0 and y != 0]
    if not pairs:
        return 0.0, 0
    same = sum(1 for x, y in pairs if x == y)
    return same / len(pairs), len(pairs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--n", type=int, default=5, help="期望提案数量，默认 5")
    ap.add_argument("--report", default=None, help="审查报告输出路径")
    ap.add_argument("--sim-threshold", type=float, default=0.75, help="取向相似度告警阈值")
    args = ap.parse_args()

    text = read_text(args.file)
    cards = split_cards(text)

    errors, warnings = [], []

    # 1 数量
    if len(cards) != args.n:
        errors.append(f"提案卡数量为 {len(cards)}，应为 {args.n}")

    if not cards:
        print("FAIL —— 未找到任何提案卡（格式应为 ===== 提案卡 [X] 《名字》 =====）")
        return 1

    codes = [c["code"] for c in cards]
    dup = {c for c in codes if codes.count(c) > 1}
    if dup:
        errors.append(f"提案代号重复：{sorted(dup)}")

    for c in cards:
        label = f"[{c['code']}]《{c['name']}》"

        # 2 字段完整
        missing = check_fields(c)
        if missing:
            errors.append(f"{label} 缺少字段：{'、'.join(missing)}")

        # 3 名字
        if not c["name"]:
            errors.append(f"{label} 缺少《》名称")
        elif any(bad in c["name"] for bad in BAD_NAMES) or re.match(r"^方案\s*[0-9一二三四五]", c["name"]):
            errors.append(f"{label} 名称无画面感（禁止「方案一」式命名）")

        # 4 开场三镜
        shots = extract_opening_three(c)
        if len(shots) < 3:
            errors.append(f"{label} 开场三镜样例不足 3 行（实得 {len(shots)}）")
        else:
            for s in shots:
                if not re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(s|秒)", s):
                    errors.append(f"{label} 开场样例缺秒数：{s[:24]}…")
                if not re.search(r"大远景|远景|全景|中景|中近景|近景|特写|大特写", s):
                    errors.append(f"{label} 开场样例缺景别：{s[:24]}…")

    # 5 平均镜头时长区分度
    durations = [extract_avg_duration(c) for c in cards]
    known = [d for d in durations if d is not None]
    if len(known) >= 2 and len(set(known)) == 1:
        errors.append(f"五案的「平均镜头时长」全部为 {known[0]}s，无区分度")
    elif known and max(known) - min(known) < 1.0:
        warnings.append(f"平均镜头时长区间过窄（{min(known)}s–{max(known)}s），五案节奏区分不明显")

    # 6 首镜重复
    firsts = []
    for c in cards:
        shots = extract_opening_three(c)
        firsts.append((f"[{c['code']}]", shots[0] if shots else ""))
    for (ca, sa), (cb, sb) in combinations(firsts, 2):
        if sa and sb and _rough_equal(sa, sb):
            errors.append(f"{ca} 与 {cb} 的开场首镜几乎相同，两案未拉开差异")
        elif sa and sb and share_size(sa, sb):
            size = size_of(sa)
            warnings.append(f"{ca} 与 {cb} 的开场首镜同为「{size}」，建议改换其中一案的开场")

    # 7 取向相似度（按五轴极性比对）
    vecs = [(f"[{c['code']}]", axis_vector(c)) for c in cards]
    for i, c in enumerate(cards):
        zeros = vecs[i][1].count(0)
        if zeros >= 5:
            errors.append(f"[{c['code']}] 的「镜头语法取向」五轴全部未标注，无法判断互斥性")
        elif zeros >= 4:
            warnings.append(
                f"[{c['code']}] 的「镜头语法取向」有 {zeros} 轴未标注端点，"
                f"建议补写以便在互斥五轴上定位"
            )
    for (la, va), (lb, vb) in combinations(vecs, 2):
        sim, n = polarity_similarity(va, vb)
        if n >= 3 and sim >= args.sim_threshold:
            errors.append(
                f"{la} 与 {lb} 在 {n} 条轴上的取向一致（相似度 {sim:.2f}），两案未互斥，必须重做其中一案"
            )
        elif n >= 2 and sim >= 1.0:
            warnings.append(f"{la} 与 {lb} 在 {n} 条轴上取向完全一致，请人工确认差异是否足够")

    # 输出
    lines = ["===== 五案提案审查报告 =====", f"文件：{args.file}", f"提案卡数量：{len(cards)} / 期望 {args.n}", ""]
    lines.append(f"错误 {len(errors)} 项 ｜ 告警 {len(warnings)} 项")
    if errors:
        lines.append("")
        lines.append("【错误 · 必须修复】")
        lines += [f"  ✗ {e}" for e in errors]
    if warnings:
        lines.append("")
        lines.append("【告警 · 建议修复】")
        lines += [f"  ! {w}" for w in warnings]
    verdict = "PASS —— 可进入关卡 3（等待用户选定）" if not errors else "FAIL —— 必须重做提案，不得进入关卡 3"
    lines += ["", f"结论：{verdict}"]
    report = "\n".join(lines)
    print(report)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report + "\n")

    return 0 if not errors else 1


def _norm(s):
    return re.sub(r"[\s（）()，,。.、：:—\-0-9.s秒]*", "", s)


def _rough_equal(a, b):
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # 计算字符重合度
    common = len(set(na) & set(nb))
    return common / max(1, min(len(set(na)), len(set(nb)))) >= 0.8


SIZE_RE = re.compile(r"大远景|远景|全景|中近景|中景|近景|大特写|特写")


def size_of(s):
    m = SIZE_RE.search(s)
    return m.group(0) if m else ""


def share_size(a, b):
    return bool(size_of(a) and size_of(a) == size_of(b))


if __name__ == "__main__":
    sys.exit(main())
