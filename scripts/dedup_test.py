#!/usr/bin/env python3
"""
dedup_test.py  —  去重键提取与合并逻辑（不调 LLM，零成本）

v4：按事件类型分流合并策略
  · billing（订阅账单）    —— 有周期性，旧的已过期则新增下一期
  · delivery / appointment / deadline —— 一次性事件，同 key 永远只留一条

四场景：
  取消              → 删除
  同 key 同日期      → 静默覆盖（重复提醒，不新增任务）
  同 key 日期变      → 覆盖并提示（改期）
  同 key 周期性下一期 → 新增（仅 billing）
"""

import json, re
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone, date

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# ------------------------------------------------------------------ 一级：单号
REF_PATTERNS = [
    ("labeled", re.compile(
        r"(?:order|订单号?|confirmation|booking\s*ref(?:erence)?|"
        r"tracking|运单号?|快递单号?|reservation|文稿编号|invoice)"
        r"\s*(?:number|no\.?|#|：|:)?\s*"
        r"([A-Z0-9][A-Z0-9\-]{5,24})", re.I)),
    ("apple",   re.compile(r"\b(W\d{9,12})\b")),
    ("longnum", re.compile(r"(?<![/=\w])(\d{12,22})(?![/=\w])")),
]

COMMON_WORDS = {
    "INFORMATION","STATUS","AVAILABLE","DETAILS","NUMBER","SUMMARY","BEFORE",
    "TOTALLABEL","SHIPPING","BILLING","ADDRESS","PAYMENT","CONTACT","ACCOUNT",
    "DELIVERY","TRACKING","CONFIRM","RECEIPT","PRODUCT","SERVICE","SUPPORT",
    "CUSTOMER","QUESTION","QUESTIONS","REQUIRED","SUBTOTAL","ESTIMATED",
}

def valid_ref(v):
    """真单号：字母数字混合，或纯数字≥12位。纯字母一律排除。"""
    if v in COMMON_WORDS:
        return False
    has_alpha = bool(re.search(r"[A-Z]", v))
    has_digit = bool(re.search(r"\d", v))
    if has_alpha and has_digit:
        return True
    if has_digit and not has_alpha:
        return len(re.sub(r"\D", "", v)) >= 12
    return False

def extract_refs(text, limit=4000):
    t = text[:limit]
    out = []
    for _, pat in REF_PATTERNS:
        for m in pat.finditer(t):
            v = m.group(1).strip().upper()
            if valid_ref(v) and v not in out:
                out.append(v)
    return out[:5]

# ------------------------------------------------------------------ 二级/三级
MULTI_TLD = {"com.au","co.uk","com.cn","co.jp","com.sg","co.nz",
             "com.hk","com.tw","co.in","com.br","co.za"}

def sender_domain(frm):
    m = re.search(r"@([\w.\-]+)", frm or "")
    if not m:
        return "unknown"
    parts = m.group(1).lower().split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_TLD:
        return ".".join(parts[-3:])          # sephora.com.au
    return ".".join(parts[-2:]) if len(parts) >= 2 else parts[0]

PRODUCT_STOP = re.compile(r"^(the|your|a|an|for|and|of|with|new|order|receipt)$", re.I)

def product_key(title, subject):
    src = f"{title} {subject}"
    toks = re.findall(r"[A-Za-z]+\d*|\d+[A-Za-z]*|[\u4e00-\u9fff]{2,}", src)
    toks = [t.lower() for t in toks if not PRODUCT_STOP.match(t)]
    return "".join(toks[:4]) if toks else ""

def build_key(em, ev):
    """严格单键：真单号 > 域名+类型+日期 > 商品词。
    单键而非多键——多键会造成传递性污染。"""
    body = str(em.get("body", ""))
    subj = em.get("subject", "")
    dom  = sender_domain(em.get("from", ""))
    typ  = ev.get("type", "?")

    refs = extract_refs(f"{subj}\n{body}")
    if refs:
        return f"ref:{dom}|{refs[0]}", 1

    d = (ev.get("datetime") or "")[:10]
    if d:
        # title 指纹：防止同一封邮件的多个事件被误合
        tsig = product_key(ev.get("title", ""), "")[:14]
        return f"dom:{dom}|{typ}|{d}|{tsig}", 2

    pk = product_key(ev.get("title", ""), subj)
    return (f"prod:{dom}|{typ}|{pk}", 3) if pk else (f"none:{em['id']}", 3)

# ------------------------------------------------------------------ 合并逻辑
# 只有账单类有周期性——同一订阅会反复扣款。
# 快递/预约/截止都是一次性事件，同一个单号下永远只该有一条。
CYCLIC_TYPES = {"billing"}

def apply_event(live, incoming, today):
    """把新事件并入活跃列表 live（原地修改），返回 (动作, 说明)。"""
    nd  = (incoming["datetime"] or "")[:10]
    typ = incoming.get("type")

    if incoming.get("cancelled"):
        for e in list(live):
            if (e["datetime"] or "")[:10] == nd:
                live.remove(e)
        return "delete", "事件取消"

    # 场景四：同日期 → 重复提醒，静默覆盖，不新增任务栏
    same = next((e for e in live if (e["datetime"] or "")[:10] == nd), None)
    if same:
        live[live.index(same)] = incoming
        return "silent_overwrite", "重复提醒，日期一致"

    # 一次性事件：同 key 只留一条，日期变了就是改期（不论旧的过没过期）
    if typ not in CYCLIC_TYPES:
        old = live[-1]
        live[live.index(old)] = incoming
        return "overwrite_notify", f"改期 {(old['datetime'] or '')[:10]} → {nd}"

    # 周期性事件（订阅账单）
    pending = [e for e in live if (e["datetime"] or "")[:10] >= today.isoformat()]
    if pending:
        old = pending[0]
        live[live.index(old)] = incoming
        return "overwrite_notify", f"改期 {(old['datetime'] or '')[:10]} → {nd}"

    live.append(incoming)
    return "new_cycle", f"上一期已过，新增 {nd}"

# ------------------------------------------------------------------ 主流程
def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

def main():
    cache = json.loads((DATA / "llm_cache.json").read_text(encoding="utf-8"))
    emails = {e["id"]: e for e in load_jsonl(DATA / "sample.jsonl")}

    items = []
    for eid, rec in cache.items():
        if not rec.get("has_commitment"):
            continue
        em = emails.get(eid)
        if not em:
            continue
        for ev in rec.get("events", []):
            if not ev.get("datetime"):
                continue
            key, lvl = build_key(em, ev)
            send = datetime.fromtimestamp(
                int(em["internal_date"]) // 1000, tz=timezone.utc)
            items.append({
                "eid": eid, "subject": em.get("subject", "")[:52],
                "from": sender_domain(em.get("from", "")),
                "type": ev.get("type"), "datetime": ev.get("datetime"),
                "key": key, "level": lvl, "sent": send,
            })

    print("=" * 66)
    print(f"进入日历层的事件：{len(items)} 条")
    print("=" * 66)

    lv = Counter(i["level"] for i in items)
    print("\n【key 提取层级分布】")
    names = {1: "一级 单号（最可靠）", 2: "二级 域名+类型+日期", 3: "三级 商品关键词"}
    for k in (1, 2, 3):
        n = lv.get(k, 0)
        print(f"  {names[k]:<24} {n:>4} 条  {n/max(len(items),1):>6.1%}")

    groups = defaultdict(list)
    for it in items:
        groups[it["key"]].append(it)

    today = date.today()
    final_total = 0
    details = []
    for key, g in groups.items():
        g = sorted(g, key=lambda x: x["sent"])
        live = [g[0]]
        acts = []
        for nxt in g[1:]:
            act, why = apply_event(live, {**nxt, "cancelled": False}, today)
            acts.append((act, why, nxt))
        final_total += len(live)
        if len(g) > 1:
            details.append((key, g, acts, len(live)))

    merged_away = len(items) - final_total
    multi = [g for g in groups.values() if len(g) > 1]
    print(f"\n【合并效果】")
    print(f"  独立事件组：{len(groups)}")
    print(f"  含重复的组：{len(multi)}")
    print(f"  最终日历条目：{final_total}"
          f"（{len(items)} → {final_total}，合并掉 {merged_away} 条，"
          f"{merged_away/max(len(items),1):.1%}）")

    if details:
        print(f"\n【重复组明细】")
        for key, g, acts, nlive in sorted(details, key=lambda x: -len(x[1])):
            print(f"\n  ── {g[0]['from']} / {g[0]['type']} ── "
                  f"{len(g)} 封 → {nlive} 条   key={key[:44]}")
            print(f"     [首次] {g[0]['datetime']}  {g[0]['subject']}")
            for act, why, nxt in acts:
                print(f"     [{act:<17}] {nxt['datetime']}  {nxt['subject']}")
                print(f"        └ {why}")

    print(f"\n【一级 key 样例（核对是否抓到假单号）】")
    shown = 0
    for it in items:
        if it["level"] == 1 and shown < 15:
            print(f"  {it['key'][:40]:<42} {it['subject']}")
            shown += 1

    lvl2 = [g for g in multi if g[0]["level"] == 2]
    if lvl2:
        print(f"\n  ⚠ {len(lvl2)} 组靠二级 key（无单号）合并，需人工确认是否真为同一事件")

    print(f"\n  注：dev 为分层抽样，同一事件的多封邮件很少同时被抽中，")
    print(f"      此处合并率不代表真实增量场景（真实场景一个订单通常产生 3–4 封）。")

if __name__ == "__main__":
    main()