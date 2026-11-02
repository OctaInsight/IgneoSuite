"""Reading and checking sample coordinates.

Accepted formats (each cell):
  decimal degrees         25.4567    -33.12    25,4567
  with hemisphere         25.4567 N  N25.4567  33.12W
  degrees-minutes         25°27.4'N  25 27.4 N
  degrees-minutes-seconds 25°27'24"N 25 27 24 N  25:27:24N  25d27m24sN
Everything is converted to decimal degrees (WGS84, north and east positive).
"""
from __future__ import annotations
import re
import numpy as np
import pandas as pd

LIMIT = {"latitude": 90.0, "longitude": 180.0}
HEMI = {"latitude": "NS", "longitude": "EW"}

_NUM = r"\d+(?:[.,]\d+)?"
_SEP = r"[\s°º˚d:'′’m\"″”s]*"


def parse_coordinate(value, kind: str) -> tuple[float, str]:
    """Return (decimal degrees, status). status: ok, converted, missing, unreadable, out_of_range, wrong_hemisphere."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan, "missing"
    if isinstance(value, (int, float, np.integer, np.floating)):
        v = float(value)
        return (v, "ok") if abs(v) <= LIMIT[kind] else (v, "out_of_range")
    s = str(value).strip().replace(" ", " ").replace("−", "-")
    if s == "" or s.lower() in {"nan", "n.d.", "nd", "-", "na", "n.a."}:
        return np.nan, "missing"
    # plain decimal (dot or comma)
    t = s.replace(",", ".") if s.count(",") == 1 and "." not in s else s
    try:
        v = float(t)
        return (v, "ok") if abs(v) <= LIMIT[kind] else (v, "out_of_range")
    except ValueError:
        pass
    s2 = re.sub(r"(?<=\d)[dms](?=[\d\sNSEW]|$)", " ", s)   # 25d27m24s style markers (lower case, after a digit)
    u = s2.upper()
    letters = re.findall(r"[A-Z]", u)
    if any(c not in "NSEW" for c in letters) or len(letters) > 1:
        return np.nan, "unreadable"
    hemi = letters[0] if letters else ""
    if hemi and hemi not in HEMI[kind]:
        return np.nan, "wrong_hemisphere"
    core = re.sub(r"[NSEW]", " ", u).strip()
    neg = core.startswith("-")
    core = core.lstrip("-+ ").replace(",", ".")
    parts = re.findall(r"\d+(?:\.\d+)?", core)
    if not parts or len(parts) > 3 or re.search(r"[^\d.\s°º˚:'′’\"″”]", core):
        return np.nan, "unreadable"
    nums = [float(p) for p in parts]
    if len(nums) >= 2 and nums[1] >= 60 or len(nums) == 3 and nums[2] >= 60:
        return np.nan, "unreadable"
    v = nums[0] + (nums[1] / 60 if len(nums) > 1 else 0) + (nums[2] / 3600 if len(nums) > 2 else 0)
    if neg or hemi in ("S", "W"):
        v = -v
    if abs(v) > LIMIT[kind]:
        return v, "out_of_range"
    return v, "converted"


MESSAGES = {
    "missing": "no value",
    "unreadable": "format not recognised",
    "out_of_range": "outside the valid range",
    "wrong_hemisphere": "hemisphere letter belongs to the other coordinate",
}


def check_locations(ids, lat_raw: pd.Series, lon_raw: pd.Series) -> dict:
    """Parse both columns and list every problem."""
    lat = [parse_coordinate(v, "latitude") for v in lat_raw]
    lon = [parse_coordinate(v, "longitude") for v in lon_raw]
    la = np.array([x[0] for x in lat], float); lo = np.array([x[0] for x in lon], float)
    sa = np.array([x[1] for x in lat]); so = np.array([x[1] for x in lon])
    bad_a = ~np.isin(sa, ["ok", "converted"]); bad_o = ~np.isin(so, ["ok", "converted"])
    zero = (~bad_a & ~bad_o) & (la == 0) & (lo == 0)
    rows = []
    for i in np.where(bad_a | bad_o | zero)[0]:
        msg = []
        if bad_a[i]:
            msg.append("latitude: " + MESSAGES[sa[i]])
        if bad_o[i]:
            msg.append("longitude: " + MESSAGES[so[i]])
        if zero[i]:
            msg.append("location is 0, 0 (probably a placeholder)")
        rows.append({"Row": i + 2, "Sample": ids[i], "Latitude as given": lat_raw.iloc[i],
                     "Longitude as given": lon_raw.iloc[i], "Problem": "; ".join(msg)})
    ok = ~(bad_a | bad_o | zero)
    # swapped columns: many latitudes beyond ±90 while the longitudes all fit within ±90
    swapped = bool((sa == "out_of_range").sum() >= max(1, 0.2 * len(sa)) and
                   np.nanmax(np.abs(lo[np.isin(so, ["ok", "converted"])]), initial=0) <= 90)
    precision = None
    good = la[ok]
    if len(good) and np.all(np.isclose(good, np.round(good))) and np.all(np.isclose(lo[ok], np.round(lo[ok]))):
        precision = "All coordinates are whole degrees (about 100 km precision). Check that decimals were not lost."
    return dict(latitude=np.where(ok, la, np.nan), longitude=np.where(ok, lo, np.nan), valid=ok,
                problems=pd.DataFrame(rows), n_converted=int(((sa == "converted") | (so == "converted"))[ok].sum()),
                swapped=swapped, precision_note=precision)


def read_age(raw: pd.Series) -> tuple[np.ndarray, int]:
    """Age in Ma; values outside 0–4,600 Ma or unreadable become missing. Returns (ages, number rejected)."""
    from .io import _to_number
    out, bad = [], 0
    for v in raw:
        x, st = _to_number(v)
        if st == "text" or (np.isfinite(x) and not 0 <= x <= 4600):
            bad += 1; x = np.nan
        out.append(x)
    return np.array(out, float), bad


def map_view(lat: np.ndarray, lon: np.ndarray) -> dict:
    """Centre and zoom that show every point."""
    la, lo = lat[np.isfinite(lat)], lon[np.isfinite(lon)]
    if not len(la):
        return dict(latitude=0, longitude=0, zoom=1)
    span = max(np.ptp(la), np.ptp(lo) * np.cos(np.radians(np.mean(la))), 0.05)
    zoom = float(np.clip(np.log2(360 / span) - 0.8, 1, 12))
    return dict(latitude=float((la.min() + la.max()) / 2), longitude=float((lo.min() + lo.max()) / 2), zoom=zoom)
