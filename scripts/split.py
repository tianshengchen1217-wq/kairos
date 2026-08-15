"""
Kairos — 数据集拆分

把 500 条标注按 350 / 150 拆成开发集和测试集。
分层抽样：保证两边的正样本比例和类型分布一致。

纪律：
  dev.jsonl  — 反复看，用来调 prompt、做错误分析
  test.jsonl — 方案定稿前不得查看，最后只跑一次
"""

import json
import random
from collections import Counter
from pathlib import Path

LABELS_FILE = Path("data/labels_clean.jsonl")
DEV_FILE = Path("data/dev.jsonl")
TEST_FILE = Path("data/test.jsonl")

TEST_SIZE = 150
SEED = 42          # 固定种子，保证拆分可复现


def load_jsonl(path: Path) -> list:
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def describe(name: str, data: list):
    """打印一个数据集的构成"""
    pos = [l for l in data if l["has_commitment"]]
    types = Counter(e["type"] for l in pos for e in l["events"])
    buckets = Counter(l["bucket"] for l in data)

    print(f"\n{name}")
    print(f"  total    {len(data)}")
    print(f"  positive {len(pos)}  ({len(pos) / len(data) * 100:.1f}%)")
    print(f"  types    {dict(types)}")
    print(f"  buckets  {dict(buckets)}")


def main():
    labels = load_jsonl(LABELS_FILE)
    print(f"Loaded {len(labels)} labels from {LABELS_FILE}")

    random.seed(SEED)

    # 按 has_commitment 分层，保证正负比例在两边一致
    pos = [l for l in labels if l["has_commitment"]]
    neg = [l for l in labels if not l["has_commitment"]]
    random.shuffle(pos)
    random.shuffle(neg)

    ratio = TEST_SIZE / len(labels)
    n_pos_test = round(len(pos) * ratio)
    n_neg_test = TEST_SIZE - n_pos_test

    test = pos[:n_pos_test] + neg[:n_neg_test]
    dev = pos[n_pos_test:] + neg[n_neg_test:]

    random.shuffle(test)
    random.shuffle(dev)

    # 写文件
    for path, data in [(DEV_FILE, dev), (TEST_FILE, test)]:
        with path.open("w", encoding="utf-8") as f:
            for l in data:
                f.write(json.dumps(l, ensure_ascii=False) + "\n")

    describe("DEV  (开发集 — 反复使用)", dev)
    describe("TEST (测试集 — 最后跑一次)", test)

    print(f"\nWritten: {DEV_FILE}  {TEST_FILE}")
    print("\n⚠️  test.jsonl 在方案定稿前不要打开、不要跑指标。")


if __name__ == "__main__":
    main()
    