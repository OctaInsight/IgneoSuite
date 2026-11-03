"""Anonymous usage records in Supabase (tables IgneoSuite_runs, IgneoSuite_events, IgneoSuite_feedback).

Only counts, settings and scores are sent, never data values or sample IDs. Nothing is sent unless
`.streamlit/secrets.toml` (or the Streamlit Cloud secrets box) contains:

    [supabase]
    url = "https://<project>.supabase.co"
    key = "sb_publishable_..."

Failures never interrupt the app.
"""
from __future__ import annotations
import json
import math
import uuid
import urllib.request
import streamlit as st
from . import __version__


def _cfg():
    try:
        s = st.secrets["supabase"]
        return s["url"].rstrip("/"), s["key"]
    except Exception:
        return None


def enabled() -> bool:
    return _cfg() is not None


def session_id() -> str:
    if "_sid" not in st.session_state:
        st.session_state["_sid"] = uuid.uuid4().hex
    return st.session_state["_sid"]


def _clean(o):
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "item"):
        return _clean(o.item())
    return o


def _post(table: str, row: dict, user=None):
    cfg = _cfg()
    if cfg is None:
        return False
    url, key = cfg
    row = _clean({**row, "session_id": session_id(), "app_version": __version__})
    if isinstance(user, dict) and user.get("id"):      # Octa account (octa_auth)
        row["octa_user_id"] = user["id"]
    elif user is not None and getattr(user, "id", None):
        row["user_id"] = user.id
    token = getattr(user, "access_token", None) or key
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}", data=json.dumps(row).encode(), method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {token}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def event(name: str, detail: dict | None = None, user=None):
    return _post("IgneoSuite_events", {"event": name, "detail": detail or {}}, user)


def run(summary: dict, user=None):
    return _post("IgneoSuite_runs", summary, user)


def feedback(rating: int | None, message: str, email: str | None, user=None):
    return _post("IgneoSuite_feedback", {"rating": rating, "message": message[:4000],
                                         "contact_email": (email or None)}, user)
