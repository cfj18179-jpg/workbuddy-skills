#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 每日积分领取脚本（签到 + 派猫猫旅行闭环）
仅用 Python 标准库，零第三方依赖。跨平台：Windows / macOS / Linux。

用法：
  python daily_points.py                 # 完整闭环：签到 + 旅行（先领后派）
  python daily_points.py --no-travel     # 只签到
  python daily_points.py --check-only    # 只查状态（只读，不领取）
  python daily_points.py --travel-only   # 只跑旅行闭环（不签到）
  python daily_points.py --location N    # 指定派遣地点 1-4（缺省随机）
  python daily_points.py --diagnose      # 环境自检（只读）
  python daily_points.py --version

输出：单行 JSON。退出码：成功 0 / 失败 1。
安全：只读登录态文件；任何输出均不包含真实 token（已脱敏）。
"""

import glob
import json
import os
import random
import ssl
import sys
import time
import urllib.error
import urllib.request

__version__ = "1.4.0"

TRAVEL_DOMAIN = "www.workbuddy.cn"  # 旅行接口专用域名（与签到域名不同，路径无 /v2 前缀）
LOCATIONS = {1: "咖啡馆", 2: "商场店铺", 3: "健身房", 4: "古镇客栈"}

# 登录态文件探测路径（按优先级：固定候选 → 目录扫描补漏）
AUTH_TAIL = os.path.join("Data", "Public", "auth", "workbuddy-desktop.info")

# macOS / Linux 上客户端 userData 目录名未必是 CodeBuddyExtension（Electron 取 app name），
# 因此在候选根目录下再通配扫一层补漏；有界（最多补 5 条），避免拖慢启动。
SCAN_ROOTS = {
    "darwin": [os.path.join("Library", "Application Support")],
    "linux": [".config"],
}


def _discover(home):
    extra = []
    for root in SCAN_ROOTS.get(sys.platform, []):
        try:
            for hit in sorted(glob.glob(os.path.join(home, root, "*", AUTH_TAIL))):
                if hit not in extra:
                    extra.append(hit)
        except Exception:
            pass
    return extra[:5]


def auth_candidates():
    home = os.path.expanduser("~")
    rel = os.path.join("CodeBuddyExtension", AUTH_TAIL)
    paths = []
    local = os.environ.get("LOCALAPPDATA")
    appdata = os.environ.get("APPDATA")
    if local:
        paths.append(os.path.join(local, rel))
    if appdata:
        paths.append(os.path.join(appdata, rel))
    paths.append(os.path.join(home, "Library", "Application Support", rel))  # macOS
    paths.append(os.path.join(home, ".config", rel))                          # Linux
    paths.append(os.path.join(home, ".workbuddy", "auth", "workbuddy-desktop.info"))  # 兜底
    for p in _discover(home):
        if p not in paths:
            paths.append(p)
    return paths


def _certifi_bundle():
    """能拿到 certifi 的 CA 包路径就返回，否则 None（保持零依赖，仅作兜底）。"""
    try:
        import certifi
        return certifi.where()
    except Exception:
        return None


def _ssl_context():
    """优先 certifi 的 CA 包（macOS 上 CERTIFICATE_VERIFY_FAILED 的主要兜底），否则用系统默认。"""
    bundle = _certifi_bundle()
    if bundle:
        try:
            return ssl.create_default_context(cafile=bundle)
        except Exception:
            pass
    return ssl.create_default_context()


def mask_token(tok):
    if isinstance(tok, dict):
        return "(encrypted field: %s)" % ("$wbEncrypted envelope" if tok.get("$wbEncrypted") else "unknown")
    if not tok or len(tok) < 16:
        return "(missing)"
    return tok[:10] + "..." + tok[-4:]


ENCRYPTED_HINT = (
    "登录态文件中的 accessToken 已改为客户端加密存储（{$wbEncrypted:1, envelope} 信封格式），"
    "脚本无法读取明文 token。请在 WorkBuddy 客户端「Buddy 加油站」手动签到，"
    "或等待本技能适配新的加密格式后重试。"
)


def resolve_token(auth):
    """从 auth 节点取出可用 token。返回 (token, err_str)；err 非空表示不可用。"""
    if not isinstance(auth, dict):
        return None, "登录态缺少 auth 节点，请打开 WorkBuddy 客户端重新登录"
    tok = auth.get("accessToken")
    if isinstance(tok, dict):
        if tok.get("$wbEncrypted"):
            return None, ENCRYPTED_HINT
        return None, "accessToken 为未知的对象结构，无法读取，请更新本技能"
    if not isinstance(tok, str) or not tok:
        return None, "登录态缺失，请打开 WorkBuddy 客户端重新登录"
    return tok, None


def load_auth():
    """返回 (info_dict, path) 或 (None, None)。只读，绝不修改。"""
    for p in auth_candidates():
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    info = json.load(f)
                return info, p
            except Exception as e:
                return None, "%s (parse error: %s)" % (p, e)
    return None, None


def scan_snapshots(main_path):
    """列出主登录态同目录下的历史快照 workbuddy-desktop.<ts>.<pid>.<uuid>.info。
    返回 [(path, info_dict), ...]，按修改时间倒序。只读。"""
    if not main_path:
        return []
    d = os.path.dirname(main_path)
    out = []
    try:
        for f in sorted(glob.glob(os.path.join(glob.escape(d), "workbuddy-desktop.*.info")),
                        key=os.path.getmtime, reverse=True):
            if os.path.basename(f) == os.path.basename(main_path):
                continue
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    out.append((f, json.load(fh)))
            except Exception:
                continue
    except Exception:
        pass
    return out


def _uin(info):
    return str(((info or {}).get("account") or {}).get("uin") or "")


def _uid(info):
    return str(((info or {}).get("account") or {}).get("uid") or "")


def _identity(info):
    """账号标识集合（uid 优先，其次 uin），用于跨凭据文件比对是否同一账号。"""
    return {x for x in (_uid(info), _uin(info)) if x}


def scan_ide_credentials(main_path):
    """列出同目录下 IDE 扩展写入的凭据文件（如 Tencent-Cloud.coding-copilot.info）。
    这类文件由 IDE 客户端以【明文】写入，可作为加密主文件的替代凭据源。
    返回 [(path, info_dict), ...]，按修改时间倒序。只读。"""
    dirs = []
    if main_path:
        dirs.append(os.path.dirname(main_path))
    for p in auth_candidates():
        d = os.path.dirname(p)
        if d not in dirs:
            dirs.append(d)
    out, seen = [], set()
    for d in dirs:
        try:
            hits = glob.glob(os.path.join(glob.escape(d), "*coding-copilot*.info"))
        except Exception:
            continue
        for f in sorted(hits, key=os.path.getmtime, reverse=True):
            if f in seen:
                continue
            seen.add(f)
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    out.append((f, json.load(fh)))
            except Exception:
                continue
    return out


IDE_HINT = (
    "主登录态（workbuddy-desktop.info）的 accessToken 已加密，本次改用同账号下由 IDE 扩展写入的"
    "明文凭据文件（*-coding-copilot.info）。仅用于调用官方签到接口，账号一致、不跨账号混用。"
)

STALE_HINT = (
    "主登录态的 accessToken 已加密；本次改用同目录下【同账号且未过期】的明文历史快照。"
    "该凭据属过期快照，仅作过渡，客户端重新登录后请以主文件为准。"
)

NO_PLAINTEXT_HINT = (
    "accessToken 已加密，且本机没有可用的替代明文凭据（IDE 扩展凭据文件 / 明文历史快照），无法自动领取。"
    "原因：新版客户端把 accessToken 以 AES-GCM 信封加密，而解密用的静态密钥（at-rest key）不落盘，"
    "只在客户端运行时经 IPC 下发给它自己的子进程，第三方脚本按设计无法解密——这是客户端的凭据保护机制，"
    "不是登录过期，也不是网络问题。"
    "可行做法：① 在客户端「Buddy 加油站」手动签到（最省事）；"
    "② 在该机器上用 WorkBuddy 的 IDE 扩展（VS Code / Cursor 插件）登录同一账号——"
    "扩展写入的 *-coding-copilot.info 是明文，本脚本会自动识别并复用；"
    "③ 在仍有明文凭据的设备上运行本技能。"
)


def resolve_token_with_fallback(info, main_path):
    """按优先级取 token：① 主文件明文 → ② IDE 扩展的明文凭据（同账号、未过期）
    → ③ 同目录明文历史快照（同账号、未过期）。
    返回 (token, err, source)；source ∈ {'main', 'ide-credential:<文件名>', 'snapshot:<文件名>', None}。"""
    auth = (info or {}).get("auth") or {}
    tok, err = resolve_token(auth)
    if tok:
        return tok, None, "main"
    if err and err != ENCRYPTED_HINT:
        return None, err, None  # 真正的错误（缺 auth / token 为空）直接报

    main_ids = _identity(info)

    # ① IDE 扩展写入的明文凭据：会随 IDE 登录自动刷新，时效性优于历史快照，故优先
    for path, iinfo in scan_ide_credentials(main_path):
        iauth = iinfo.get("auth") or {}
        itok, _ = resolve_token(iauth)
        if not itok or token_expired(iauth):
            continue
        cand_ids = _identity(iinfo)
        if main_ids and cand_ids and not (main_ids & cand_ids):
            continue  # 账号不一致，绝不混用
        return itok, None, "ide-credential:%s" % os.path.basename(path)

    # ② 同目录明文历史快照（旧版客户端遗留）
    main_uin = _uin(info)
    for path, sinfo in scan_snapshots(main_path):
        sauth = sinfo.get("auth") or {}
        stok, _ = resolve_token(sauth)
        if not stok or token_expired(sauth):
            continue
        suin = _uin(sinfo)
        if main_uin and suin and suin != main_uin:
            continue  # 账号不一致，绝不混用
        return stok, None, "snapshot:%s" % os.path.basename(path)

    # 加密信封 + 无任何可用明文凭据 → 给出可操作的原因说明
    return None, NO_PLAINTEXT_HINT, None


def token_expired(auth):
    exp = auth.get("expiresAt")
    if not exp:
        return False
    try:
        exp = float(exp)
        if exp > 1e12:  # 13 位毫秒
            exp = exp / 1000.0
        return exp < time.time()
    except Exception:
        return False


def http_json(url, token, method="GET", body=None, timeout=20):
    """发起请求并解析 JSON。非 2xx 也尽力解析响应体。返回 (http_status, payload_dict_or_None, err_str)。"""
    data = None
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw else None), None
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "replace")
            return e.code, (json.loads(raw) if raw else None), None
        except Exception:
            return e.code, None, "HTTP %d" % e.code
    except Exception as e:
        return None, None, str(e)


def extract_balance(data):
    """从多层结构里尽力提取积分余额字段。"""
    candidates = ["total_credit", "total_credit_balance", "total_points", "points_balance",
                  "credit_balance", "balance", "remain_credit", "score", "integral",
                  "totalCredit", "pointsBalance", "balanceCredit"]
    layers = [data, data.get("data") if isinstance(data, dict) else None]
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        for key in candidates:
            if key in layer and isinstance(layer[key], (int, float)):
                return layer[key]
        sub = layer.get("result")
        if isinstance(sub, dict):
            for key in candidates:
                if key in sub and isinstance(sub[key], (int, float)):
                    return sub[key]
    return None


def do_checkin(token, domain, check_only=False):
    """签到主流程。返回结果 dict。"""
    r = {"action": "unknown", "credit": None, "streak_days": None, "balance": None}
    status, payload, err = http_json(
        "https://%s/v2/billing/meter/checkin-activity-status" % domain, token, method="POST", body={})
    r["status_http"] = status
    if err:
        r["action"] = "error"
        r["error"] = "状态查询失败: %s" % err
        return r
    data = (payload or {}).get("data") or {}
    r["balance"] = extract_balance(payload or {})
    r["today_signed"] = bool(data.get("today_checked_in"))
    r["streak_days"] = data.get("streak_days")

    if check_only:
        r["action"] = "checked_only"
        return r
    if r["today_signed"]:
        r["action"] = "skip_already_signed"
        return r

    status, payload, err = http_json(
        "https://%s/v2/billing/meter/daily-checkin" % domain, token, method="POST", body={})
    r["claim_http"] = status
    body = payload or {}
    msg = str(body.get("msg", ""))
    if (body.get("code") == 10001 or "已签到" in msg):
        r["action"] = "skip_already_signed"  # 幂等，非错误
        return r
    if status == 200 and body.get("code") == 0:
        d = body.get("data") or {}
        r["action"] = "claimed"
        r["credit"] = body.get("credit") or d.get("credit") or d.get("daily_credit")
        r["streak_days"] = body.get("streak_days") or d.get("streak_days") or r["streak_days"]
        r["balance"] = extract_balance(body) or r["balance"]
    else:
        r["action"] = "error"
        r["error"] = "领取失败: HTTP=%s code=%s msg=%s" % (status, body.get("code"), msg or err)
    return r


def do_travel(token, check_only=False, location=None):
    """旅行闭环：查状态 -> arrived 先领 -> idle 且未达上限则派。写请求前必查前置条件。"""
    out = {"available": True, "state": None, "auto_log": []}

    status, payload, err = http_json(
        "https://%s/activity/growth/buddy/travel/status" % TRAVEL_DOMAIN, token)
    if err or status != 200 or (payload or {}).get("code") != 0:
        out["available"] = False
        out["reason"] = "旅行状态接口不可用: %s" % (err or (payload or {}).get("msg") or status)
        return out
    d = (payload or {}).get("data") or {}
    out["state"] = d.get("state")
    out["daily_limit_reached"] = bool(d.get("daily_limit_reached"))
    out["reward_credit"] = d.get("reward_credit")
    out["location"] = (d.get("location") or {}).get("name") if isinstance(d.get("location"), dict) else d.get("location")

    def countdown(d):
        try:
            left = int(d.get("arrive_at", 0)) - int(d.get("server_now", 0))
            return max(left, 0)
        except Exception:
            return None

    if d.get("state") == "traveling":
        out["arrive_in_seconds"] = countdown(d)
        out["note"] = "Buddy 旅行中，到达后自动可领"
        return out

    if d.get("state") == "arrived":
        if check_only:
            out["note"] = "已到达待领取（check-only 未领取）"
            return out
        status, payload, err = http_json(
            "https://%s/activity/growth/buddy/travel/claim" % TRAVEL_DOMAIN, token, method="POST", body={})
        body = payload or {}
        if status == 200 and body.get("code") == 0:
            got = (body.get("data") or {}).get("reward_credit")
            out["auto_log"].append("领取旅行积分 +%s" % got)
            out["claimed_credit"] = got
        else:
            out["auto_log"].append("领取失败: %s" % (body.get("msg") or err))
        # 领完重查状态，决定能否再派
        status, payload, err = http_json(
            "https://%s/activity/growth/buddy/travel/status" % TRAVEL_DOMAIN, token)
        d = ((payload or {}).get("data") or {}) if status == 200 and (payload or {}).get("code") == 0 else {}
        out["state"] = d.get("state") or out["state"]

    if d.get("state") == "idle" and not d.get("daily_limit_reached"):
        if check_only:
            out["note"] = "Buddy 空闲可派遣（check-only 未派遣）"
            return out
        loc = location if location in LOCATIONS else random.choice(list(LOCATIONS))
        status, payload, err = http_json(
            "https://%s/activity/growth/buddy/travel/depart" % TRAVEL_DOMAIN, token,
            method="POST", body={"location_id": loc})
        body = payload or {}
        if status == 200 and body.get("code") == 0:
            out["auto_log"].append("已派往「%s」" % LOCATIONS[loc])
            out["dispatched"] = True
        else:
            out["auto_log"].append("派遣失败: %s" % (body.get("msg") or err))
    elif d.get("state") == "idle":
        out["note"] = "今日派遣次数已达上限，明天再来"
    return out


def summarize(res):
    if res.get("status") == "error" and res.get("error") and not res.get("checkin"):
        return "执行失败: %s" % res["error"]
    parts = []
    if res.get("token_note"):
        src = str(res.get("token_source") or "")
        if src.startswith("ide-credential:"):
            parts.append("凭据来自 IDE 扩展明文凭据（主登录态已加密）")
        else:
            parts.append("凭据来自历史快照（主登录态已加密，属过渡方案）")
    c = res.get("checkin", {})
    act = c.get("action")
    if act == "claimed":
        parts.append("签到成功 +100 积分")
    elif act == "skip_already_signed":
        parts.append("今日已签到（自动跳过）")
    elif act == "checked_only":
        parts.append("今日已签" if c.get("today_signed") else "今日未签")
    elif act == "error":
        parts.append("签到失败: %s" % c.get("error", "未知"))
    if c.get("streak_days") is not None:
        parts.append("连续 %s 天" % c["streak_days"])
    if c.get("balance") is not None:
        parts.append("余额 %s" % c["balance"])
    t = res.get("travel") or {}
    if t.get("available"):
        if t.get("auto_log"):
            parts.append("；".join(t["auto_log"]))
        if t.get("state") == "traveling" and t.get("arrive_in_seconds") is not None:
            parts.append("旅行中，约 %d 小时后到达" % round(t["arrive_in_seconds"] / 3600))
        if t.get("note"):
            parts.append(t["note"])
    elif res.get("travel") is not None:
        parts.append("旅行功能暂不可用")
    return " | ".join(p for p in parts if p)


def main():
    args = sys.argv[1:]
    if "--version" in args:
        print(json.dumps({"version": __version__}))
        return 0
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    check_only = "--check-only" in args
    travel_only = "--travel-only" in args
    no_travel = "--no-travel" in args
    location = None
    if "--location" in args:
        try:
            location = int(args[args.index("--location") + 1])
        except (ValueError, IndexError):
            print(json.dumps({"status": "error", "error": "--location 需要数字参数 1-4"}))
            return 1

    result = {"status": "ok", "version": __version__}

    info, where = load_auth()
    if "--diagnose" in args:
        auth_d = (info or {}).get("auth", {}) or {}
        main_uin = _uin(info) if info else ""
        snaps = []
        for p, sinfo in scan_snapshots(where if info else None)[:8]:
            sauth = sinfo.get("auth") or {}
            stok, _ = resolve_token(sauth)
            snaps.append({
                "file": os.path.basename(p),
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
                "token_field": "encrypted-envelope" if isinstance(sauth.get("accessToken"), dict) else "plaintext",
                "token": mask_token(sauth.get("accessToken")),
                "uin_match": _uin(sinfo) == main_uin if main_uin else None,
                "expired": token_expired(sauth),
                "usable": bool(stok) and not token_expired(sauth) and (not main_uin or _uin(sinfo) == main_uin),
            })
        main_ids = _identity(info) if info else set()
        ide_diag = []
        for p, iinfo in scan_ide_credentials(where if info else None)[:5]:
            iauth = iinfo.get("auth") or {}
            itok, _ = resolve_token(iauth)
            matched = bool(main_ids & _identity(iinfo)) if (main_ids and _identity(iinfo)) else None
            ide_diag.append({
                "file": os.path.basename(p),
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
                "token_field": "plaintext" if isinstance(iauth.get("accessToken"), str) else "encrypted-envelope",
                "token": mask_token(iauth.get("accessToken")),
                "domain": iauth.get("domain"),
                "account_match": matched,
                "expired": token_expired(iauth),
                "usable": bool(itok) and not token_expired(iauth) and matched is not False,
            })
        diag = {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "auth_file_found": bool(info),
            "auth_file_path": where if info else (where or "未找到"),
            "token": mask_token(auth_d.get("accessToken")),
            "token_field": "encrypted-envelope" if isinstance(auth_d.get("accessToken"), dict) else "plaintext",
            "domain": auth_d.get("domain"),
            "token_expired": token_expired(auth_d) if info else None,
            "ssl_ca": "certifi" if _certifi_bundle() else "system-default",
            "ide_credentials": ide_diag,
            "plaintext_snapshots": snaps,
            "auth_paths_checked": [{"path": p, "exists": os.path.isfile(p)} for p in auth_candidates()],
        }
        diag_token, diag_err, diag_src = resolve_token_with_fallback(info, where) if info else (None, "未找到登录态文件", None)
        diag["token_source"] = diag_src
        if info and not diag_err and diag_src != "main":
            diag["token_note"] = IDE_HINT if (diag_src or "").startswith("ide-credential:") else STALE_HINT
        if info and not diag_err and not diag["token_expired"]:
            status, payload, err = http_json(
                "https://%s/v2/billing/meter/checkin-activity-status" % diag["domain"],
                diag_token, method="POST", body={})
            diag["api_reachable"] = err is None
            diag["api_http"] = status
        elif diag_err:
            diag["api_reachable"] = False
            diag["api_note"] = diag_err
        print(json.dumps({"status": "ok", "diagnose": diag}, ensure_ascii=False))
        return 0

    if not info:
        result.update({"status": "error",
                       "error": "未找到登录态文件，请先在 WorkBuddy 客户端登录后重试",
                       "searched": auth_candidates()})
        result["summary"] = summarize(result)
        print(json.dumps(result, ensure_ascii=False))
        return 1

    auth = info.get("auth") or {}
    domain = auth.get("domain") or "www.codebuddy.cn"
    token, tok_err, tok_src = resolve_token_with_fallback(info, where)
    if tok_err:
        result.update({"status": "error",
                       "error": tok_err,
                       "token": mask_token(auth.get("accessToken"))})
        result["summary"] = summarize(result)
        print(json.dumps(result, ensure_ascii=False))
        return 1
    if tok_src == "main" and token_expired(auth):
        result.update({"status": "error",
                       "error": "登录态已过期，请打开 WorkBuddy 客户端重新登录",
                       "token": mask_token(token)})
        result["summary"] = summarize(result)
        print(json.dumps(result, ensure_ascii=False))
        return 1

    result["token"] = mask_token(token)
    result["token_source"] = tok_src
    result["domain"] = domain
    if tok_src and tok_src != "main":
        result["token_note"] = IDE_HINT if tok_src.startswith("ide-credential:") else STALE_HINT

    if not travel_only:
        result["checkin"] = do_checkin(token, domain, check_only=check_only)
        if result["checkin"]["action"] == "error":
            result["status"] = "error"

    if not no_travel and not check_only:
        result["travel"] = do_travel(token, check_only=False, location=location)
    elif check_only:
        result["travel"] = do_travel(token, check_only=True, location=location)

    result["summary"] = summarize(result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
