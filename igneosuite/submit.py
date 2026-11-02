"""Sending an author's dataset to the IgneoSuite database (tables IgneoSuite_datasets and IgneoSuite_samples)."""
from __future__ import annotations
import json
import uuid
import urllib.request
import urllib.error
import numpy as np
import pandas as pd
from . import __version__
from .telemetry import _cfg, _clean, session_id

LICENCES = {"CC-BY-4.0": "CC BY 4.0: anyone may reuse with credit",
            "CC0-1.0": "CC0: no restrictions",
            "CC-BY-NC-4.0": "CC BY-NC 4.0: reuse with credit, not for commercial use",
            "restricted": "Restricted: stored for Octa Insight only, not shared"}
BATCH = 500


def _num(v):
    return None if v is None or not np.isfinite(v) else float(v)


def sample_rows(dataset_id: str, ids, columns, M: np.ndarray, meta: pd.DataFrame,
                est: np.ndarray | None = None, E: np.ndarray | None = None) -> list[dict]:
    """One dict per sample: author's ID, location, age, measured values and (optionally) estimates."""
    rows = []
    for i in range(M.shape[0]):
        miss = np.isnan(M[i])
        r = dict(dataset_id=dataset_id, row_number=i + 1, sample_id=str(ids[i])[:200],
                 latitude=_num(meta["latitude"].iloc[i]), longitude=_num(meta["longitude"].iloc[i]),
                 age_ma=_num(meta["age_ma"].iloc[i]),
                 measured={c: float(M[i, j]) for j, c in enumerate(columns) if not miss[j]})
        if est is not None:
            r["estimated"] = {c: float(est[i, j]) for j, c in enumerate(columns) if miss[j] and np.isfinite(est[i, j])}
            r["estimate_error"] = ({c: float(E[i, j]) for j, c in enumerate(columns) if miss[j] and np.isfinite(E[i, j])}
                                   if E is not None else None)
        rows.append(r)
    return rows


def _post(table, payload, user=None):
    cfg = _cfg()
    if cfg is None:
        raise RuntimeError("The database connection is not configured.")
    url, key = cfg
    token = getattr(user, "access_token", None) or key
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}", data=json.dumps(_clean(payload)).encode(), method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {token}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            if not 200 <= r.status < 300:
                raise RuntimeError(f"Database answered {r.status}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Database refused the data ({e.code}): {e.read().decode(errors='replace')[:300]}")


def submit(info: dict, ids, columns, M, meta, est=None, E=None, method=None, band=None,
           user=None, progress=None) -> str:
    """Create the dataset row, then add samples in batches. Returns the dataset id."""
    did = str(uuid.uuid4())
    ds = dict(id=did, session_id=session_id(), app_version=__version__,
              author_name=info["author_name"].strip(), author_email=info["author_email"].strip(),
              affiliation=info.get("affiliation") or None, title=info["title"].strip(),
              reference=info.get("reference") or None, description=info.get("description") or None,
              licence=info["licence"], consent=bool(info["consent"]),
              n_samples=int(M.shape[0]), n_variables=int(M.shape[1]), variables=list(map(str, columns)),
              estimation_method=method if est is not None else None,
              error_band=band if est is not None else None)
    if user is not None and getattr(user, "id", None):
        ds["user_id"] = user.id
    _post("IgneoSuite_datasets", ds, user)
    rows = sample_rows(did, ids, columns, M, meta, est, E)
    for k in range(0, len(rows), BATCH):
        _post("IgneoSuite_samples", rows[k:k + BATCH], user)
        if progress:
            progress(min(1.0, (k + BATCH) / len(rows)), f"{min(k + BATCH, len(rows))} of {len(rows)} samples")
    return did
