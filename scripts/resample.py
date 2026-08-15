#!/usr/bin/env python3
"""resample.py — 从未抽过的邮件里分层抽 150 封新 test（复用 annotate.py 的原分桶逻辑）"""

import json, random, sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "scripts"))

# 复用当初的分桶规则，保证新旧可比
from annotate import has_date, hint_match

random.seed(42)
QUOTAS_NEW = {"billing": 39, "promotion": 36, "delivery": 21,
              "deadline": 18, "appointment": 18, "random": 18}

def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

def dump_jsonl(path, rows, mode="w"):
    with open(path, mode, encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def main():
    dev = load_jsonl(DATA / "dev.jsonl")          # 已是合并后的 500
    used_ids = {r["email_id"] for r in dev}
    raw = load_jsonl(DATA / "emails_raw.jsonl")
    pool = [e for e in raw if e["id"] not in used_ids]
    print(f"候选池: {len(pool)} 封（排除已抽 {len(used_ids)} 封）")

    random.shuffle(pool)
    buckets = {k: [] for k in QUOTAS_NEW}
    picked_ids = set()

    # 跟当初完全一致：先填「有日期 + 类别命中」的桶
    for e in pool:
        text = f"{e['subject']} {e['body'][:2000]}"
        if not has_date(text):
            continue
        for cat in ["billing", "delivery", "deadline", "appointment", "promotion"]:
            if len(buckets[cat]) >= QUOTAS_NEW[cat]:
                continue
            if hint_match(text, cat) and e["id"] not in picked_ids:
                e["_bucket"] = cat
                buckets[cat].append(e)
                picked_ids.add(e["id"])
                break

    # 再填随机桶
    for e in pool:
        if len(buckets["random"]) >= QUOTAS_NEW["random"]:
            break
        if e["id"] not in picked_ids:
            e["_bucket"] = "random"
            buckets["random"].append(e)
            picked_ids.add(e["id"])

    picked = [e for b in buckets.values() for e in b]
    random.shuffle(picked)
    print(f"实际抽取: {len(picked)} 封")
    print(f"分桶: { {k: len(v) for k, v in buckets.items()} }")

    dump_jsonl(DATA / "sample.jsonl", picked, mode="a")
    print(f"已追加 {len(picked)} 封到 sample.jsonl")

    skeleton = [{"email_id": e["id"], "bucket": e["_bucket"],
                 "has_commitment": None, "events": []} for e in picked]
    dump_jsonl(DATA / "test_new_raw.jsonl", skeleton)
    print("待标注文件: test_new_raw.jsonl")

if __name__ == "__main__":
    main()