"""
落库层:裁决 → 日历事件
dedup 的 build_key / 合并语义 import 自 scripts/dedup_test.py(单一事实来源),
本文件只把 apply_event 的四场景翻译成 SQL 操作。
已知差异:管线 prompt 把"已取消"判为负例,取消场景暂无触发路径 —— 记入 TODO。
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import dedup_test as D            # build_key / CYCLIC_TYPES
import extractor
import gmail_client as gc
import db


def _merge_into_db(conn, user_id: int, email: dict, ev: dict, key: str):
    """四场景合并,DB 版 apply_event。返回 (action, event_id)。"""
    nd = (ev.get("datetime") or "")[:10]
    typ = ev.get("type", "other")
    dom = D.sender_domain(email.get("sender", ""))
    today = date.today().isoformat()

    rows = conn.execute(
        "SELECT id, datetime, type FROM events "
        "WHERE user_id=? AND dedup_key=? AND status='active' ORDER BY datetime",
        (user_id, key)).fetchall()

    def _update(row_id, action):
        conn.execute(
            "UPDATE events SET datetime=?, title=?, type=?, email_id=?, "
            "updated_at=datetime('now') WHERE id=?",
            (ev["datetime"], ev.get("title", ""), typ, email["id"], row_id))
        return action, row_id

    if not rows:
        cur = conn.execute(
            "INSERT INTO events (user_id, email_id, dedup_key, type, title, "
            "datetime, source_domain) VALUES (?,?,?,?,?,?,?)",
            (user_id, email["id"], key, typ, ev.get("title", ""),
             ev["datetime"], dom))
        return "new", cur.lastrowid

    same = next((r for r in rows if (r["datetime"] or "")[:10] == nd), None)
    if same:                                     # 场景:同日期 → 静默覆盖
        return _update(same["id"], "silent_overwrite")

    if typ not in D.CYCLIC_TYPES:                # 一次性事件 → 改期覆盖
        return _update(rows[-1]["id"], "overwrite_notify")

    pending = [r for r in rows if (r["datetime"] or "")[:10] >= today]
    if pending:                                  # billing 未到期 → 改期覆盖
        return _update(pending[0]["id"], "overwrite_notify")

    cur = conn.execute(                          # billing 上期已过 → 新增一期
        "INSERT INTO events (user_id, email_id, dedup_key, type, title, "
        "datetime, source_domain) VALUES (?,?,?,?,?,?,?)",
        (user_id, email["id"], key, typ, ev.get("title", ""),
         ev["datetime"], dom))
    return "new_cycle", cur.lastrowid


def process_new(user_id: int = 1, bootstrap_days: int = 7,
                commit_cursor: bool = True):
    """一轮增量:拉取 → 逐封四道门 → 合并落库 → 记 log → 推游标。"""
    msgs, max_ts = gc.fetch_new_messages(user_id, bootstrap_days=bootstrap_days)
    summary = {"fetched": len(msgs), "positive": 0, "events": 0,
               "actions": [], "errors": 0}

    with db.get_conn() as conn:
        for m in msgs:
            v = extractor.extract_email(m)
            tin = sum(u["in"] for u in v["usages"])
            tout = sum(u["out"] for u in v["usages"])

            event_ids = []
            if v.get("error"):
                summary["errors"] += 1
                verdict = "error"
            elif v["has_commitment"]:
                verdict = "positive"
                summary["positive"] += 1
                # dedup_test 的 build_key 期望 em["from"],做字段适配
                em_view = {"body": m["body"], "subject": m["subject"],
                           "from": m["sender"], "id": m["id"]}
                for ev in v["events"]:
                    if not ev.get("datetime"):
                        continue
                    key, _ = D.build_key(em_view, ev)
                    action, eid = _merge_into_db(conn, user_id, m, ev, key)
                    event_ids.append(str(eid))
                    summary["events"] += 1
                    summary["actions"].append(
                        (action, ev.get("datetime"), ev.get("title", "")[:40]))
            else:
                verdict = "negative"

            conn.execute(
                "INSERT INTO extraction_log (user_id, email_id, gate, verdict, "
                "rule_hit, tokens_in, tokens_out, event_ids) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (user_id, m["id"], v["gate"], verdict, v.get("rule_hit"),
                 tin, tout, ",".join(event_ids) or None))

    if commit_cursor and msgs and summary["errors"] == 0:
        gc.commit_cursor(user_id, max_ts)        # 全批成功才推游标
        summary["cursor_committed"] = True
    else:
        summary["cursor_committed"] = False
    return summary


if __name__ == "__main__":
    import json
    s = process_new(bootstrap_days=2, commit_cursor=False)   # 冒烟:不推游标
    print(json.dumps(s, ensure_ascii=False, indent=2))