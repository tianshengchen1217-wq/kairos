"""
Kairos — 正则 Baseline + 评估框架

这是所有后续方案的对照组。
predict() 是唯一需要替换的函数，评估逻辑保持不变。

v2 规范适配：收据类不再一票否决——含未来续期日的是 billing 正样本。
中英文对等处理，不依赖数据分布的偶然性。
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

DEV_FILE = Path("data/dev.jsonl")
SAMPLE_FILE = Path("data/sample.jsonl")


# ── 日期模式 ──────────────────────────────────────────────────

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

DATE_PATTERNS = [
    # 09/21/2022  ·  9-21-22
    (r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", "mdy"),
    # 2022-09-21
    (r"\b(\d{4})-(\d{2})-(\d{2})\b", "ymd"),
    # September 21, 2022  ·  Sep 21 2022
    (r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b", "mdy_word"),
    # 21 September 2022
    (r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", "dmy_word"),
    # 2022年9月21日
    (r"(\d{4})年(\d{1,2})月(\d{1,2})日", "cn"),
    # 9月21日（缺年份）
    (r"(\d{1,2})月(\d{1,2})日", "cn_noyear"),
]

# 触发词：这些词附近的日期更可能是真承诺
TRIGGERS = [
    r"due", r"renew", r"expir", r"payment date", r"deliver", r"arriv",
    r"appointment", r"scheduled", r"deadline", r"check-?in", r"pickup",
    r"续期", r"到期", r"入住", r"截止",
]

# 否定词：出现即判负
# 注意：receipt 已从此表移出——v2 规范下收据不再无条件判负，见 RECEIPT_PAT
NEGATIVES = [
    r"cancel(l)?ed", r"has been delivered", r"was delivered",
    r"refund(ed)?", r"已取消", r"已停止", r"unsubscribe preferences",
]

# 收据 / 发票类：v2 规范下含未来续期日的是 billing 正样本，不能一票否决。
# 中英文对等——任一语言的收据走同一条逻辑，避免因数据分布偶然性而"碰巧正确"。
RECEIPT_PAT = re.compile(r"receipt|收据|发票|invoice", re.I)
RENEW_PAT = re.compile(
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*续期"   # 2024年05月15日续期
    r"|renews?\s+on"                                      # renews on Dec 1
    r"|renewal\s+(?:date|price)"                          # renewal date / price
    r"|next\s+billing\s+date"                             # Next billing date: 2024-11-02
    r"|续期价格|自动续期|连续包[月周年]",
    re.I,
)


def parse_date(match, kind, ref_year):
    """把正则捕获组转成 date 对象，失败返回 None"""
    try:
        g = match.groups()
        if kind == "mdy":
            m, d, y = int(g[0]), int(g[1]), int(g[2])
            y = y + 2000 if y < 100 else y
        elif kind == "ymd":
            y, m, d = int(g[0]), int(g[1]), int(g[2])
        elif kind == "mdy_word":
            m = MONTHS.get(g[0][:3].lower())
            d, y = int(g[1]), int(g[2])
        elif kind == "dmy_word":
            d = int(g[0])
            m = MONTHS.get(g[1][:3].lower())
            y = int(g[2])
        elif kind == "cn":
            y, m, d = int(g[0]), int(g[1]), int(g[2])
        elif kind == "cn_noyear":
            m, d, y = int(g[0]), int(g[1]), ref_year
        else:
            return None
        if not m or not (1 <= m <= 12) or not (1 <= d <= 31):
            return None
        return datetime(y, m, d)
    except (ValueError, TypeError):
        return None


# ── 预测函数（这是唯一要替换的部分）────────────────────────────

def predict(email: dict) -> dict:
    """正则 baseline：找日期 → 排除否定 → 要求触发词邻近"""
    text = f"{email['subject']}\n{email['body'][:4000]}"
    sent = datetime.fromtimestamp(int(email["internal_date"]) / 1000)

    # 否定词直接判负
    for pat in NEGATIVES:
        if re.search(pat, text, re.I):
            return {"has_commitment": False, "events": []}

    # 收据类：无未来续期日 → 判负；有续期日则放行，交给下面的日期规则
    if RECEIPT_PAT.search(text) and not RENEW_PAT.search(text):
        return {"has_commitment": False, "events": []}

    candidates = []
    for pat, kind in DATE_PATTERNS:
        for m in re.finditer(pat, text, re.I):
            dt = parse_date(m, kind, sent.year)
            if not dt:
                continue
            # 必须是未来（允许当天）
            if dt < sent - timedelta(days=1):
                continue
            # 太远的大概率是噪音
            if dt > sent + timedelta(days=400):
                continue
            # 附近 120 字符内要有触发词
            window = text[max(0, m.start() - 120): m.end() + 120]
            if not any(re.search(t, window, re.I) for t in TRIGGERS):
                continue
            candidates.append(dt)

    if not candidates:
        return {"has_commitment": False, "events": []}

    best = min(candidates)   # 取最早的未来日期
    return {
        "has_commitment": True,
        "events": [{
            "type": "billing",                  # baseline 不做类型判断
            "datetime": best.strftime("%Y-%m-%d"),
            "title": email["subject"][:60],
        }],
    }


# ── 评估 ──────────────────────────────────────────────────────

def load_jsonl(path):
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def evaluate(gold_file: Path):
    gold = load_jsonl(gold_file)
    emails = {e["id"]: e for e in load_jsonl(SAMPLE_FILE)}

    tp = fp = fn = tn = 0
    date_hit = date_total = 0
    errors = {"fp": [], "fn": [], "date": []}

    for g in gold:
        email = emails.get(g["email_id"])
        if not email:
            continue

        pred = predict(email)
        truth = g["has_commitment"]
        guess = pred["has_commitment"]

        if guess and truth:
            tp += 1
            # 日期是否抽对
            gd = (g["events"][0].get("datetime") or "")[:10]
            pd = pred["events"][0]["datetime"][:10]
            date_total += 1
            if gd == pd:
                date_hit += 1
            else:
                errors["date"].append((email["subject"][:50], gd, pd))
        elif guess and not truth:
            fp += 1
            errors["fp"].append(email["subject"][:60])
        elif not guess and truth:
            fn += 1
            errors["fn"].append(email["subject"][:60])
        else:
            tn += 1

    p = tp / (tp + fp) if tp + fp else 0
    r = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * p * r / (p + r) if p + r else 0
    acc = (tp + tn) / len(gold)

    print("=" * 58)
    print(f"BASELINE (regex)  —  {gold_file.name}, n={len(gold)}")
    print("=" * 58)
    print(f"  TP {tp:3d}   FP {fp:3d}   FN {fn:3d}   TN {tn:3d}")
    print()
    print(f"  Precision  {p:.3f}")
    print(f"  Recall     {r:.3f}")
    print(f"  F1         {f1:.3f}")
    print(f"  Accuracy   {acc:.3f}   ← 注意它有多具欺骗性")
    if date_total:
        print(f"\n  Date accuracy (on TP)  {date_hit}/{date_total} = {date_hit/date_total:.3f}")

    print("\n" + "-" * 58)
    print(f"FALSE POSITIVES (说是，其实不是) — {len(errors['fp'])}")
    for s in errors["fp"][:10]:
        print(f"  · {s}")

    print(f"\nFALSE NEGATIVES (漏掉的真承诺) — {len(errors['fn'])}")
    for s in errors["fn"][:10]:
        print(f"  · {s}")

    if errors["date"]:
        print(f"\nDATE MISMATCH — {len(errors['date'])}")
        for s, gd, pd in errors["date"][:10]:
            print(f"  · {s}\n      gold={gd}  pred={pd}")


if __name__ == "__main__":
    evaluate(DEV_FILE)