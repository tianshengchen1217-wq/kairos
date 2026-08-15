"""
Kairos — 标注修正脚本

功能：
1. 去重 — 标注时重标会追加新行，同一 email_id 保留最后一条
2. 修正 — 按 sample.jsonl 中的序号（1-indexed）覆盖指定记录
3. 排序 — 按 sample 顺序写回，保证结果可复现

输出：data/labels_clean.jsonl
"""

import json
from pathlib import Path

SAMPLE_FILE = Path("data/sample.jsonl")
LABELS_FILE = Path("data/labels.jsonl")
OUTPUT_FILE = Path("data/labels_clean.jsonl")

# ── 修正表 ────────────────────────────────────────────────────
# key = 标注时看到的序号（[N/500] 里的 N）
# value = 要覆盖的字段

FIXES = {
    # ── 格式修正 ──────────────────────────────────────────
    4: {
        "has_commitment": True,
        "events": [{"type": "billing", "datetime": "2023-04-13",
                    "title": "Apple 订阅续期 ¥12/月"}],
    },
    13: {
        "has_commitment": True,
        "events": [{"type": "deadline", "datetime": "2024-04-19",
                    "title": "Essex 欠款结算截止"}],
    },
    276: {
        "has_commitment": True,
        "events": [{"type": "billing", "datetime": "2024-07-12",
                    "title": "Apple 订阅续期"}],
    },
    318: {
        "has_commitment": True,
        "events": [{"type": "appointment", "datetime": "2022-07-27 13:00",
                    "title": "预约"}],
    },
    # #14 Anthropic 收据 — 已扣款记录，非未来承诺
    14: {
        "has_commitment": False,
        "events": [],
    },
    # #16 Louisiana Crawfish 促销 — 页脚 "subscription" 导致误判
    16: {
        "has_commitment": False,
        "events": [],
    },
    # #57 手滑误按
    57: {
        "has_commitment": False,
        "events": [],
    },
    # #336 OpenTable Mani Restaurant — 当时未展开全文，缺日期
    336: {
        "has_commitment": True,
        "events": [{
            "type": "appointment",
            "datetime": "2026-07-04 18:30",
            "title": "Mani Restaurant 订位 2人（Glebe）",
        }],
    },
}


def load_jsonl(path: Path) -> list:
    """逐行读取 JSONL，跳过损坏行"""
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def main():
    sample = load_jsonl(SAMPLE_FILE)
    labels = load_jsonl(LABELS_FILE)

    print(f"Sample: {len(sample)} emails")
    print(f"Labels: {len(labels)} rows")

    # ── 去重：同一 email_id 保留最后一条 ──────────────────────
    dedup = {}
    for l in labels:
        dedup[l["email_id"]] = l
    dupes = len(labels) - len(dedup)
    if dupes:
        print(f"  removed {dupes} duplicate row(s)")

    # ── 应用修正 ─────────────────────────────────────────────
    print("\nApplying fixes:")
    fixed = 0
    for idx, patch in sorted(FIXES.items()):
        if idx < 1 or idx > len(sample):
            print(f"  #{idx}: out of range, skipped")
            continue

        email_id = sample[idx - 1]["id"]   # 序号 1-indexed
        if email_id not in dedup:
            print(f"  #{idx}: not labeled yet, skipped")
            continue

        before = dedup[email_id].get("has_commitment")
        dedup[email_id].update(patch)
        after = patch["has_commitment"]
        print(f"  #{idx}: {before} -> {after}")
        fixed += 1

    # ── 按 sample 顺序排序后写回 ──────────────────────────────
    order = {e["id"]: i for i, e in enumerate(sample)}
    final = sorted(dedup.values(), key=lambda l: order.get(l["email_id"], 10**9))

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        for l in final:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")

    # ── 汇总 ─────────────────────────────────────────────────
    pos = sum(1 for l in final if l["has_commitment"])
    print(f"\nFixed:    {fixed}")
    print(f"Final:    {len(final)} labels")
    print(f"Positive: {pos} ({pos / len(final) * 100:.1f}%)")
    print(f"Output:   {OUTPUT_FILE}")


if __name__ == "__main__":
    main()