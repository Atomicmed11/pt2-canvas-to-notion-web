import os
from fastapi import FastAPI, HTTPException
from app import get_active_courses, get_assignments, normalize_assignment, upsert_assignment

app = FastAPI()
SYNC_SECRET = os.environ.get("SYNC_SECRET", "").strip()

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/sync")
def sync(key: str):
    if not SYNC_SECRET or key != SYNC_SECRET:
        raise HTTPException(status_code=401, detail="bad key")
    courses = get_active_courses()
    total = 0
    for c in courses:
        cid = c.get("id")
        cname = c.get("name") or f"Course {cid}"
        if not cid:
            continue
        assignments = get_assignments(cid)
        for a in assignments:
            upsert_assignment(normalize_assignment(a, cname))
            total += 1
    return {"status": "synced", "assignments_processed": total}
