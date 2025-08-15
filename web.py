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
