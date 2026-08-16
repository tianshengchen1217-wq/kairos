from pathlib import Path
from fastapi import FastAPI, Body
from fastapi.staticfiles import StaticFiles

import db

app = FastAPI(title="Kairos API", version="0.2.0")

# 启动时建表(幂等:表已存在则跳过)
db.init_db()

import auth
app.include_router(auth.router)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/api/health")
def health():
    return {"ok": True, "service": "kairos", "version": "0.2.0"}


@app.get("/api/events")
def list_events():
    # 单用户阶段固定 user_id=1;OAuth 接入后改为从会话取
    return db.list_events(user_id=1)


@app.post("/api/events")
def create_event(ev: dict = Body(...)):
    # 返回带 id 的完整记录 —— store.js 的 POST 约定
    return db.add_event(ev, user_id=1)


# 托管前端。必须放在所有 /api 路由之后,否则会拦截 API 请求
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")