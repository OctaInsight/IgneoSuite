"""Saving and reopening IgneoSuite projects in Supabase.

Every write and read goes through the igneosuite_* database functions, which check the project's
private access key (until sign-in exists) or the signed-in owner. The key is created in the browser
session and only its SHA-256 hash is stored in the database.
"""
from __future__ import annotations
import json
import math
import secrets
import urllib.error
import urllib.request
import uuid
import numpy as np
import pandas as pd
from . import __version__
from .telemetry import _cfg

BATCH = 500


# ---------------------------------------------------------------- encoding
def encode(o):
    """Turn results (DataFrames, arrays, numpy numbers) into JSON-safe objects."""
    if isinstance(o, pd.DataFrame):
        d = o.to_dict(orient="split")
        return {"__df__": {"index": encode(list(d["index"])), "columns": [str(c) for c in d["columns"]],
                           "data": encode(d["data"]), "index_name": o.index.name}}
    if isinstance(o, pd.Series):
        return encode(o.to_frame())
    if isinstance(o, np.ndarray):
        return {"__nd__": encode(o.tolist()), "dtype": str(o.dtype)}
    if isinstance(o, dict):
        return {str(k): encode(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [encode(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        o = float(o)
        return None if (math.isnan(o) or math.isinf(o)) else o
    return o


def _numeric(df):
    for c in df.columns:
        try:
            df[c] = pd.to_numeric(df[c])
        except (ValueError, TypeError):
            pass
    return df


def _nan(x):
    return [_nan(v) for v in x] if isinstance(x, list) else (np.nan if x is None else x)


def decode(o):
    if isinstance(o, dict):
        if "__df__" in o:
            d = o["__df__"]
            df = pd.DataFrame(decode(d["data"]), index=decode(d["index"]), columns=d["columns"])
            df.index.name = d.get("index_name")
            return _numeric(df)
        if "__nd__" in o:
            dt = o.get("dtype", "float64")
            try:
                return np.array(_nan(o["__nd__"]), dtype=dt)
            except (ValueError, TypeError):
                return np.array(o["__nd__"], dtype=object)
        return {k: decode(v) for k, v in o.items()}
    if isinstance(o, list):
        return [decode(v) for v in o]
    return o


# ---------------------------------------------------------------- client
def enabled() -> bool:
    return _cfg() is not None


def _rpc(fn: str, payload: dict, user=None, timeout=90):
    cfg = _cfg()
    if cfg is None:
        raise RuntimeError("The database connection is not set up for this installation.")
    url, key = cfg
    token = getattr(user, "access_token", None) or key
    req = urllib.request.Request(f"{url}/rest/v1/rpc/{fn}", data=json.dumps(encode(payload)).encode(), method="POST",
                                 headers={"apikey": key, "Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")
        try:
            msg = json.loads(msg).get("message", msg)
        except Exception:
            pass
        raise RuntimeError(f"The database refused the request ({e.code}): {msg[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"The database could not be reached: {e.reason}")


def new_project() -> dict:
    return {"id": str(uuid.uuid4()), "key": secrets.token_urlsafe(24)}


def project_code(p: dict) -> str:
    return f"{p['id']}~{p['key']}"


def by_account(p: dict) -> bool:
    """True when the project was opened through the signed-in account (no private key in this session)."""
    return str(p.get("key", "")).startswith("session:")


def account_key(session_token: str) -> str:
    return f"session:{session_token}"


def claim(p, session_token: str) -> bool:
    """Attach a saved project to the signed-in Octa account (the first owner stays)."""
    return bool(_rpc("igneosuite_claim", {"p_id": p["id"], "p_key": p["key"], "p_session": session_token}))


def my_projects(session_token: str) -> list[dict]:
    return _rpc("igneosuite_my_projects", {"p_session": session_token}) or []


# ---- sharing with other Octa users (owner shares by username or email, as viewer or editor)
def shared_with_me(session_token: str) -> list[dict]:
    return _rpc("igneosuite_shared_with_me", {"p_session": session_token}) or []


def my_role(session_token: str, project_id: str) -> str | None:
    """owner / edit / view / None for the signed-in user."""
    return _rpc("igneosuite_my_role", {"p_session": session_token, "p_id": project_id})


def find_users(session_token: str, query: str) -> list[dict]:
    return _rpc("igneosuite_find_users", {"p_session": session_token, "p_query": query}) or []


def share(session_token: str, project_id: str, people: list[str], role: str) -> dict:
    return _rpc("igneosuite_share", {"p_session": session_token, "p_id": project_id, "p_people": people,
                                     "p_role": role}) or {}


def shares(session_token: str, project_id: str) -> list[dict]:
    return _rpc("igneosuite_shares", {"p_session": session_token, "p_id": project_id}) or []


# ---- deleting a project: the owner asks, an administrator approves
def request_delete(session_token: str, project_id: str, reason: str) -> dict:
    return _rpc("igneosuite_request_delete", {"p_session": session_token, "p_id": project_id, "p_reason": reason}) or {}


def cancel_delete(session_token: str, project_id: str) -> bool:
    return bool(_rpc("igneosuite_cancel_delete", {"p_session": session_token, "p_id": project_id}))


def admin_delete_requests(session_token: str) -> dict:
    return _rpc("igneosuite_admin_delete_requests", {"p_session": session_token}) or {}


def admin_decide_delete(session_token: str, request_id: int, approve: bool, comment: str) -> dict:
    return _rpc("igneosuite_admin_decide_delete", {"p_session": session_token, "p_request": int(request_id),
                                                    "p_approve": bool(approve), "p_comment": comment}) or {}


def unshare(session_token: str, project_id: str, email: str) -> bool:
    return bool(_rpc("igneosuite_unshare", {"p_session": session_token, "p_id": project_id, "p_email": email}))


def parse_code(code: str) -> dict | None:
    code = (code or "").strip()
    if "~" not in code:
        return None
    pid, key = code.split("~", 1)
    try:
        uuid.UUID(pid)
    except ValueError:
        return None
    return {"id": pid, "key": key} if 24 <= len(key) <= 128 else None


def save_dataset(p, meta: dict, user=None):
    _rpc("igneosuite_save_dataset", {"p_id": p["id"], "p_key": p["key"], "p_meta": {**meta, "app_version": __version__}}, user)


def save_samples(p, rows: list[dict], user=None, progress=None):
    for k in range(0, max(len(rows), 1), BATCH):
        _rpc("igneosuite_save_samples", {"p_id": p["id"], "p_key": p["key"], "p_rows": rows[k:k + BATCH],
                                         "p_first": k == 0}, user)
        if progress:
            progress(min(1.0, (k + BATCH) / max(len(rows), 1)))


def save_estimates(p, rows: list[dict], user=None, progress=None):
    for k in range(0, len(rows), BATCH):
        _rpc("igneosuite_save_estimates", {"p_id": p["id"], "p_key": p["key"], "p_rows": rows[k:k + BATCH]}, user)
        if progress:
            progress(min(1.0, (k + BATCH) / len(rows)))


def save_clusters(p, labels: list[dict], user=None):
    """labels: [{"row_number", "a" (before filling), "b" (after filling)}]. Clears all numbers first."""
    for k in range(0, max(len(labels), 1), 5000):
        _rpc("igneosuite_save_clusters", {"p_id": p["id"], "p_key": p["key"], "p_rows": labels[k:k + 5000],
                                          "p_first": k == 0}, user)


def save_age_groups(p, groups: list[dict], user=None):
    """groups: [{"row_number", "g" (group name)}]. Clears every sample's group first."""
    for k in range(0, max(len(groups), 1), 5000):
        _rpc("igneosuite_save_age_groups", {"p_id": p["id"], "p_key": p["key"], "p_rows": groups[k:k + 5000],
                                            "p_first": k == 0}, user)


def save_step(p, step: str, params: dict, results: dict, user=None):
    _rpc("igneosuite_save_step", {"p_id": p["id"], "p_key": p["key"], "p_step": step, "p_params": params,
                                  "p_results": results, "p_app_version": __version__}, user)


def delete_step(p, step: str, user=None):
    _rpc("igneosuite_delete_step", {"p_id": p["id"], "p_key": p["key"], "p_step": step}, user)


def load(p, user=None, progress=None) -> dict:
    out = _rpc("igneosuite_load_dataset", {"p_id": p["id"], "p_key": p["key"]}, user)
    rows, off = [], 0
    n = (out.get("dataset") or {}).get("n_samples") or 0
    while True:
        page = _rpc("igneosuite_load_samples", {"p_id": p["id"], "p_key": p["key"], "p_offset": off, "p_limit": 2000}, user)
        rows += page
        off += len(page)
        if progress and n:
            progress(min(1.0, off / n))
        if len(page) < 2000:
            break
    out["samples"] = rows
    out["steps"] = {k: {"params": decode(v["params"]), "results": decode(v["results"]), "updated_at": v.get("updated_at")}
                    for k, v in (out.get("steps") or {}).items()}
    return out
