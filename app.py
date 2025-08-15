#!/usr/bin/env python3
import os
import requests

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "").strip()
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "").strip()
CANVAS_TOKEN = os.environ.get("CANVAS_TOKEN", "").strip()
CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL", "").rstrip("/").strip()
NOTION_VERSION = os.environ.get("NOTION_VERSION", "2022-06-28")

PROP_NAME = os.environ.get("NOTION_PROP_NAME", "Name")
PROP_COURSE = os.environ.get("NOTION_PROP_COURSE", "Course")
PROP_CANVAS_ID = os.environ.get("NOTION_PROP_CANVAS_ID", "Canvas ID")
PROP_URL = os.environ.get("NOTION_PROP_URL", "URL")
PROP_POINTS = os.environ.get("NOTION_PROP_POINTS", "Points")
PROP_DUE = os.environ.get("NOTION_PROP_DUE", "Due Date")
PROP_STATUS = os.environ.get("NOTION_PROP_STATUS", "Status")

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
    import requests
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
    import requests
    url = "https://api.notion.com/v1/pages"
    payload = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": props}
    r = requests.post(url, headers=notion_headers(), json=payload)
    r.raise_for_status()
    return r.json()

def notion_update_page(page_id, props):
    import requests
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
    else:
        notion_create_page(props)
