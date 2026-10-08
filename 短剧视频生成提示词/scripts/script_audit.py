#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
script_audit.py —— 剧本一致性审查（Script Consistency Audit）v2

用途：任何提示词 / 分镜产出（.md/.txt/.docx）交付前，必须对剧本原文做逐句比对，
      禁止出现「与剧本不符合」或「删掉剧本内容」的情况。

【双硬性指标】
  指标 A（全文）：剧本内容必须出现在产出文件里         —— 防整体丢失
  指标 B（可执行块）：剧本内容必须出现在「分镜时序代码块」正文里
                     —— 防「只写进文末附录核对表、真正粘贴给模型的那段没写」
     产出文件里没有代码块时，指标 B 自动退化为指标 A 并注明。

【三类比对对象】
  1) 台词行（角色：内容）——硬性，A/B 双达标才合格
  2) 画面内文字 / 字幕 / 标记（【…】）——硬性
  3) ▲ 动作行——辅助扫描（最长公共子串比例，低覆盖仅告警，需人工确认）

用法：
  python script_audit.py --script 剧本.txt --output 提示词.md [--output 分镜表.md]
                         [--episode 1] [--report 审查报告.md] [--threshold 0.5]

退出码：0 = 通过（无缺失、无改写）；1 = 不合格（禁止交付，必须回改）
"""

import argparse
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------- 读取

def read_text(path):
    if path.lower().endswith(".docx"):
        import zipfile
        z = zipfile.ZipFile(path)
        xml = z.read("word/document.xml").decode("utf-8")
        paras = re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, re.S)
        return "\n".join("".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S)) for p in paras)
    for enc in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


# ---------------------------------------------------------------- 归一化

def norm(s):
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u2014", "-").replace("\u2013", "-").replace("\uff0d", "-")
    s = s.replace("\u3000", "")
    return re.sub(r"\s+", "", s)


# ---------------------------------------------------------------- 剧本切片

EP_RE = re.compile(r"^第\s*([0-9０-９一二三四五六七八九十百]+)\s*集\s*$")


def cn2num(s):
    s = s.strip()
    if s.isdigit():
        return int(s)
    mp = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if s in mp:
        return mp[s]
    if s.startswith("十"):
        return 10 + mp.get(s[1:], 0)
    if len(s) == 2 and s[0] in mp and s[1] in mp:
        return mp[s[0]] * 10 + mp[s[1]]
    return None


def slice_episode(text, episode):
    """切片但保留原始行号（范围外的行置空），保证报告里的「剧本行号」可直接对回原文。"""
    lines = text.split("\n")
    starts = [(i, cn2num(m.group(1))) for i, ln in enumerate(lines)
              if (m := EP_RE.match(ln.strip()))]
    if not starts:
        return text
    if episode is None:
        start, end = starts[0][0], len(lines)
    else:
        start = end = None
        for idx, (i, n) in enumerate(starts):
            if n == episode:
                start = i
                end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
                break
        if start is None:
            return ""
    out = [""] * len(lines)
    for k in range(start, end):
        out[k] = lines[k]
    return "\n".join(out)


# ---------------------------------------------------------------- 剧本提取

SPEAKER_RE = re.compile(
    r"^([A-Za-z\u4e00-\u9fa5][A-Za-z0-9\u4e00-\u9fa5（）()\u3001\s]{0,15}?)[：:]\s*(.+)$"
)
SKIP_SPEAKER = ("出场人物", "核心梗", "人物小传", "时间", "地点", "备注", "说明", "角色",
                "CUT", "FADE", "DISSOLVE", "转场", "切")


def extract(script_text):
    """-> dialogues[(lineno, speaker, content)], inserts[(lineno, inner)], actions[(lineno, text)]"""
    dialogues, inserts, actions = [], [], []
    for i, raw in enumerate(script_text.split("\n"), start=1):
        ln = raw.strip()
        if not ln:
            continue

        if ln.startswith("▲"):
            body = re.sub(r"^[▲\s]+", "", ln)
            if body:
                actions.append((i, body))
            for m in re.finditer(r"【([^】]+)】", body):
                inserts.append((i, m.group(1)))
            continue

        if re.match(r"^\d+\s*[-－]\s*\d+", ln) or ln.startswith("#") or ln.startswith(">"):
            continue
        if EP_RE.match(ln):          # 「第N集」集标题行
            continue

        for m in re.finditer(r"【([^】]+)】", ln):
            inserts.append((i, m.group(1)))
        stripped = re.sub(r"【[^】]*】", "", ln).strip()
        if not stripped:
            continue

        m = SPEAKER_RE.match(stripped)
        if m:
            sp, content = m.group(1).strip(), m.group(2).strip()
            if sp in SKIP_SPEAKER or len(sp) > 12 or not content:
                continue
            dialogues.append((i, sp, content))
            continue

        if len(ln) >= 2:
            actions.append((i, ln))

    return dialogues, inserts, actions


# ---------------------------------------------------------------- 匹配

def hit(hay, needle):
    n = norm(needle)
    return bool(n) and n in hay


def partial(hay, needle, win=10):
    n = norm(needle)
    if len(n) <= win:
        return False
    return any(n[i:i + win] in hay for i in range(len(n) - win))


def lcs_ratio(line, hay):
    """最长公共子串占该行长度比例（二分查找窗口长度）"""
    n = norm(line)
    if not n:
        return 1.0
    lo, hi, best = 3, len(n), 3
    if not any(n[i:i + 3] in hay for i in range(max(1, len(n) - 2))):
        return 0.0
    while lo <= hi:
        mid = (lo + hi) // 2
        found = any(n[i:i + mid] in hay for i in range(len(n) - mid + 1))
        if found:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best / len(n)


def haystacks(paths):
    """返回 [(path, full_text, block_text, has_blocks)]"""
    res = []
    for p in paths:
        if not os.path.exists(p):
            res.append((p, "", "", False))
            continue
        raw = read_text(p)
        blocks = re.findall(r"```[a-zA-Z]*\n(.*?)```", raw, re.S)
        has = len(blocks) > 0
        res.append((p, norm(raw), norm("\n".join(blocks)) if has else norm(raw), has))
    return res


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="剧本一致性审查 v2")
    ap.add_argument("--script", required=True, help="剧本原文（.txt/.docx）")
    ap.add_argument("--output", required=True, action="append", help="受审产出文件，可多次")
    ap.add_argument("--episode", default=None, help="只审第 N 集")
    ap.add_argument("--report", default=None, help="审查报告输出路径（.md）")
    ap.add_argument("--threshold", type=float, default=0.5, help="▲动作行覆盖告警阈值")
    args = ap.parse_args()

    script_text = slice_episode(read_text(args.script),
                                cn2num(args.episode) if args.episode else None)
    dialogues, inserts, actions = extract(script_text)
    hs = haystacks(args.output)
    any_blocks = any(h[3] for h in hs)

    R = ["# 剧本一致性审查报告（双指标）", "",
         f"- 剧本：`{args.script}`",
         f"- 范围：{('第 %s 集' % args.episode) if args.episode else '全文（自第一个集标题起）'}",
         f"- 受审产出：{'、'.join('`%s`' % p for p in args.output)}",
         f"- 可执行块检测：{'已启用（以代码块正文为准）' if any_blocks else '未检出代码块 → 指标 B 退化为全文'}",
         ""]

    # 1) 台词
    d_miss_full, d_miss_block, d_partial, d_ok = [], [], [], []
    for (i, sp, c) in dialogues:
        in_full = any(hit(h[1], c) for h in hs)
        in_block = any(hit(h[2], c) for h in hs)
        if not any_blocks:
            in_block = in_full
        if in_full and in_block:
            d_ok.append((i, sp, c))
        elif not in_full and not any(partial(h[1], c) for h in hs):
            d_miss_full.append((i, sp, c))
        elif not in_full:
            d_partial.append((i, sp, c))
        else:  # 全文有、可执行块没有 —— 正是本次事故的类型
            d_miss_block.append((i, sp, c))

    # 2) 画面内文字 / 字幕
    i_miss, i_ok, seen = [], [], set()
    for (i, inner) in inserts:
        if norm(inner) in seen or not norm(inner):
            continue
        seen.add(norm(inner))
        core = re.sub(r"^(字幕|画面|文字|闪前)\s*[：:]", "", inner).strip() or inner
        cands = [core] + [core.split("：")[-1], core.split(":")[-1]]
        if any(hit(h[2], c) for h in hs for c in cands if c):
            i_ok.append((i, inner))
        else:
            i_miss.append((i, inner))

    # 3) ▲ 动作行（辅助）
    a_rows = []
    for (i, text) in actions:
        best = max((lcs_ratio(text, h[2]) for h in hs), default=0.0)
        a_rows.append((i, text, best))
    low = [r for r in a_rows if r[2] < args.threshold]

    total = len(dialogues)
    cover = 100.0 * len(d_ok) / total if total else 100.0
    ok = not (d_miss_full or d_miss_block or d_partial or i_miss)

    R += ["## 一、总览", "",
          "| 类别 | 条目 | 合格 | 仅全文有/块内缺 | 全文也缺 | 疑似改写 | 判定 |", "|---|---|---|---|---|---|---|",
          f"| 台词（双指标硬性） | {total} | {len(d_ok)} | {len(d_miss_block)} | {len(d_miss_full)} | {len(d_partial)} | "
          f"{'✅ 通过' if (not d_miss_full and not d_miss_block and not d_partial) else '❌ 不合格'}（合计覆盖率 {cover:.1f}%） |",
          f"| 画面文字/字幕（硬性） | {len(i_ok)+len(i_miss)} | {len(i_ok)} | — | {len(i_miss)} | — | "
          f"{'✅ 通过' if not i_miss else '❌ 不合格'} |",
          f"| ▲ 动作行（辅助） | {len(a_rows)} | {len(a_rows)-len(low)} | — | — | {len(low)}（低覆盖） | "
          f"{'✅ 无明显缺口' if not low else '⚠️ 需人工复核 ' + str(len(low)) + ' 条'} |", ""]

    def sec(title, rows, fmt):
        R.append(f"## {title}")
        R.append("")
        if not rows:
            R.append("（无）")
            R.append("")
            return
        R.append("| 剧本行号 | " + fmt[0] + " |")
        R.append("|---|---|")
        for r in rows:
            R.append("| " + " | ".join(fmt[1](r)) + " |")
        R.append("")

    esc = lambda s: s.replace("|", "\\|")
    sec("二、【最严重】可执行块内缺失——文末附录有、粘贴给模型的正文没有（禁止项，必须回改）",
        d_miss_block, ("台词", lambda r: [str(r[0]), f"{r[1]}：{esc(r[2])}"]))
    sec("三、全文亦缺失——剧本内容在产出中完全找不到（禁止项，必须回改）",
        d_miss_full, ("台词", lambda r: [str(r[0]), f"{r[1]}：{esc(r[2])}"]))
    sec("四、疑似改写——须交付原版+优化版两版并由用户书面确认",
        d_partial, ("台词", lambda r: [str(r[0]), f"{r[1]}：{esc(r[2])}"]))
    sec("五、画面内文字 / 字幕缺失（禁止项）",
        i_miss, ("原文", lambda r: [str(r[0]), esc(r[1])]))
    sec(f"六、▲ 动作行覆盖（辅助扫描，LCS 比例 < {args.threshold*100:.0f}% 需人工确认，允许同义改写但不许丢事件）",
        sorted(low, key=lambda x: x[2]), ("动作行", lambda r: [str(r[0]), f"{esc(r[1])}（{r[2]*100:.0f}%）"]))

    R += ["---", "",
          "**判定规则**：台词与画面内文字/字幕为**双指标硬性 100%**——既要出现在产出文件里，",
          "**更要出现在会被粘贴进模型的「分镜时序」代码块正文里**；缺失或改写即不合格，必须回改，禁止交付。", ""]

    report = "\n".join(R)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)

    print("=" * 60)
    print("剧本一致性审查 · 摘要（双指标）")
    print("=" * 60)
    print(f"台词：合格 {len(d_ok)}/{total} | 仅全文有·块内缺 {len(d_miss_block)} | 全文也缺 {len(d_miss_full)} | 疑似改写 {len(d_partial)}")
    print(f"画面文字/字幕：{len(i_ok)}/{len(i_ok)+len(i_miss)} 合格 | 缺失 {len(i_miss)}")
    print(f"▲ 动作行：{len(a_rows)-len(low)}/{len(a_rows)} 达标（阈值 {args.threshold*100:.0f}%）")
    if d_miss_block:
        print("\n[❗可执行块内缺失（最严重）]")
        for (i, sp, c) in d_miss_block:
            print(f"  行{i} {sp}：{c}")
    if d_miss_full:
        print("\n[❗全文亦缺失]")
        for (i, sp, c) in d_miss_full:
            print(f"  行{i} {sp}：{c}")
    if d_partial:
        print("\n[⚠️ 疑似改写]")
        for (i, sp, c) in d_partial:
            print(f"  行{i} {sp}：{c}")
    if i_miss:
        print("\n[❗画面文字/字幕缺失]")
        for (i, c) in i_miss:
            print(f"  行{i}：{c}")
    if low:
        print(f"\n[▲ 低覆盖 {len(low)} 条，人工确认]")
        for (i, t, r) in sorted(low, key=lambda x: x[2])[:15]:
            print(f"  行{i}（{r*100:.0f}%）：{t[:38]}")
    print("\n判定：" + ("✅ 通过（可交付）" if ok else "❌ 不合格（禁止交付，必须回改）"))
    if args.report:
        print(f"报告已写入：{args.report}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
