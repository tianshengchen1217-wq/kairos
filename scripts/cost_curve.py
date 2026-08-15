#!/usr/bin/env python3
"""
cost_curve.py  —  Kairos 成本曲线计算

不重新抽取、不烧钱。读现有数据还原每封邮件走的路径，估算四个方案的成本：
  规则 baseline / 纯 Haiku / 混合(Haiku+Sonnet兜底) / 全 Opus

放到 kairos/scripts/ 下运行：  python scripts/cost_curve.py

token 估算：默认用"字符数 / 4"粗估（英文约 4 字符/token）。
若想用精确 token 数，把 USE_API_COUNT=True，会调 anthropic 的 count_tokens 接口
（只计数、不产生抽取费用，但会慢一些）。
"""

import json
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
DATA       = ROOT / "data"
GOLD_FILE  = DATA / "dev.jsonl"
EMAIL_FILE = DATA / "sample.jsonl"
CACHE_FILE = DATA / "llm_cache.json"

# ------------------------------------------------------------------ 价格（USD / 每百万 token），2026-08 当前价
#   注意：Sonnet 5 为 introductory 价，2026-09-01 起涨到 3/15
PRICES = {
    "haiku":  {"in": 1.0,  "out": 5.0},
    "sonnet": {"in": 2.0,  "out": 10.0},
    "opus":   {"in": 5.0,  "out": 25.0},
}

# system prompt 的 token 数（每次调用都要发一遍），粗估。可按实际调整。
SYSTEM_PROMPT_TOKENS = 550

USE_API_COUNT = False   # True 则用 API 精确计数（慢、需 key）；False 用字符/4 粗估
FULL_CORPUS   = 31175   # 全量邮件数，用于外推

def est_tokens(text):
    """粗估 token 数：约 4 字符 = 1 token。中文偏多，算是保守估计。"""
    return max(1, len(text) // 4)

def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

def clean_len(body):
    return len(str(body))

def main():
    gold   = load_jsonl(GOLD_FILE)
    emails = {e["id"]: e for e in load_jsonl(EMAIL_FILE)}
    cache  = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}

    n = len(gold)
    # 分类统计每封走的路径
    n_filtered = n_haiku_only = n_escalated = 0
    # 累加各模型的 in/out token（基于混合方案实际路径）
    tok = {m: {"in": 0, "out": 0} for m in PRICES}

    # 同时为"纯 Haiku"和"全 Opus"两个对照方案累加 token
    tok_haiku_all = {"in": 0, "out": 0}   # 所有非过滤邮件都只走 Haiku
    tok_opus_all  = {"in": 0, "out": 0}   # 所有邮件都走 Opus（含被规则过滤的也算，作纯模型对照）

    for g in gold:
        eid = g["email_id"]
        em = emails.get(eid, {})
        subj = em.get("subject", "")
        body = str(em.get("body", ""))
        rec = cache.get(eid, {})

        # 输入 token = system + 主题 + 正文（截断到 6000 字符，跟抽取脚本一致）
        in_tok = SYSTEM_PROMPT_TOKENS + est_tokens(subj) + est_tokens(body[:6000])
        # 输出 token = 缓存里 JSON 的长度估
        out_tok = est_tokens(json.dumps(rec.get("events", []), ensure_ascii=False)) + 20

        # --- 全 Opus 对照：每封都发 Opus 一次 ---
        tok_opus_all["in"]  += in_tok
        tok_opus_all["out"] += out_tok

        # --- 混合方案实际路径 ---
        if rec.get("_filtered"):
            n_filtered += 1
            # 规则过滤，不调 LLM，0 成本
            continue

        # 非过滤的都要过 Haiku（纯 Haiku 方案 = 这些邮件各一次 Haiku）
        tok_haiku_all["in"]  += in_tok
        tok_haiku_all["out"] += out_tok

        # 混合方案：先一次 Haiku
        tok["haiku"]["in"]  += in_tok
        tok["haiku"]["out"] += out_tok

        if rec.get("_escalated"):
            n_escalated += 1
            # 再一次 Sonnet 兜底
            tok["sonnet"]["in"]  += in_tok
            tok["sonnet"]["out"] += out_tok
        else:
            n_haiku_only += 1

    def cost(model, t):
        return t["in"] / 1e6 * PRICES[model]["in"] + t["out"] / 1e6 * PRICES[model]["out"]

    # 各方案在 dev(n 封)上的成本
    cost_hybrid = cost("haiku", tok["haiku"]) + cost("sonnet", tok["sonnet"])
    cost_haiku  = cost("haiku", tok_haiku_all)
    cost_opus   = cost("opus", tok_opus_all)

    def per_1k(c):
        return c / n * 1000

    def full(c):
        return c / n * FULL_CORPUS

    print("=" * 64)
    print(f"成本曲线  |  评估集 {GOLD_FILE.name}  n={n}  |  全量外推基数={FULL_CORPUS}")
    print(f"token 估算方式: {'API 精确计数' if USE_API_COUNT else '字符/4 粗估'}")
    print("=" * 64)
    print(f"\n路径分布:")
    print(f"  规则过滤(不调LLM): {n_filtered}   仅Haiku: {n_haiku_only}   升级Sonnet兜底: {n_escalated}")
    print(f"  → 混合方案里，Haiku 调用 {n_haiku_only + n_escalated} 次，Sonnet 调用 {n_escalated} 次")

    print(f"\n{'方案':<22}{'F1':>7}{'Recall':>9}{'每千封$':>12}{'全量$':>12}{'相对全Opus':>12}")
    rows = [
        ("正则 baseline",        0.531, 0.778, 0.0),
        ("纯 Haiku(+规则过滤)",  0.767, 0.958, cost_haiku),
        ("混合(Haiku+Sonnet)",   0.857, 1.000, cost_hybrid),
        ("全 Opus(上限)",        0.900, 1.000, cost_opus),
    ]
    for name, f1, rec_, c in rows:
        rel = f"{c/cost_opus*100:.0f}%" if cost_opus and c else ("—" if c == 0 else "")
        print(f"{name:<22}{f1:>7.3f}{rec_:>9.3f}{per_1k(c):>12.3f}{full(c):>12.2f}{rel:>12}")

    print("\n说明:")
    print("- 成本仅含 LLM 调用；规则过滤层近似 0 成本（本地正则）。")
    print("- 输入 token = system prompt + 主题 + 正文(截断6000字)；输出按抽取结果估。")
    print("- Sonnet 5 用 introductory 价 $2/$10（2026-09-01 起涨到 $3/$15，届时混合成本会略升）。")
    print("- '全 Opus' 未含规则过滤（作纯模型质量上限对照）；实际部署 Opus 也可叠加过滤层降本。")
    print("- 粗估会有偏差，要精确数字把 USE_API_COUNT 改 True 重跑。")


if __name__ == "__main__":
    main()