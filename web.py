import os
from fastapi import FastAPI, HTTPException
from app import sync_once

app = FastAPI()
SYNC_SECRET = os.environ.get("SYNC_SECRET", "").strip()

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/sync")
def sync(key: str):
    if not SYNC_SECRET or key != SYNC_SECRET:
        raise HTTPException(status_code=401, detail="bad key")
    sync_once()
    return {"status": "synced"}
from fastapi import FastAPI, Request
import os
from app import sync_once  # import your main sync

app = FastAPI()
SECRET_KEY = os.environ.get("SYNC_SECRET_KEY", "changeme")

@app.get("/")
def root():
    return {"status": "ok", "message": "Canvas → Notion sync service is running."}

@app.get("/sync")
def sync(request: Request):
    key = request.query_params.get("key")
    if key != SECRET_KEY:
        return {"error": "unauthorized"}
    sync_once()
    return {"status": "done"}