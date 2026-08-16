"""
Gmail 客户端 · 令牌复活术
从 users 表取 refresh_token → 换 access token → 构建 Gmail 服务对象。
这是服务器"以用户身份读邮箱"能力的唯一入口。
"""
import os

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import db

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_service(user_id: int = 1):
    """为指定用户构建 Gmail API 服务对象。"""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT refresh_token FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if not row or not row["refresh_token"]:
        raise RuntimeError(f"user {user_id} has no refresh_token — 需要先走 OAuth 授权")

    creds = Credentials(
        token=None,                                   # access token 空着,下面当场换
        refresh_token=row["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except Exception as e:
        msg = str(e).lower()
        if "invalid_grant" in msg or "invalid_scope" in msg:
            db.mark_token_expired(user_id)            # 钥匙作废:标记,停止空转
        raise                                          # 照常抛出,调用方(scheduler)记日志
    return build("gmail", "v1", credentials=creds, cache_discovery=False)

def fetch_new_messages(user_id: int = 1, bootstrap_days: int = 7,
                       max_results: int = 50):
    """
    增量拉取:只取 sync_state 游标之后的邮件。
    首次运行(无游标)只回溯 bootstrap_days 天,避免全量扫 31K 封。
    返回 (messages, max_internal_date):
      messages 按时间升序,每封含 id / internal_date / subject / sender / body 等;
      max_internal_date 是本批最大时间戳,由调用方在"全部处理成功后"写回游标。
    """
    import base64
    import time

    svc = get_service(user_id)

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT last_internal_date FROM sync_state WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    cursor_ms = row["last_internal_date"] if row and row["last_internal_date"] else None

    if cursor_ms:
        after_sec = cursor_ms // 1000            # Gmail 搜索用秒
    else:
        after_sec = int(time.time()) - bootstrap_days * 86400

    resp = svc.users().messages().list(
        userId="me", q=f"after:{after_sec}", maxResults=max_results,
    ).execute()
    ids = [m["id"] for m in resp.get("messages", [])]

    messages, max_ts = [], cursor_ms or 0
    for mid in ids:
        msg = svc.users().messages().get(
            userId="me", id=mid, format="full",
        ).execute()
        ts = int(msg["internalDate"])
        if cursor_ms and ts <= cursor_ms:        # after: 只有秒精度,毫秒级再过滤一次
            continue
        headers = {h["name"]: h["value"]
                   for h in msg["payload"].get("headers", [])}
        messages.append({
            "id": mid,
            "internal_date": ts,
            "subject": headers.get("Subject", ""),
            "sender": headers.get("From", ""),
            "labels": msg.get("labelIds", []),
            "body": _extract_body(msg["payload"]),
        })
        max_ts = max(max_ts, ts)

    messages.sort(key=lambda m: m["internal_date"])
    return messages, max_ts


def _extract_body(payload) -> str:
    """从 MIME 结构里挖正文,text/plain 优先,递归 multipart。"""
    import base64

    def decode(data):
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    if payload.get("mimeType") == "text/plain" and payload["body"].get("data"):
        return decode(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    if payload.get("mimeType") == "text/html" and payload["body"].get("data"):
        return decode(payload["body"]["data"])   # 没有纯文本时退而求 HTML
    return ""


def commit_cursor(user_id: int, max_internal_date: int):
    """仅在整批处理成功后调用 —— 游标推进与处理成功绑定,失败轮次自动重试。"""
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO sync_state (user_id, last_internal_date, last_run_at, last_status) "
            "VALUES (?, ?, datetime('now'), 'ok') "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "last_internal_date = excluded.last_internal_date, "
            "last_run_at = excluded.last_run_at, last_status = 'ok'",
            (user_id, max_internal_date),
        )

if __name__ == "__main__":
    # 冒烟测试:列最近 5 封邮件的主题 —— 服务器第一次以你的身份读邮箱
    svc = get_service()
    resp = svc.users().messages().list(userId="me", maxResults=5).execute()
    for m in resp.get("messages", []):
        msg = svc.users().messages().get(
            userId="me", id=m["id"],
            format="metadata", metadataHeaders=["Subject", "From"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        print(f"[{m['id']}] {headers.get('Subject', '(无主题)')[:60]}")
    print("\n✓ 令牌复活 + Gmail 读取,链路通")