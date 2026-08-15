"""
Kairos — 数据探索脚本
统计邮件分布，为标注方案提供依据。
"""

import json
import re
from collections import Counter
from pathlib import Path

DATA_FILE = Path("data/emails_raw.jsonl")


def load_emails():
    """逐行读取 JSONL，跳过损坏行（fetch 可能还在写）"""
    emails = []
    with DATA_FILE.open(encoding="utf-8") as f:
        for line in f:
            try:
                emails.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return emails


# ── 日期表达式模式 ────────────────────────────────────────────

DATE_PATTERNS = {
    "absolute_dmy": r"\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
    "absolute_mdy": r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
    "numeric": r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    "iso": r"\b\d{4}-\d{2}-\d{2}\b",
    "relative_days": r"\bin\s+\d+\s+days?\b",
    "relative_weekday": r"\b(next|this)\s+(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\b",
    "chinese": r"\d{1,2}月\d{1,2}日",
    "tomorrow": r"\b(tomorrow|tonight|today)\b",
}

# ── 类别关键词（粗筛，仅用于估算分布）─────────────────────────

CATEGORY_HINTS = {
    "billing": [r"renew", r"subscription", r"invoice", r"billing", r"payment due", r"auto-renew"],
    "delivery": [r"shipped", r"out for delivery", r"tracking", r"dispatch", r"arriv"],
    "deadline": [r"\bdue\b", r"deadline", r"submit by", r"closing date", r"expires"],
    "appointment": [r"appointment", r"meeting", r"interview", r"booking confirm", r"reservation"],
    "promotion": [r"% off", r"sale", r"discount", r"limited time", r"shop now", r"deal"],
}


def match_any(text: str, patterns: list) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def main():
    emails = load_emails()
    print(f"Total emails loaded: {len(emails)}\n")

    # ── 1. 日期表达分布 ──────────────────────────────────────
    print("=" * 55)
    print("DATE EXPRESSIONS")
    print("=" * 55)

    date_counter = Counter()
    has_any_date = 0

    for e in emails:
        text = f"{e['subject']} {e['body'][:3000]}"
        found = False
        for name, pattern in DATE_PATTERNS.items():
            if re.search(pattern, text, re.I):
                date_counter[name] += 1
                found = True
        if found:
            has_any_date += 1

    for name, count in date_counter.most_common():
        print(f"  {name:20s} {count:5d}  ({count/len(emails)*100:5.1f}%)")
    print(f"\n  Emails with ANY date: {has_any_date} ({has_any_date/len(emails)*100:.1f}%)")

    # ── 2. 类别粗估 ──────────────────────────────────────────
    print("\n" + "=" * 55)
    print("CATEGORY HINTS (keyword-based, rough estimate)")
    print("=" * 55)

    cat_counter = Counter()
    for e in emails:
        text = f"{e['subject']} {e['body'][:2000]}"
        for cat, patterns in CATEGORY_HINTS.items():
            if match_any(text, patterns):
                cat_counter[cat] += 1

    for cat, count in cat_counter.most_common():
        print(f"  {cat:15s} {count:5d}  ({count/len(emails)*100:5.1f}%)")

    # ── 3. Gmail 标签分布 ────────────────────────────────────
    print("\n" + "=" * 55)
    print("GMAIL LABELS")
    print("=" * 55)

    label_counter = Counter()
    for e in emails:
        for label in e.get("labels", []):
            label_counter[label] += 1

    for label, count in label_counter.most_common(12):
        print(f"  {label:25s} {count:5d}")

    # ── 4. 高频发件人 ────────────────────────────────────────
    print("\n" + "=" * 55)
    print("TOP SENDERS")
    print("=" * 55)

    sender_counter = Counter()
    for e in emails:
        # 提取纯邮箱地址
        m = re.search(r"<([^>]+)>", e["from"])
        addr = m.group(1) if m else e["from"]
        sender_counter[addr.lower()] += 1

    for sender, count in sender_counter.most_common(20):
        print(f"  {sender:45s} {count:4d}")

    # ── 5. 交叉：有日期 且 疑似 billing ──────────────────────
    print("\n" + "=" * 55)
    print("HIGH-VALUE CANDIDATES (has date + billing hint)")
    print("=" * 55)

    candidates = 0
    for e in emails:
        text = f"{e['subject']} {e['body'][:2000]}"
        has_date = any(re.search(p, text, re.I) for p in DATE_PATTERNS.values())
        is_billing = match_any(text, CATEGORY_HINTS["billing"])
        if has_date and is_billing:
            candidates += 1

    print(f"  Count: {candidates} ({candidates/len(emails)*100:.1f}%)")


if __name__ == "__main__":
    main()