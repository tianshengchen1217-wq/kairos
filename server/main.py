from pathlib import Path

from fastapi import FastAPI, Body, Cookie, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler

import db
import db
import auth

app = FastAPI(title="Kairos API", version="0.3.0")

# 启动时建表(幂等:表已存在则跳过)
db.init_db()
db.init_db()
app.include_router(auth.router)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


# ── 门禁:从 cookie 解出当前用户 ─────────────────────────
def current_user(kairos_session: str | None = Cookie(default=None)) -> int:
    """无牌或过期 → 401(store.js 已预留该语义)"""
    user_id = db.get_session_user(kairos_session)
    if user_id is None:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return user_id


# ── 定时任务:遍历所有用户,单个失败不连累别人 ─────────────
def scheduled_sync():
    import ingest
    with db.get_conn() as conn:
        user_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM users WHERE refresh_token IS NOT NULL "
            "AND (token_status IS NULL OR token_status != 'expired')")]
    for uid in user_ids:
        try:
            s = ingest.process_new(user_id=uid, commit_cursor=True)
            print(f"[scheduler] user={uid} fetched={s['fetched']} "
                  f"positive={s['positive']} events={s['events']} "
                  f"errors={s['errors']}")
        except Exception as e:
            print(f"[scheduler] user={uid} sync failed: {e}")

def scheduled_backup():
    import shutil, sqlite3, time
    from pathlib import Path
    src = db.DB_PATH
    bdir = Path(src).parent / "backups"
    bdir.mkdir(exist_ok=True)
    dst = bdir / f"kairos-{time.strftime('%Y%m%d')}.db"
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)                       # 官方热备 API,写入中也安全
    # 只留最近 7 份
    for old in sorted(bdir.glob("kairos-*.db"))[:-7]:
        old.unlink()
    print(f"[backup] {dst.name} done")

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_sync, "interval", hours=1,
                  next_run_time=None)
scheduler.add_job(scheduled_backup, "cron", hour=17, minute=0)
scheduler.start()


scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_sync, "interval", hours=1,
                  next_run_time=None)
scheduler.start()


# ── API 路由 ─────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"ok": True, "service": "kairos", "version": "0.3.0"}


@app.get("/api/events")
def list_events(user_id: int = Depends(current_user)):
    return db.list_events(user_id=user_id)


@app.post("/api/events")
def create_event(ev: dict = Body(...), user_id: int = Depends(current_user)):
    return db.add_event(ev, user_id=user_id)


@app.get("/api/connection")
def connection_status(user_id: int = Depends(current_user)):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT email, refresh_token IS NOT NULL AS has_rt, token_status "
            "FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not row["has_rt"]:
        return {"state": "none", "email": None}
    if row["token_status"] == "expired":
        return {"state": "expired", "email": row["email"]}
    return {"state": "connected", "email": row["email"]}


@app.post("/api/sync")
def sync_now(user_id: int = Depends(current_user)):
    """手动触发:只同步当前登录用户自己的邮箱"""
    import ingest
    return ingest.process_new(user_id=user_id, commit_cursor=True)


@app.post("/api/logout")
def logout(kairos_session: str | None = Cookie(default=None)):
    if kairos_session:
        db.delete_session(kairos_session)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("kairos_session")
    return resp


# 托管前端:必须放在所有 /api 路由之后,否则会拦截 API 请求
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")