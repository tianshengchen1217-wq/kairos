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
    creds.refresh(Request())                          # refresh_token → 新鲜的 access token
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


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