"""
抽取器 · 四道门管线的服务器入口
所有门逻辑/prompt/正则 import 自 scripts/extract_llm.py —— 单一事实来源,
scripts 里调 prompt,这里自动同步。本文件只做两件事:
  1. 重实现 ask_model(原版是 main() 里的闭包,无法 import)
  2. extract_email():单封邮件 → 裁决(带门位标注,供 extraction_log 用)
"""
import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env")

import extract_llm as X          # 四道门的单一事实来源

_client = None
def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def ask_model(model_name: str, user_text: str, use_prefill: bool = True) -> dict:
    """与 extract_llm.main() 内的闭包同逻辑:prefill 可选,重试,真实 usage。"""
    if use_prefill:
        msgs = [{"role": "user", "content": user_text},
                {"role": "assistant", "content": "{"}]
        prefix = "{"
    else:
        msgs = [{"role": "user", "content": user_text +
                 "\n\n只输出 JSON,不要任何其它文字,不要 markdown。"}]
        prefix = ""
    for attempt in range(4):
        try:
            resp = client().messages.create(
                model=model_name, max_tokens=X.MAX_TOKENS,
                system=X.SYSTEM_PROMPT, messages=msgs)
            raw = prefix + "".join(b.text for b in resp.content if b.type == "text")
            parsed = X.extract_json(raw)
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


def extract_email(email: dict) -> dict:
    """
    单封邮件过四道门。
    输入:fetch_new_messages 产出的 dict(id/subject/body/labels/internal_date)
    输出:{
      has_commitment, events,
      gate:  终审门位 rule_filter | haiku | time_probe | sonnet,
      rule_hit / gate3_reason / usages / error
    }
    """
    subject = email.get("subject", "")
    body_raw = str(email.get("body", ""))
    labels = email.get("labels")

    # 门①
    hit = X.pre_filter(subject, body_raw, labels)
    if hit:
        return {"has_commitment": False, "events": [],
                "gate": "rule_filter", "rule_hit": hit, "usages": []}

    send = X.parse_send_date(email.get("internal_date"))
    body = X.slice_body(X.clean_body(body_raw))
    user_text = f"【发送日期】{send}\n【主题】{subject}\n【正文】\n{body}"

    # 门②
    result = ask_model(X.MODEL, user_text, use_prefill=X.USE_PREFILL)
    usages = [result["_usage"]] if result.get("_usage") else []
    gate = "haiku"

    # 门③④
    if not result.get("has_commitment"):
        do_esc, reason = X.should_escalate(body, send)
        if do_esc:
            esc = ask_model(X.ESCALATE_MODEL, user_text, use_prefill=False)
            if esc.get("_usage"):
                usages.append(esc["_usage"])
            result, gate = esc, "sonnet"
        else:
            gate = "time_probe"
        result["_gate3"] = reason

    return {"has_commitment": bool(result.get("has_commitment")),
            "events": result.get("events", []),
            "gate": gate,
            "rule_hit": None,
            "gate3_reason": result.get("_gate3"),
            "usages": usages,
            "error": result.get("_error")}


if __name__ == "__main__":
    # 冒烟测试:拉近 2 天真实邮件,前 6 封过管线,只打印不落库
    import gmail_client as gc
    msgs, _ = gc.fetch_new_messages(bootstrap_days=2)
    print(f"取 {min(6, len(msgs))}/{len(msgs)} 封过四道门:\n")
    for m in msgs[:6]:
        v = extract_email(m)
        tag = f"[{v['gate']}" + (f":{v['rule_hit']}" if v["rule_hit"] else "") + "]"
        print(f"{tag:28s} {'✓正' if v['has_commitment'] else '·负'}  {m['subject'][:48]}")
        for ev in v["events"]:
            print(f"{'':30s}→ {ev.get('datetime')}  {ev.get('type')}  {ev.get('title')}")
    print("\n✓ 管线在服务器环境复活")