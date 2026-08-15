"""
Kairos — Gmail 全量导出脚本
把 Gmail 邮件拉下来存成 JSONL, 供后续标注和模型评估使用。
支持断点续传：中断后重跑会跳过已抓取的邮件。
"""

import base64
import json
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ── 配置 ─────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("data/token.json")
OUTPUT_FILE = Path("data/emails_raw.jsonl")

# 每批拉取数量（Gmail API 单次上限 500）
BATCH_SIZE = 100


# ── 认证 ─────────────────────────────────────────────────────

def get_service():
    """获取 Gmail API service，首次运行会打开浏览器授权"""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ── 正文解析 ──────────────────────────────────────────────────

def decode_part(data: str) -> str:
    """解码 base64url 编码的邮件内容"""
    if not data:
        return ""
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")


def extract_body(payload: dict) -> tuple[str, str]:
    """
    递归提取邮件正文，返回 (纯文本, HTML)。
    邮件结构是嵌套的 MIME 树，需要深度遍历。
    """
    plain, html = "", ""

    if "parts" in payload:
        for part in payload["parts"]:
            p, h = extract_body(part)
            plain += p
            html += h
    else:
        mime = payload.get("mimeType", "")
        data = payload.get("body", {}).get("data", "")
        if mime == "text/plain":
            plain += decode_part(data)
        elif mime == "text/html":
            html += decode_part(data)

    return plain, html


def strip_html(html: str) -> str:
    """粗暴地把 HTML 转成纯文本，够用即可"""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ── 主逻辑 ────────────────────────────────────────────────────

def load_existing_ids() -> set:
    """读取已抓取的邮件 ID，用于断点续传"""
    if not OUTPUT_FILE.exists():
        return set()
    ids = set()
    with OUTPUT_FILE.open(encoding="utf-8") as f:
        for line in f:
            try:
                ids.add(json.loads(line)["id"])
            except Exception:
                continue
    return ids


def fetch_all():
    service = get_service()
    done_ids = load_existing_ids()
    print(f"Already fetched: {len(done_ids)}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_FILE.open("a", encoding="utf-8")

    page_token = None
    total_new = 0

    while True:
        resp = service.users().messages().list(
            userId="me",
            maxResults=BATCH_SIZE,
            pageToken=page_token,
            q="-in:spam -in:trash",   # 排除垃圾箱和已删除
        ).execute()

        messages = resp.get("messages", [])
        if not messages:
            break

        for msg in messages:
            if msg["id"] in done_ids:
                continue

            try:
                detail = service.users().messages().get(
                    userId="me", id=msg["id"], format="full"
                ).execute()
            except Exception as e:
                print(f"  skip {msg['id']}: {e}")
                continue

            payload = detail.get("payload", {})
            headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
            plain, html = extract_body(payload)
            body = plain.strip() or strip_html(html)

            record = {
                "id": detail["id"],
                "thread_id": detail.get("threadId"),
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "date_header": headers.get("date", ""),
                # Gmail 内部时间戳，毫秒，比 Date 头可靠
                "internal_date": detail.get("internalDate"),
                "labels": detail.get("labelIds", []),
                "snippet": detail.get("snippet", ""),
                # 截断长正文，标注用不到全文
                "body": body[:8000],
            }

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            total_new += 1

            if total_new % 50 == 0:
                out.flush()
                print(f"  fetched {total_new} new...")

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    out.close()
    print(f"\nDone. New: {total_new}, Total: {len(done_ids) + total_new}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    fetch_all()