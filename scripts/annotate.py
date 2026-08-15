"""
Kairos — 标注工具
在终端里逐封显示邮件，人工判断是否含时间承诺及其类型。
支持断点续传：退出后重跑会从上次位置继续。
"""

import json
import random
import re
from pathlib import Path

RAW_FILE = Path("data/emails_raw.jsonl")
SAMPLE_FILE = Path("data/sample.jsonl")      # 抽样结果，固定不变
LABELS_FILE = Path("data/labels.jsonl")      # 标注结果

PREVIEW_CHARS = 300
RANDOM_SEED = 42   # 固定种子，保证抽样可复现

# ── 抽样用的关键词（和 explore.py 保持一致）──────────────────

DATE_PATTERNS = [
    r"\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\bin\s+\d+\s+days?\b",
    r"\b(next|this)\s+(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\b",
    r"\d{1,2}月\d{1,2}日",
    r"\btomorrow\b",
]

HINTS = {
    "billing": [r"renew", r"subscription", r"invoice", r"billing", r"payment due", r"auto-renew"],
    "delivery": [r"shipped", r"out for delivery", r"tracking", r"dispatch", r"arriv"],
    "deadline": [r"\bdue\b", r"deadline", r"submit by", r"closing date", r"expires"],
    "appointment": [r"appointment", r"meeting", r"interview", r"booking confirm", r"reservation"],
    "promotion": [r"% off", r"\bsale\b", r"discount", r"limited time", r"shop now", r"\bdeal\b"],
}

# 分层抽样配额
QUOTAS = {
    "billing": 130,
    "delivery": 70,
    "deadline": 60,
    "appointment": 60,
    "promotion": 120,
    "random": 60,
}


def load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def has_date(text: str) -> bool:
    return any(re.search(p, text, re.I) for p in DATE_PATTERNS)


def hint_match(text: str, cat: str) -> bool:
    return any(re.search(p, text, re.I) for p in HINTS[cat])


# ── 分层抽样 ──────────────────────────────────────────────────

def build_sample():
    """按配额分层抽样，结果写入 sample.jsonl（只做一次）"""
    if SAMPLE_FILE.exists():
        print(f"Using existing sample: {SAMPLE_FILE}")
        return load_jsonl(SAMPLE_FILE)

    emails = load_jsonl(RAW_FILE)
    print(f"Loaded {len(emails)} raw emails")

    random.seed(RANDOM_SEED)
    random.shuffle(emails)

    buckets = {k: [] for k in QUOTAS}
    used_ids = set()

    # 先填有日期 + 类别命中的桶
    for e in emails:
        text = f"{e['subject']} {e['body'][:2000]}"
        if not has_date(text):
            continue
        for cat in ["billing", "delivery", "deadline", "appointment", "promotion"]:
            if len(buckets[cat]) >= QUOTAS[cat]:
                continue
            if hint_match(text, cat) and e["id"] not in used_ids:
                e["_bucket"] = cat
                buckets[cat].append(e)
                used_ids.add(e["id"])
                break

    # 再填随机桶
    for e in emails:
        if len(buckets["random"]) >= QUOTAS["random"]:
            break
        if e["id"] not in used_ids:
            e["_bucket"] = "random"
            buckets["random"].append(e)
            used_ids.add(e["id"])

    sample = [e for bucket in buckets.values() for e in bucket]
    random.shuffle(sample)   # 打乱顺序，避免标注时形成惯性

    with SAMPLE_FILE.open("w", encoding="utf-8") as f:
        for e in sample:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print("\nSample composition:")
    for cat in QUOTAS:
        print(f"  {cat:12s} {len(buckets[cat]):4d} / {QUOTAS[cat]}")
    print(f"\nTotal: {len(sample)}  →  {SAMPLE_FILE}")
    return sample


# ── 显示 ──────────────────────────────────────────────────────

def clean_body(body: str) -> str:
    """压缩空白，让终端显示更紧凑"""
    return re.sub(r"\s+", " ", body).strip()


def show_email(e: dict, idx: int, total: int, full: bool = False):
    print("\n" + "=" * 70)
    print(f"[{idx}/{total}]   bucket: {e.get('_bucket', '?')}")
    print("=" * 70)
    print(f"From:    {e['from'][:65]}")
    print(f"Date:    {e['date_header'][:40]}")
    print(f"Subject: {e['subject'][:65]}")
    print("-" * 70)

    body = clean_body(e["body"])
    if full:
        print(body[:5000])
    else:
        print(body[:PREVIEW_CHARS])
        if len(body) > PREVIEW_CHARS:
            print(f"\n   ... [{len(body) - PREVIEW_CHARS} more chars — press 'f' for full text]")
    print("-" * 70)


MENU = """
  1) billing      续费 / 账单到期
  2) delivery     快递到货
  3) deadline     截止日期
  4) appointment  预约 / 会议
  5) 否 — 不该进日历

  f) 看全文    b) 上一封    s) 跳过    q) 保存退出
"""

TYPE_MAP = {"1": "billing", "2": "delivery", "3": "deadline", "4": "appointment"}


def main():
    sample = build_sample()
    total = len(sample)

    # 读取已标注，支持续传
    labeled = load_jsonl(LABELS_FILE)
    done_ids = {l["email_id"] for l in labeled}
    print(f"\nAlready labeled: {len(done_ids)}")
    input("\nPress Enter to start annotating...")

    out = LABELS_FILE.open("a", encoding="utf-8")

    i = 0
    show_full = False
    session_count = 0

    while i < total:
        e = sample[i]

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
            record = {
                "email_id": e["id"],
                "bucket": e.get("_bucket"),
                "has_commitment": False,
                "events": [],
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            done_ids.add(e["id"])
            session_count += 1
            i += 1
            continue

        if choice in TYPE_MAP:
            ev_type = TYPE_MAP[choice]
            # 追问日期
            dt = input("  Date (YYYY-MM-DD, or YYYY-MM-DD HH:MM, blank=skip): ").strip()
            title = input("  Short title: ").strip()

            record = {
                "email_id": e["id"],
                "bucket": e.get("_bucket"),
                "has_commitment": True,
                "events": [{
                    "type": ev_type,
                    "datetime": dt or None,
                    "title": title or e["subject"][:60],
                }],
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            done_ids.add(e["id"])
            session_count += 1
            i += 1
            continue

        print("  Invalid input, try again.")

    out.close()
    print(f"\nLabeled this session: {session_count}")
    print(f"Total labeled: {len(done_ids)} / {total}")
    print(f"Saved to: {LABELS_FILE}")


if __name__ == "__main__":
    main()