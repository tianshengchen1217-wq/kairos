#!/usr/bin/env python3
"""
extract_llm.py  —  Kairos 混合抽取（规则过滤 + Haiku 主力 + Sonnet 兜底）

四道门：
  ① 规则前置过滤：Re: 往返对话 / 收据(无续期日) / Gmail促销 / 促销词 → 判负，不调 LLM
  ② Haiku 抽取（带 prefill）→ 判正则采信
  ③ 时间表达探测：无 → 采信负；绝对日期全在过去 → 采信负；否则升级
  ④ Sonnet 兜底复核（无 prefill）

消融实验：ABLATION_PURE_LLM=True 时关掉所有规则层，只用 prompt + 单模型，
         用于测量"纯 LLM 能力"作为对照。
"""

import os, re, sys, json, time, html
from pathlib import Path
from collections import defaultdict
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, date

import anthropic

# ------------------------------------------------------------------ 配置
ROOT       = Path(__file__).resolve().parent.parent
DATA       = ROOT / "data"
GOLD_FILE  = DATA / "dev.jsonl"        # 对照实验用 dev；最终无偏结果用 test
EMAIL_FILE = DATA / "sample.jsonl"
CACHE_FILE = DATA / "llm_cache.json"

# ===== 消融开关 =====
ABLATION_PURE_LLM = False   # True = 关掉门①/③/④和切片，只用 prompt + 单模型
USE_PREFILL       = True    # Haiku 支持 prefill；Opus / Sonnet 不支持，跑它们时改 False
# ===================

MODEL          = "claude-haiku-4-5-20251001"
ESCALATE_MODEL = "claude-sonnet-5"
MAX_TOKENS     = 1024

SLICE_MAX, SLICE_HEAD, SLICE_WIN = 3000, 800, 300

# 单价 USD / 每百万 token（2026-08；Sonnet 5 为 introductory 价）
PRICE = {
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0},
    "claude-sonnet-5":           {"in": 2.0, "out": 10.0},
    "claude-opus-4-8":           {"in": 5.0, "out": 25.0},
}

JOIN_KEY_EMAIL, JOIN_KEY_GOLD = "id", "email_id"
FORCE_BODY_KEY, FORCE_DATE_KEY = "body", "internal_date"

# ------------------------------------------------------------------ prompt
SYSTEM_PROMPT = """你是一个邮件时间承诺抽取器。给你一封邮件和它的发送日期，判断其中是否含有“时间承诺”，并抽取事件。
注意：正文可能是切片后的片段，用 "..." 表示中间省略了无关内容。

【第一步：先过排除门。命中任意一条，立即返回 {"has_commitment": false, "events": []}，不要进入后续抽取。】
A. 收据 / 付款凭证（"Apple 提供的收据""Your receipt from X""Receipt for …"）：
   - 已发生的那笔交易本身不是承诺，其购买日期一律不抽。
   - **但若正文中写明了未来的续期/扣款日**（如"2022年12月01日续期""renews on Dec 1""Next billing date: 2024-11-02"），
     这是一次将要发生的自动扣款，必须抽取：has_commitment=true，type=billing，datetime 取该续期日。
   - 注意区分：收据顶部的"日期: YYYY年MM月DD日"是本次交易日期，属于已发生，不抽。
     若正文只有商品类型描述（如"VIP会员(自动续期) 订阅续期"）而无具体未来日期，判负。
   - 若收据中没有任何未来续期日，才判负。
B. 纯促销 / 营销：打折、大促、deals、sale、% off、Black Friday、clearance、bonus points、miles 等。
   即使带"ends today / expires tomorrow / last chance"也判负——那是促销截止，不是用户的权益或行动承诺。
   营销邮件里顺带提及的会员到期日也判负；只有专门的到期提醒才算 deadline。
C. 已取消 / 已完成 / 已送达 / 请求被拒（cancelled / declined / delivered / completed / 已取消 / 已送达）。

【第二步：排除门没命中，再判是否为时间承诺 has_commitment=true。必须同时满足：】
1. 未来：时间点晚于发送日期（含当天）。发送日之前的日期一律不算。
2. 与用户相关：是收件人本人需要知道或行动的事，不是泛泛通知或广告。
   多事件排班表（社区活动、餐车档期、课程表）属泛泛通知，判负。
3. 唯一确定的时间点：能落到某一天（或某天某时刻）。

【抽 / 不抽】
- 可推算的单一时长要抽："in 5 days" → 发送日 + 5 天，"within one week" → 发送日 + 7 天，"by Friday" → 对应那天。
- 订阅确认类：若给出订阅起始日和计费周期（如"自2021年2月7日起，以¥12.00/月自动续期"），
  推算首次扣款日 = 起始日 + 一个周期，抽为 billing。只抽首次，不抽后续循环。
- 区间不抽："4–6 business days""1–2 weeks""24-48 hours"。
- 模糊不抽："soon""shortly""immediately""as soon as possible"。

【变更类邮件】主题含 Update / Changed / Rescheduled / Modified / 变更 / 改期 / 已更新 时，
正文中常出现新旧两个时间并排（例如 "2 guests · 20:30  2 guests · 20:00"，
原本旧值带删除线，转纯文本后格式丢失）。
此时抽取**生效的新值**——通常是后出现的那个，而非前面已作废的旧值。

【type 归类】
- 自动扣款、账单续费、会员到期自动续、收据中的续期日 → billing
- 需用户主动行动才生效（交表、提交材料、预约、申请截止、激活账户、手动付款）→ deadline
- 快递 / 订单送达（未来的送达日或发货日）→ delivery
- 预约 / 面谈 / 活动 / 订位（有具体时间）→ appointment
- 账单类判别：写明 auto pay / automatically debited → billing；只给 due date 要你去付 → deadline；
  只有余额、无任何日期 → 判负。

【邮件线程】只看最新一层。忽略被 ">" 或 "On … wrote:" 引用的历史内容里的日期。

【输出】严格只输出 JSON，无任何多余文字、无 markdown 代码块：
{"has_commitment": true, "events": [{"type": "...", "datetime": "YYYY-MM-DD 或 YYYY-MM-DD HH:MM", "title": "简短中文描述"}]}

【title 写法】必须让用户在日历里一眼认出是什么，不能只写通用词。
- billing：写「商品/服务名 + 计费周期 + 金额」，如「芒果TV 连续包月 ¥18」「Verizon 账单 $60.50」
  绝不能只写「订阅续期」「自动扣款」——同一天可能有多个不同订阅，无法区分。
- delivery：写「商家 + 商品」，如「Apple USB-C 充电线送达」「Walmart 矿泉水送达」
- appointment：写「地点/机构 + 事项」，如「Rata 餐厅订位 2人」「UC Berkeley 校园参观」
- deadline：写「要做的事 + 主体」，如「提交 Duolingo 成绩（UCSB 申请）」
一封邮件含多个事件时，各条 title 必须能相互区分。

多个事件按 datetime 从早到晚排列。无事件时 has_commitment=false 且 events=[]。"""

# ------------------------------------------------------------------ 清洗
def clean_body(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(l.strip() for l in text.split("\n")).strip()

def clean_subject(subject):
    """剥掉 [Xxx] 类邮件列表/工单前缀，让下游主题规则能正常匹配。"""
    return re.sub(r"^\s*(?:\[[^\]]{1,30}\]\s*)+", "", subject or "").strip()

# ------------------------------------------------------------------ 时间表达
MONTHS = {m: i for i, m in enumerate(
    ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1)}

REL_DATE = re.compile(r"\b(?:today|tomorrow|明天|后天|"
                      r"mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)

ABS_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), "ymd"),
    (re.compile(r"(\d{1,2})[/](\d{1,2})[/](\d{4})"), "mdy"),
    (re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "Mdy"),
    (re.compile(r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(\d{4})", re.I), "dMy"),
    (re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"), "ymd"),
]

PARTIAL_DATE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
    r"|\d{1,2}\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"|\d{1,2}月\d{1,2}日", re.I)

DURATION = re.compile(
    r"\b(?:within|in|after|before|by)\s+(?:the\s+)?(?:next\s+)?"
    r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple|few|several)\s*"
    r"(?:-|–|to|or)?\s*(?:\d+)?\s*"
    r"(?:business\s+)?(?:day|days|week|weeks|month|months|year|years|hour|hours)\b"
    r"|\b(?:day|days|week|weeks|month|months)\s+from\s+(?:now|today|receipt)\b"
    r"|\d+\s*(?:天|日|周|个?月|年)\s*(?:之?内|以内|后)"
    r"|[一二三四五六七八九十两]\s*(?:天|日|周|个?月|年)\s*(?:之?内|以内|后)"
    r"|\b(?:end\s+of\s+(?:the\s+)?(?:day|week|month|year|semester))\b", re.I)

TIME_PATTERNS = (REL_DATE, PARTIAL_DATE, DURATION)

def parse_abs_dates(text):
    out = []
    for pat, kind in ABS_PATTERNS:
        for m in pat.finditer(text):
            try:
                if kind == "ymd":   y, mo, d = int(m[1]), int(m[2]), int(m[3])
                elif kind == "mdy": mo, d, y = int(m[1]), int(m[2]), int(m[3])
                elif kind == "Mdy": mo, d, y = MONTHS[m[1][:3].lower()], int(m[2]), int(m[3])
                else:               d, mo, y = int(m[1]), MONTHS[m[2][:3].lower()], int(m[3])
                out.append(date(y, mo, d))
            except Exception:
                continue
    return out

def should_escalate(text, send_date):
    has_rel      = bool(REL_DATE.search(text))
    has_partial  = bool(PARTIAL_DATE.search(text))
    has_duration = bool(DURATION.search(text))
    abs_dates    = parse_abs_dates(text)
    if not (has_rel or has_partial or has_duration or abs_dates):
        return False, "no_date"
    if has_rel or has_partial or has_duration:
        return True, "rel_or_duration"
    if send_date and abs_dates and all(d < send_date for d in abs_dates):
        return False, "all_dates_past"
    return True, "future_date"

# ------------------------------------------------------------------ 切片
def slice_body(text, max_chars=SLICE_MAX, head_chars=SLICE_HEAD, window=SLICE_WIN):
    if len(text) <= head_chars:
        return text
    spans = [(0, head_chars)]
    for pat in TIME_PATTERNS:
        for m in pat.finditer(text):
            spans.append((max(0, m.start()-window), min(len(text), m.end()+window)))
    for pat, _ in ABS_PATTERNS:
        for m in pat.finditer(text):
            spans.append((max(0, m.start()-window), min(len(text), m.end()+window)))
    spans.sort()
    merged = [spans[0]]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out, used = [], 0
    for s, e in merged:
        piece = text[s:e]
        if used + len(piece) > max_chars:
            continue
        out.append(piece); used += len(piece)
    sliced = "\n...\n".join(out)
    return sliced if sliced else text[:head_chars]

# ------------------------------------------------------------------ 门① 规则前置过滤
REPLY_PAT   = re.compile(r"^\s*(?:re|fwd|fw)\s*:", re.I)
RECEIPT_PAT = re.compile(r"收据|your receipt|receipt for|payment confirmation", re.I)

RENEW_IN_RECEIPT = re.compile(
    r"\d{4}年\d{1,2}月\d{1,2}日续期|renews?\s+on|renewal date|next billing date|连续包[月周年]", re.I)

PROMO_ESCAPE = re.compile(
    r"reminder|appointment|reservation|booking|confirm|order|delivery|"
    r"shipped|scheduled|coming up|预约|订单|配送|确认|提醒", re.I)

PROMO_PAT = re.compile(
    r"black friday|flash sale|% off|\bdeals?\b|clearance|sale ends|"
    r"limited[- ]time|save \$|\d+% |\bmiles\b|超值|促销|大促|折扣|秒杀|限时"
    r"|is here|are here|new releases?|lineup"
    r"|as low as|starting at|\$\d+\s*(?:off|/month)"
    r"|don'?t miss|last chance|gift of|drop is here"
    r"|claim your reward|reward is waiting|rewards? back|bonus (?:miles|points)|weekly perks",
    re.I)

def pre_filter(subject, body, labels=None):
    subject = clean_subject(subject)
    if REPLY_PAT.search(subject):
        return "reply_thread"
    if RECEIPT_PAT.search(f"{subject}\n{body[:500]}"):
        if not RENEW_IN_RECEIPT.search(body):
            return "receipt"
        return None
    if labels and "CATEGORY_PROMOTIONS" in labels:
        if not PROMO_ESCAPE.search(subject):
            return "gmail_promo"
    if PROMO_PAT.search(subject):
        return "promo"
    return None

# ------------------------------------------------------------------ 工具
def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

def parse_send_date(v):
    if v is None: return None
    if isinstance(v, (int, float)): v = str(int(v))
    v = str(v).strip()
    if v.isdigit():
        n = int(v)
        if len(v) >= 13: n //= 1000
        return datetime.fromtimestamp(n, tz=timezone.utc).date()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m: return date(int(m[1]), int(m[2]), int(m[3]))
    try: return parsedate_to_datetime(v).date()
    except Exception: return None

def event_day(ev):
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(ev.get("datetime", "")))
    return m.group(1) if m else None

def earliest(events):
    ds = sorted([e for e in events if event_day(e)], key=event_day)
    return ds[0] if ds else None

def extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = text.find("{"), text.rfind("}")
    if i == -1 or j == -1: raise ValueError("no json object")
    return json.loads(text[i:j+1])

# ------------------------------------------------------------------ 主流程
def main():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("缺 ANTHROPIC_API_KEY")

    gold   = load_jsonl(GOLD_FILE)
    emails = {e[JOIN_KEY_EMAIL]: e for e in load_jsonl(EMAIL_FILE)}
    BODY_KEY, DATE_KEY = FORCE_BODY_KEY, FORCE_DATE_KEY
    n_pos = sum(1 for g in gold if g.get("has_commitment"))

    mode = "消融：纯 LLM（无规则层）" if ABLATION_PURE_LLM else "完整架构（规则+兜底）"
    print(f"模式: {mode}")
    print(f"主模型: {MODEL}   prefill: {USE_PREFILL}")
    if not ABLATION_PURE_LLM:
        print(f"兜底模型: {ESCALATE_MODEL}")
    print(f"评估集 {GOLD_FILE.name}  n={len(gold)}  正样本 {n_pos} ({n_pos/len(gold):.1%})")
    print("-" * 62)

    cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    client = anthropic.Anthropic()

    def ask_model(model_name, user_text, use_prefill=True):
        if use_prefill:
            msgs = [{"role": "user", "content": user_text},
                    {"role": "assistant", "content": "{"}]
            prefix = "{"
        else:
            msgs = [{"role": "user", "content": user_text +
                     "\n\n只输出 JSON，不要任何其它文字，不要 markdown。"}]
            prefix = ""
        for attempt in range(4):
            try:
                resp = client.messages.create(
                    model=model_name, max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT, messages=msgs)
                raw = prefix + "".join(b.text for b in resp.content if b.type == "text")
                parsed = extract_json(raw)
                parsed.setdefault("events", [])
                parsed["has_commitment"] = bool(parsed.get("has_commitment"))
                parsed["_usage"] = {"model": model_name,
                                    "in": resp.usage.input_tokens,
                                    "out": resp.usage.output_tokens}
                return parsed
            except (anthropic.RateLimitError, anthropic.APIStatusError,
                    anthropic.APIConnectionError):
                time.sleep(3 * (attempt + 1))
            except Exception as e:
                if attempt == 3:
                    return {"has_commitment": False, "events": [], "_error": str(e)[:120]}
                time.sleep(1)
        return {"has_commitment": False, "events": [], "_error": "retries_exhausted"}

    def call(rec):
        eid = rec[JOIN_KEY_GOLD]
        if eid in cache:
            return cache[eid]
        em = emails.get(eid)
        if em is None:
            return {"has_commitment": False, "events": [], "_error": "not_in_sample"}

        # ① 规则前置过滤（消融模式跳过）
        if not ABLATION_PURE_LLM:
            hit = pre_filter(em.get("subject", ""), str(em.get(BODY_KEY, "")), em.get("labels"))
            if hit:
                result = {"has_commitment": False, "events": [], "_filtered": hit}
                cache[eid] = result
                CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                return result

        send = parse_send_date(em.get(DATE_KEY))
        cleaned = clean_body(str(em.get(BODY_KEY, "")))
        # 消融模式不切片，按同样长度上限截断，保证输入量可比
        body = cleaned[:SLICE_MAX] if ABLATION_PURE_LLM else slice_body(cleaned)
        user_text = (f"【发送日期】{send}\n【主题】{em.get('subject','')}\n【正文】\n{body}")

        # ② 主模型
        result = ask_model(MODEL, user_text, use_prefill=USE_PREFILL)
        usages = [result.get("_usage")] if result.get("_usage") else []

        # ③④ 兜底（消融模式跳过）
        if not ABLATION_PURE_LLM and not result.get("has_commitment"):
            do_esc, reason = should_escalate(body, send)
            result["_gate3"] = reason
            if do_esc:
                esc = ask_model(ESCALATE_MODEL, user_text, use_prefill=False)
                if esc.get("_usage"):
                    usages.append(esc["_usage"])
                esc["_escalated"] = True
                esc["_gate3"] = reason
                result = esc

        result["_usages"] = [u for u in usages if u]
        if not result.get("_error"):
            cache[eid] = result
            CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        return result

    tp = fp = fn = tn = 0
    date_hit = date_tot = type_hit = parse_err = 0
    fn_list, fp_list = [], []
    tok = defaultdict(lambda: {"in": 0, "out": 0})
    gate3, gate1 = {}, {}

    for i, g in enumerate(gold, 1):
        pred = call(g)
        if pred.get("_error"): parse_err += 1
        for u in pred.get("_usages", []):
            tok[u["model"]]["in"]  += u["in"]
            tok[u["model"]]["out"] += u["out"]
        if pred.get("_gate3"):
            gate3[pred["_gate3"]] = gate3.get(pred["_gate3"], 0) + 1
        if pred.get("_filtered"):
            gate1[pred["_filtered"]] = gate1.get(pred["_filtered"], 0) + 1

        g_pos, p_pos = bool(g.get("has_commitment")), bool(pred.get("has_commitment"))
        subj = emails.get(g[JOIN_KEY_GOLD], {}).get("subject", "")[:65]
        if g_pos and p_pos:
            tp += 1
            gd, pd = earliest(g.get("events", [])), earliest(pred.get("events", []))
            if gd:
                date_tot += 1
                if pd and event_day(gd) == event_day(pd): date_hit += 1
            gt = (g["events"][0] if g.get("events") else {}).get("type")
            pt = (sorted(pred["events"], key=event_day)[0] if pred.get("events") else {}).get("type")
            if gt and gt == pt: type_hit += 1
        elif not g_pos and p_pos:
            fp += 1; fp_list.append(subj)
        elif g_pos and not p_pos:
            fn += 1; fn_list.append(subj)
        else:
            tn += 1
        if i % 25 == 0: print(f"  ...{i}/{len(gold)}")

    P = tp/(tp+fp) if tp+fp else 0
    R = tp/(tp+fn) if tp+fn else 0
    F1 = 2*P*R/(P+R) if P+R else 0
    cost = sum(tok[m]["in"]/1e6*PRICE.get(m,{}).get("in",0) +
               tok[m]["out"]/1e6*PRICE.get(m,{}).get("out",0) for m in tok)

    print("\n" + "=" * 62)
    print(f"【{mode}】{MODEL}" + ("" if ABLATION_PURE_LLM else f" + {ESCALATE_MODEL}"))
    print(f"{GOLD_FILE.name}  n={len(gold)}")
    print(f"TP {tp}  FP {fp}  FN {fn}  TN {tn}   解析失败 {parse_err}")
    print(f"Precision {P:.3f}   Recall {R:.3f}   F1 {F1:.3f}")
    print(f"    v2 gold 对照 — baseline(regex): P 0.668 / R 0.847 / F1 0.747")
    if date_tot:
        print(f"Date acc {date_hit}/{date_tot}={date_hit/date_tot:.3f}   "
              f"Type acc {type_hit}/{tp}={type_hit/tp:.3f}")
    if not ABLATION_PURE_LLM:
        print(f"\n门①过滤: {sum(gate1.values())}  明细 {gate1}")
        print(f"门③分流: {gate3}")
    print(f"\n=== 真实 token ===")
    for m in tok:
        c = tok[m]["in"]/1e6*PRICE.get(m,{}).get("in",0) + tok[m]["out"]/1e6*PRICE.get(m,{}).get("out",0)
        print(f"  {m}: in {tok[m]['in']:,}  out {tok[m]['out']:,}  = ${c:.4f}")
    print(f"  合计 ${cost:.4f}  |  外推31175封 ${cost/len(gold)*31175:.2f}")
    print(f"\nFALSE NEGATIVES — {fn}")
    for s in fn_list: print("  ·", s)
    print(f"\nFALSE POSITIVES — {fp}")
    for s in fp_list: print("  ·", s)

if __name__ == "__main__":
    main()