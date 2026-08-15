#!/usr/bin/env python3
"""
annotate_test.py  —  只标注新抽的 150 封 test

读 test_new_raw.jsonl 的 id 列表 → 从 sample.jsonl 取邮件内容 → 逐封标注
结果写 test_labels.jsonl（支持中断续标）

标完后：python scripts/finalize_test.py  生成 test.jsonl
"""

import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SKELETON   = DATA / "test_new_raw.jsonl"
EMAIL_FILE = DATA / "sample.jsonl"
OUT_FILE   = DATA / "test_labels.jsonl"
PREVIEW_CHARS = 1200

def load_jsonl(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

def clean_body(body):
    return re.sub(r"\s+", " ", body or "").strip()

def show_email(e, idx, total, full=False):
    print("\n" + "=" * 70)
    print(f"[{idx}/{total}]   bucket: {e.get('_bucket', '?')}")
    print("=" * 70)
    print(f"From:    {e.get('from','')[:65]}")
    print(f"Date:    {e.get('date_header','')[:40]}")
    print(f"Subject: {e.get('subject','')[:65]}")
    print("-" * 70)
    body = clean_body(e.get("body", ""))
    print(body[:5000] if full else body[:PREVIEW_CHARS])
    if not full and len(body) > PREVIEW_CHARS:
        print(f"\n   ... [{len(body)-PREVIEW_CHARS} more chars — press 'f' for full text]")
    print("-" * 70)

MENU = """
  1) billing      续费 / 账单到期        2) delivery     快递到货
  3) deadline     截止日期               4) appointment  预约 / 会议
  5) 否 — 不该进日历
  f) 看全文    b) 上一封    s) 跳过    q) 保存退出

  判据：未来(≥发送日) + 与用户相关 + 唯一确定时间点
  可推算单一时长抽("in 5 days")；区间("4-6 days")、模糊("soon")不抽
  收据/已完成/已取消/纯促销 → 否；权益过期 → deadline；线程只看最新层
"""
TYPE_MAP = {"1": "billing", "2": "delivery", "3": "deadline", "4": "appointment"}

def main():
    skeleton = load_jsonl(SKELETON)
    emails = {e["id"]: e for e in load_jsonl(EMAIL_FILE)}
    todo = []
    for s in skeleton:
        em = emails.get(s["email_id"])
        if em:
            em["_bucket"] = s.get("bucket", em.get("_bucket"))
            todo.append(em)
    total = len(todo)

    labeled = load_jsonl(OUT_FILE)
    done_ids = {l["email_id"] for l in labeled}
    print(f"待标注 {total} 封，已完成 {len(done_ids)} 封，剩余 {total-len(done_ids)} 封")
    input("\nPress Enter to start...")

    out = OUT_FILE.open("a", encoding="utf-8")
    i = 0
    show_full = False
    session = 0

    while i < total:
        e = todo[i]
        if e["id"] in done_ids:
            i += 1
            continue
        show_email(e, i + 1, total, full=show_full)
        print(MENU)
        choice = input("> ").strip().lower()

        if choice == "q":
            break
        if choice == "f":
            show_full = True
            continue
        show_full = False
        if choice == "s":
            i += 1
            continue
        if choice == "b":
            i = max(0, i - 1)
            continue

        if choice == "5":
            rec = {"email_id": e["id"], "bucket": e.get("_bucket"),
                   "has_commitment": False, "events": []}
        elif choice in TYPE_MAP:
            dt = input("  Date (YYYY-MM-DD 或 YYYY-MM-DD HH:MM): ").strip()
            title = input("  Short title: ").strip()
            rec = {"email_id": e["id"], "bucket": e.get("_bucket"),
                   "has_commitment": True,
                   "events": [{"type": TYPE_MAP[choice],
                               "datetime": dt or None,
                               "title": title or e.get("subject", "")[:60]}]}
        else:
            print("  无效输入")
            continue

        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        done_ids.add(e["id"])
        session += 1
        i += 1

    out.close()
    print(f"\n本次标注 {session} 封，累计 {len(done_ids)}/{total}")
    if len(done_ids) == total:
        print("全部完成！接下来跑：python scripts/finalize_test.py")

if __name__ == "__main__":
    main()
