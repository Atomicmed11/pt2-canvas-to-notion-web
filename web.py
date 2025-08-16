# web.py
import os
from fastapi import FastAPI, Request
from app import sync_once

app = FastAPI()

# ONE env var name for the secret (set this in Render)
SECRET_KEY = os.environ.get("SYNC_SECRET_KEY", "").strip()

@app.get("/")
def root():
    return {"status": "ok", "message": "Canvas → Notion sync service is running."}

@app.get("/health")
def health():
    return {"ok": True}

# Accept BOTH GET and POST so cron or browser tests work
@app.api_route("/sync", methods=["GET", "POST"])
async def sync(request: Request):
    # Try query first: /sync?key=xxx
    key = request.query_params.get("key")

    # If not in query, try JSON body: {"key":"xxx"}
    if not key:
        try:
            data = await request.json()
            key = (data or {}).get("key")
        except Exception:
            key = None

    if not SECRET_KEY or key != SECRET_KEY:
        return {"error": "unauthorized"}

    sync_once()
    return {"status": "synced"}