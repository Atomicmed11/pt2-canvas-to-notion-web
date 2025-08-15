#!/usr/bin/env python3
import os
import re
import html
import time
import unicodedata
import requests
from datetime import datetime, timezone

# ---------------------------
# Environment variables
# ---------------------------
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "").strip()
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "").strip()
CANVAS_TOKEN = os.environ.get("CANVAS_TOKEN", "").strip()
CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL", "").rstrip("/").strip()  # e.g., https://your-school.instructure.com
NOTION_VERSION = os.environ.get("NOTION_VERSION", "2022-06-28")
ONLY_DATED = os.environ.get("ONLY_DATED", "true").lower() in ("1", "true", "yes")
MASTER_TITLE = os.environ.get("MASTER_TITLE", "Syllabi & Start Here (All Courses)")
SYLLABI_PAGE_ID = os.environ.get("SYLLABI_PAGE_ID", "").strip()
DEBUG = os.environ.get("DEBUG", "false").lower() in ("1", "true", "yes")

# Notion database property names (customize in Notion to match these, or change here)
PROP_NAME = os.environ.get("NOTION_PROP_NAME", "Name")
PROP_COURSE = os.environ.get("NOTION_PROP_COURSE", "Course")
PROP_CANVAS_ID = os.environ.get("NOTION_PROP_CANVAS_ID", "Canvas ID")
PROP_URL = os.environ.get("NOTION_PROP_URL", "URL")
PROP_POINTS = os.environ.get("NOTION_PROP_POINTS", "Points")
PROP_DUE = os.environ.get("NOTION_PROP_DUE", "Due Date")
PROP_STATUS = os.environ.get("NOTION_PROP_STATUS", "Status")  # optional (Select or Rich text)

def notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json"
    }

def canvas_headers():
    return {"Authorization": f"Bearer {CANVAS_TOKEN}"}

def paginate_canvas(url, params=None):
    params = params or {}
    while url:
        r = requests.get(url, headers=canvas_headers(), params=params)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            for item in data:
                yield item
        else:
            yield data
        link = r.headers.get("Link", "")
        next_url = None
        if link:
            parts = [p.strip() for p in link.split(",")]
            for p in parts:
                if 'rel="next"' in p:
                    start = p.find("<") + 1
                    end = p.find(">")
                    next_url = p[start:end]
                    break
        url = next_url
        params = {}

# Courses & assignments
def get_current_and_future_courses():
    """
    Try /users/self/courses with simple params. If Canvas 4xx/5xx occurs,
    fall back to /api/v1/courses and post-filter by term dates.
    """
    import datetime as _dt

    # Primary attempt (most schools): no state[] filter
    url = f"{CANVAS_BASE_URL}/api/v1/users/self/courses"
    params = {
        "per_page": 100,
        "enrollment_type[]": ["student"],
        "enrollment_state[]": ["active", "invited_or_pending"],
        "include[]": ["term"],
    }
    try:
        courses = list(paginate_canvas(url, params=params))
        if DEBUG: 
            print(f"[DEBUG] users/self/courses returned: {len(courses)}")  # <-- added debug
        if courses:
            return courses
    except requests.HTTPError:
        pass  # fall through to fallback

    # Fallback: /courses then keep ones that are current or future by term dates
    url2 = f"{CANVAS_BASE_URL}/api/v1/courses"
    params2 = {
        "per_page": 100,
        "enrollment_state": "active",   # broader
        "include[]": ["term"],
    }
    courses2 = list(paginate_canvas(url2, params=params2))
    print(f"[DEBUG] fallback /courses returned: {len(courses2)}")  # debug line

    now = _dt.datetime.utcnow()
    keep = []
    for c in courses2:
        term = (c or {}).get("term") or {}
        start = term.get("start_at")
        end = term.get("end_at")
        def _parse(s):
            try:
                # Canvas uses ISO8601 with Z or offset; let requests handle naive parsing
                return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return None
        sdt, edt = _parse(start), _parse(end)
        # keep if no term dates (be generous), or term hasn't ended,
        # i.e., current or future
        if (sdt is None and edt is None) or (edt and edt >= now) or (sdt and sdt >= now):
            keep.append(c)
    return keep

def get_active_courses():
    url = f"{CANVAS_BASE_URL}/api/v1/courses"
    params = {"enrollment_state": "active", "per_page": 100}
    return list(paginate_canvas(url, params=params))

def get_assignments(course_id):
    url = f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/assignments"
    params = {"per_page": 100}
    return list(paginate_canvas(url, params=params))

def normalize_assignment(a, course_name):
    return {
        "id": str(a.get("id")),
        "name": a.get("name") or f"Assignment {a.get('id')}",
        "due_at": a.get("due_at"),
        "url": a.get("html_url"),
        "points": a.get("points_possible"),
        "course": course_name,
        "published": a.get("published", True),
        "workflow_state": a.get("workflow_state")
    }

def notion_query_by_canvas_id(canvas_id):
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {"filter": {"property": PROP_CANVAS_ID, "rich_text": {"equals": str(canvas_id)}}, "page_size": 1}
    r = requests.post(url, headers=notion_headers(), json=payload)
    r.raise_for_status()
    return r.json().get("results", [])

def build_notion_properties(x):
    props = {
        PROP_NAME: {"title": [{"text": {"content": x["name"]}}]},
        PROP_COURSE: {"rich_text": [{"text": {"content": x["course"]}}]},
        PROP_CANVAS_ID: {"rich_text": [{"text": {"content": x["id"]}}]},
    }
    if x.get("url"):
        props[PROP_URL] = {"url": x["url"]}
    if x.get("points") is not None:
        props[PROP_POINTS] = {"number": float(x["points"])}
    if x.get("due_at"):
        props[PROP_DUE] = {"date": {"start": x["due_at"]}}
    status_val = x.get("workflow_state") or ("published" if x.get("published") else "unpublished")
    if status_val:
        props[PROP_STATUS] = {"rich_text": [{"text": {"content": status_val}}]}
    return props

def notion_create_page(props):
    url = "https://api.notion.com/v1/pages"
    payload = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": props}
    r = requests.post(url, headers=notion_headers(), json=payload)
    r.raise_for_status()
    return r.json()

def notion_update_page(page_id, props):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"properties": props}
    r = requests.patch(url, headers=notion_headers(), json=payload)
    r.raise_for_status()
    return r.json()

def upsert_assignment(x):
    results = notion_query_by_canvas_id(x["id"])
    props = build_notion_properties(x)
    if results:
        page_id = results[0]["id"]
        notion_update_page(page_id, props)
        print(f"Updated: {x['course']} • {x['name']}")
    else:
        notion_create_page(props)
        print(f"Created: {x['course']} • {x['name']}")
    time.sleep(0.4)

# Orientation / Syllabus harvesting
ORIENT_PATTERNS = [
    r"\borientation\b", r"\bstart\s*here\b", r"\bbegin\s*here\b",
    r"\bgetting\s*started\b", r"\bwelcome\b", r"\bread\s*me\s*first\b",
    r"\bcourse\s*(overview|info|information)\b", r"\bpolic(y|ies)\b",
    r"\bsimple\s*syllabus\b", r"\bsmart\s*syllabus\b"
]
SYLLAB_PAT = r"\bsyllab\w*\b"

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def looks_like_orientation(title: str) -> bool:
    t = norm(title)
    return any(re.search(p, t) for p in ORIENT_PATTERNS)

def looks_like_syllabus(title: str) -> bool:
    return bool(re.search(SYLLAB_PAT, norm(title)))

def plain_text_preview(html_body, limit=240):
    if not html_body:
        return ""
    txt = re.sub(r"<[^>]+>", " ", html_body)
    txt = html.unescape(re.sub(r"\s+", " ", txt)).strip()
    return (txt[:limit] + "…") if len(txt) > limit else txt

def get_syllabus_html(course_id):
    url = f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}"
    r = requests.get(url, headers=canvas_headers(), params={"include[]": "syllabus_body"})
    r.raise_for_status()
    data = r.json()
    return data.get("syllabus_body")
def get_front_page(course_id):
    try:
        r = requests.get(
            f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/front_page",
            headers=canvas_headers()
        )
        r.raise_for_status()
        data = r.json()  # { title, body, html_url, ... }
        return {
            "title": data.get("title") or "Front Page",
            "html": data.get("body") or "",
            "web_url": data.get("html_url")
        }
    except requests.HTTPError:
        return None
    
def get_pages_with_bodies(course_id):
    pages = list(paginate_canvas(f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/pages",
                                 params={"per_page": 100}))
    out = []
    for p in pages:
        title = p.get("title") or ""
        pr = requests.get(f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/pages/{p['url']}",
                          headers=canvas_headers())
        pr.raise_for_status()
        body = pr.json().get("body")
        out.append({"title": title, "html": body, "web_url": p.get("html_url")})
    return out

def get_modules_and_items(course_id):
    mods = list(paginate_canvas(f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/modules"))
    items = []
    for m in mods:
        mid = m["id"]
        mitems = list(paginate_canvas(
            f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/modules/{mid}/items"))
        for it in mitems:
            title = it.get("title") or ""
            web_url = it.get("html_url") or it.get("external_url")
            items.append({"module": m.get("name"), "title": title, "web_url": web_url, "type": it.get("type")})
    return items

def find_syllabus_files(course_id):
    files = list(paginate_canvas(
        f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/files",
        params={"search_term": "syllab", "per_page": 100}))
    keep_ext = (".pdf", ".doc", ".docx")
    out = []
    for f in files:
        name = f.get("display_name") or f.get("filename") or ""
        if looks_like_syllabus(name) or any(name.lower().endswith(ext) for ext in keep_ext):
            out.append({"title": name, "web_url": f.get("url")})
    return out

def get_or_create_master_page(title=None):
    # If a specific page was provided, use it directly.
    if SYLLABI_PAGE_ID:
        return SYLLABI_PAGE_ID

    # Otherwise fall back to creating/finding a page INSIDE the database.
    title = title or MASTER_TITLE
    q = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
        headers=notion_headers(),
        json={"filter": {"property": PROP_NAME, "title": {"equals": title}}, "page_size": 1}
    ).json()
    if q.get("results"):
        return q["results"][0]["id"]
    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=notion_headers(),
        json={
            "parent": {"database_id": NOTION_DATABASE_ID},
            "properties": {PROP_NAME: {"title":[{"text":{"content": title}}]}}
        }
    )
    r.raise_for_status()
    return r.json()["id"]

def append_blocks(page_id, blocks):
    if not blocks: return
    r = requests.patch(f"https://api.notion.com/v1/blocks/{page_id}/children",
                       headers=notion_headers(),
                       json={"children": blocks})
    r.raise_for_status()

def clear_page_children(page_id):
    """
    Deletes all child blocks from a Notion page so we can rewrite it fresh.
    """
    # paginate through children
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
    while True:
        r = requests.get(url, headers=notion_headers())
        r.raise_for_status()
        data = r.json()
        children = data.get("results", [])
        if not children:
            break
        # delete each child block
        for b in children:
            bid = b["id"]
            dr = requests.delete(f"https://api.notion.com/v1/blocks/{bid}", headers=notion_headers())
            # ignore 404s to be resilient
            if dr.status_code not in (200, 202, 204, 404):
                dr.raise_for_status()
            time.sleep(0.15)  # be nice to the API
        # next page?
        if data.get("has_more") and data.get("next_url"):
            url = data["next_url"]
        else:
            break

def bullet(text, href=None):
    if href:
        rt = [{"type":"text","text":{"content":text,"link":{"url":href}}}]
    else:
        rt = [{"type":"text","text":{"content":text}}]
    return {"object":"block","type":"bulleted_list_item","bulleted_list_item":{"rich_text":rt}}

def heading(text):
    return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":text}}]}}

def summarize_intros_and_syllabi(courses):
    master = get_or_create_master_page()
    # clear previous run so we don't stack sections
    clear_page_children(master)

    blocks = [heading(f"Sync run — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")]

    for c in courses:
        cid = c.get("id"); cname = c.get("name") or f"Course {cid}"
        if not cid:
            continue

        if DEBUG:
            print(f"[syllabi] Checking course {cid} — {cname}")

        # Built-in Syllabus
        body = get_syllabus_html(cid)
        if DEBUG:
            print(f"[syllabi] syllabus_body present? {'yes' if body else 'no'}")
        if body:
            blocks.append(
                bullet(
                    f"[Syllabus] {cname} — {plain_text_preview(body, 120)}",
                    f"{CANVAS_BASE_URL}/courses/{cid}/assignments/syllabus"
                )
            )

        # Front page (many instructors put “Start Here” here)
        fp = get_front_page(cid)
        if DEBUG:
            print(f"[syllabi] front page found? {'yes' if fp else 'no'}")
        if fp and (
            looks_like_orientation(fp["title"]) or
            looks_like_syllabus(fp["title"]) or
            "start" in norm(fp["title"])
        ):
            blocks.append(
                bullet(
                    f"[Front Page] {cname}: {fp['title']} — {plain_text_preview(fp['html'], 120)}",
                    fp["web_url"]
                )
            )

        # Course pages
        pages = get_pages_with_bodies(cid)
        if DEBUG:
            print(f"[syllabi] pages fetched: {len(pages)}")
        for p in pages:
            if looks_like_orientation(p["title"]) or looks_like_syllabus(p["title"]):
                blocks.append(
                    bullet(
                        f"[Page] {cname}: {p['title']} — {plain_text_preview(p['html'], 120)}",
                        p["web_url"]
                    )
                )

        # Modules & items
        mods = get_modules_and_items(cid)
        if DEBUG:
            print(f"[syllabi] module items fetched: {len(mods)}")
        for it in mods:
            if (
                looks_like_orientation(it["title"]) or
                looks_like_syllabus(it["title"]) or
                looks_like_orientation(it.get("module") or "")
            ):
                blocks.append(bullet(f"[Module] {cname}: {it['title']}", it.get("web_url")))

        # Likely syllabus files
        files = find_syllabus_files(cid)
        if DEBUG:
            print(f"[syllabi] likely syllabus files: {len(files)}")
        for f in files:
            blocks.append(bullet(f"[File] {cname}: {f['title']}", f["web_url"]))

        time.sleep(0.2)

    append_blocks(master, blocks)

def sync_once():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting sync…")
    courses = get_active_courses()
    print(f"Found {len(courses)} active courses")
    for c in courses:
        cid = c.get("id")
        cname = c.get("name") or f"Course {cid}"
        if not cid:
            continue
        try:
            assignments = get_assignments(cid)
        except requests.HTTPError as e:
            print(f"Error fetching assignments for {cname}: {e}")
            continue
        print(f"- {cname}: {len(assignments)} assignments")
        for a in assignments:
            x = normalize_assignment(a, cname)
            if ONLY_DATED and not x.get("due_at"):
                continue
            try:
                upsert_assignment(x)
            except requests.HTTPError as e:
                print(f"  ! Notion error for '{x['name']}': {e}")
                time.sleep(0.6)
                continue

    try:
        courses_for_syllabi = get_current_and_future_courses()
        summarize_intros_and_syllabi(courses_for_syllabi)
        print("Master page updated.")
    except requests.HTTPError as e:
        print("Error updating master page:", e)
    print("Sync complete.")
