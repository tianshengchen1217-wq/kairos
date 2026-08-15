from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Kairos API", version="0.1.0")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

@app.get("/api/health")
def health():
    return {"ok": True, "service": "kairos", "version": "0.1.0"}

@app.get("/api/events")
def list_events():
    # 骨架阶段:假数据,形状严格遵循 store.js 合同
    # {id, datetime, type, title};datetime 带时间用空格分隔,不带则只有日期
    return [
        {"id": "srv-1", "datetime": "2026-08-20",       "type": "billing",     "title": "iCloud+ 订阅续费(来自后端)"},
        {"id": "srv-2", "datetime": "2026-08-22 19:30", "type": "appointment", "title": "测试订位(来自后端)"},
    ]

# 托管前端:必须放在所有 /api 路由之后,否则会把 /api 也吞掉
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")