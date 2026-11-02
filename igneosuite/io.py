"""Reading and cleaning geochemical tables."""
from __future__ import annotations
import io
import re
import numpy as np
import pandas as pd

PLACEHOLDERS = {"", "n", "n.d.", "nd", "n.a.", "na", "nan", "-", "--", "—", "d.l.", "dl", "<dl", "bdl", "b.d.l.", "<d.l.", "tr", "trace"}
HIDDEN_SPACE = re.compile(r"[\s     ﻿]")

REE = ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"]
OXIDES = ["SiO2", "TiO2", "Al2O3", "A12O3", "Fe2O3", "FeO", "Fe2O3t", "FeOt", "MnO", "MgO", "CaO", "Na2O", "K2O", "P2O5"]


def read_table(uploaded, sheet: str | int | None = 0) -> pd.DataFrame:
    """Read a CSV or Excel file (path or uploaded file object) with all cells as text."""
    name = getattr(uploaded, "name", str(uploaded)).lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(uploaded, sheet_name=sheet, dtype=object)
    data = uploaded.read() if hasattr(uploaded, "read") else open(uploaded, "rb").read()
    text = data.decode("utf-8-sig", errors="replace") if isinstance(data, bytes) else data
    sep = ";" if text.count(";") > text.count(",") else ","
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=object)


def _to_number(v):
    """Return (value, status) with status in {'number', 'recovered', 'missing', 'text'}."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan, "missing"
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v), "number"
    s = str(v)
    if s.strip().lower() in PLACEHOLDERS:
        return np.nan, "missing"
    if s.strip().startswith("<"):
        return np.nan, "missing"          # censored value reported as '<x': treated as missing
    try:
        return float(s), ("recovered" if re.search(r"[\u00a0\u2009\u200a\u2007\u202f\ufeff]", s) else "number")
    except ValueError:
        pass
    cleaned = HIDDEN_SPACE.sub("", s).replace(",", ".") if s.count(",") == 1 and "." not in s else HIDDEN_SPACE.sub("", s)
    try:
        return float(cleaned), "recovered"
    except ValueError:
        return np.nan, "text"


def clean_table(raw: pd.DataFrame, id_col: str, value_cols: list[str]):
    """Convert value columns to numbers. Returns (numeric frame, report dict)."""
    out = pd.DataFrame(index=raw.index)
    counts = {"number": 0, "recovered": 0, "missing": 0, "text": 0}
    texts = {}
    for c in value_cols:
        vals, stats = zip(*(_to_number(v) for v in raw[c])) if len(raw) else ((), ())
        out[c] = np.array(vals, dtype=float)
        for s in stats:
            counts[s] += 1
        bad = [str(raw[c].iloc[i]) for i, s in enumerate(stats) if s == "text"]
        if bad:
            texts[c] = sorted(set(bad))[:10]
    nonpos = {c: int((out[c] <= 0).sum()) for c in value_cols if (out[c] <= 0).any()}
    report = dict(counts=counts, text_examples=texts, nonpositive=nonpos, n_rows=len(raw), n_cols=len(value_cols))
    ids = raw[id_col].astype(str).values if id_col else np.arange(1, len(raw) + 1).astype(str)
    return out, ids, report


META_NAMES = {
    "latitude": {"lat", "latitude", "lat (°)", "lat (deg)", "latitude (°)", "latitude (deg)", "latitude (n)",
                 "lat.", "y", "breddegrad"},
    "longitude": {"lon", "long", "lng", "longitude", "lon (°)", "long (°)", "longitude (°)", "longitude (deg)",
                  "longitude (e)", "long.", "x", "lengdegrad"},
    "age_ma": {"age", "age (ma)", "age ma", "age_ma", "age(ma)", "age [ma]", "ma"},
    "reference": {"reference", "ref", "ref.", "source", "citation", "publication", "doi"},
    "comment": {"comment", "comments", "remark", "remarks", "note", "notes"},
}


def guess_meta(raw: pd.DataFrame) -> dict:
    """Guess latitude, longitude and age columns from their names (None if not found)."""
    out = {}
    for key, names in META_NAMES.items():
        out[key] = next((c for c in raw.columns if str(c).strip().lower() in names), None)
    return out


def read_meta(raw: pd.DataFrame, cols: dict) -> tuple[pd.DataFrame, dict]:
    """Numeric latitude, longitude and age (Ma); values outside valid ranges become missing."""
    limits = {"latitude": (-90, 90), "longitude": (-180, 180), "age_ma": (0, 4600)}
    meta, bad = pd.DataFrame(index=raw.index), {}
    for key, col in cols.items():
        if not col:
            meta[key] = np.nan
            continue
        v = np.array([_to_number(x)[0] for x in raw[col]], dtype=float)
        lo, hi = limits[key]
        out = (v < lo) | (v > hi)
        bad[key] = int(out.sum())
        v[out] = np.nan
        meta[key] = v
    return meta, bad


def guess_columns(raw: pd.DataFrame):
    """Guess the ID column and the numeric value columns."""
    cols = list(raw.columns)
    id_guess = next((c for c in cols if str(c).strip().lower() in {"id", "sample", "sample id", "sample_id", "name"}), cols[0])
    value_guess = []
    meta = {c for c in guess_meta(raw).values() if c}
    for c in cols:
        if c == id_guess or c in meta:
            continue
        nums = sum(_to_number(v)[1] in ("number", "recovered") for v in raw[c])
        if nums >= 0.2 * max(len(raw), 1):
            value_guess.append(c)
    return id_guess, value_guess


def element_group(col: str) -> str:
    """Classify a column as 'Major oxides', 'REE' or 'Trace elements' from its name."""
    base = re.split(r"[\s_(\[]", str(col).strip())[0]
    if base in REE:
        return "REE"
    if base in OXIDES or "wt" in str(col).lower() or base.endswith("O") or base.endswith("O2") or base.endswith("O3") or base.endswith("O5"):
        return "Major oxides"
    return "Trace elements"


def short_name(col: str) -> str:
    return re.split(r"\s", str(col).strip())[0]
