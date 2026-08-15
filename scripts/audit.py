"""
Kairos — 标注质量体检
检查格式错误、可疑值、一致性问题。
"""

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

LABELS_FILE = Path("data/labels_clean.jsonl")
SAMPLE_FILE = Path("data/sample.jsonl")

VALID_TYPES = {"billing", "delivery", "deadline", "appointment"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")


def load_jsonl(path):
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def main():
    labels = load_jsonl(LABELS_FILE)
    sample = {e["id"]: e for e in load_jsonl(SAMPLE_FILE)}
    idx_of = {e["id"]: i + 1 for i, e in enumerate(load_jsonl(SAMPLE_FILE))}

    issues = Counter()

    print("=" * 60)
    print("FORMAT ISSUES")
    print("=" * 60)

    for l in labels:
        n = idx_of.get(l["email_id"], "?")

        # 负样本不该有 events
        if not l["has_commitment"] and l["events"]:
            print(f"  #{n}: negative but has events")
            issues["neg_with_events"] += 1

        for ev in l["events"]:
            # 类型合法性
            if ev["type"] not in VALID_TYPES:
                print(f"  #{n}: bad type '{ev['type']}'")
                issues["bad_type"] += 1

            dt = ev.get("datetime")

            # 日期缺失
            if not dt:
                print(f"  #{n}: positive but no datetime  [{ev['type']}]")
                issues["no_date"] += 1
                continue

            # 日期格式
            if not DATE_RE.match(dt.strip()):
                print(f"  #{n}: bad date format -> {dt!r}")
                issues["bad_date"] += 1
                continue

            # 日期必须晚于邮件发送时间
            email = sample.get(l["email_id"])
            if email and email.get("internal_date"):
                sent = datetime.fromtimestamp(int(email["internal_date"]) / 1000)
                try:
                    parsed = datetime.strptime(dt.strip()[:10], "%Y-%m-%d")
                except ValueError:
                    continue
                delta = (parsed - sent).days
                if delta < -1:
                    print(f"  #{n}: date {dt[:10]} is {abs(delta)}d BEFORE email ({sent.date()})")
                    issues["past_date"] += 1
                elif delta > 400:
                    print(f"  #{n}: date {dt[:10]} is {delta}d after email — suspicious")
                    issues["far_future"] += 1

    if not issues:
        print("  none")

    # ── 一致性抽查线索 ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("CONSISTENCY: same sender, different labels")
    print("=" * 60)

    by_sender = {}
    for l in labels:
        email = sample.get(l["email_id"])
        if not email:
            continue
        m = re.search(r"<([^>]+)>", email["from"])
        addr = (m.group(1) if m else email["from"]).lower()
        by_sender.setdefault(addr, []).append((idx_of[l["email_id"]], l["has_commitment"]))

    for addr, rows in sorted(by_sender.items()):
        if len(rows) < 2:
            continue
        vals = {r[1] for r in rows}
        if len(vals) > 1:   # 同一发件人既有正也有负
            pos = [str(n) for n, v in rows if v]
            neg = [str(n) for n, v in rows if not v]
            print(f"  {addr}")
            print(f"     pos: #{', #'.join(pos)}   neg: #{', #'.join(neg)}")

    print("\n" + "=" * 60)
    print(f"Total issues: {sum(issues.values())}")
    for k, v in issues.most_common():
        print(f"  {k:20s} {v}")


if __name__ == "__main__":
    main()