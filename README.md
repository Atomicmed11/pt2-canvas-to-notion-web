# Canvas → Notion (Assignments + Syllabi/Orientation Summary)

Deploy as a Web Service on Render (free plan). Trigger via POST: `/sync?key=YOUR_SECRET`.

## What it does
- Upserts assignments from active Canvas courses to your Notion database.
  - Skips undated assignments if `ONLY_DATED=true` (default).
- Updates a single Notion page (title `Syllabi & Start Here (All Courses)` by default) with bulleted links + previews of:
  - Built-in Canvas **Syllabus**
  - **Pages** that look like Orientation/Start Here/Syllabus
  - **Module items** with orientation-like names
  - **Syllabus files** (PDF/DOC)

## Env vars (Render → Environment)
- NOTION_TOKEN
- NOTION_DATABASE_ID
- CANVAS_TOKEN
- CANVAS_BASE_URL
- SYNC_SECRET
- OPTIONAL: ONLY_DATED=true|false, MASTER_TITLE

Build: `pip install -r requirements.txt`  
Start: `uvicorn web:app --host 0.0.0.0 --port $PORT`
