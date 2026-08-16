"""
Google OAuth · Web 应用流
两个路由对应六步流程:
  /api/auth/google    → 第①②步:生成授权 URL,把用户送去 Google
  /api/auth/callback  → 第④⑤⑥步:收授权码,后台换令牌,存库
"""
import os
import secrets
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

import db

# 读项目根目录的 .env(auth.py 在 server/ 下,所以往上一层找)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
BASE_URL = os.environ.get("KAIROS_BASE_URL", "http://127.0.0.1:8000")
REDIRECT_URI = f"{BASE_URL}/api/auth/callback"

AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES    = "openid email https://www.googleapis.com/auth/gmail.readonly"

router = APIRouter(prefix="/api/auth")

# state 暂存。单进程开发期用内存 dict 足够;多实例部署时要挪到库/缓存
_pending_states: set[str] = set()


@router.get("/google")
def start_auth():
    """第①②步:造授权 URL,302 把浏览器送去 Google"""
    state = secrets.token_urlsafe(24)          # 防伪水印
    _pending_states.add(state)
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",               # 要授权码,不要隐式令牌
        "scope": SCOPES,
        "state": state,
        "access_type": "offline",              # 关键:没有它就拿不到 refresh_token
        "prompt": "consent",                   # 强制出同意页,保证每次都发 refresh_token
    }
    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def callback(code: str | None = None, state: str | None = None,
                   error: str | None = None):
    """第④⑤⑥步:验 state → 拿 code 换令牌 → 存库 → 送回日历"""
    if error:                                   # 用户在 Google 页面点了拒绝
        return RedirectResponse("/?auth=denied")
    if not code or state not in _pending_states:
        raise HTTPException(400, "invalid state or missing code")
    _pending_states.discard(state)              # state 一次性,用完即毁

    # 第⑤步:后台直连换令牌(出示 client_secret 的唯一时刻)
    async with httpx.AsyncClient() as client:
        resp = await client.post(TOKEN_URL, data={
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        })
    if resp.status_code != 200:
        raise HTTPException(502, f"token exchange failed: {resp.text}")
    tokens = resp.json()
    # tokens: access_token / refresh_token / expires_in / id_token ...

    # 用 access_token 问 Google "这是谁"(拿 email 和永久 sub)
    async with httpx.AsyncClient() as client:
        ui = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"})
    info = ui.json()                            # {"sub": ..., "email": ...}

    db.upsert_user(
        email=info["email"],
        google_sub=info["sub"],
        refresh_token=tokens.get("refresh_token"),
    )
    return RedirectResponse("/?auth=ok")        # 回日历,带上成功标记