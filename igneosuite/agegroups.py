"""Age statistics and age groups (IgneoSuite 2, module "Plot and explore", step 2).

A grouping is a table of intervals: name, from (Ma, younger end), to (Ma, older end), colour.
A sample belongs to the first interval with  from <= age < to  (the oldest interval also takes age == to).
Samples without an age, or outside every interval, are put in "No age" / "Outside the groups".
"""
from __future__ import annotations
import numpy as np
import pandas as pd

NO_AGE = "No age"
OUTSIDE = "Outside the groups"
GREY = "#9a9893"
PALETTE = ["#2a78d6", "#e8743b", "#19a979", "#ed4a7b", "#945ecf", "#13a4b4", "#525df4", "#bf399e",
           "#6c8893", "#ee6868", "#2f6497", "#e0a52a"]

# International Chronostratigraphic Chart (ICS), boundaries in Ma; standard ICS colours.
TIMESCALE = {
    "Eon": [("Phanerozoic", 0, 538.8, "#9AD9DD"), ("Proterozoic", 538.8, 2500, "#F73563"),
            ("Archean", 2500, 4031, "#F0047F"), ("Hadean", 4031, 4567, "#AE027E")],
    "Era": [("Cenozoic", 0, 66.0, "#F2F91D"), ("Mesozoic", 66.0, 251.902, "#67C5CA"),
            ("Paleozoic", 251.902, 538.8, "#99C08D"), ("Neoproterozoic", 538.8, 1000, "#FEB342"),
            ("Mesoproterozoic", 1000, 1600, "#FDB462"), ("Paleoproterozoic", 1600, 2500, "#F74370"),
            ("Neoarchean", 2500, 2800, "#F99BC1"), ("Mesoarchean", 2800, 3200, "#F768A9"),
            ("Paleoarchean", 3200, 3600, "#F4449F"), ("Eoarchean", 3600, 4031, "#DA037F"),
            ("Hadean", 4031, 4567, "#AE027E")],
    "Period": [("Quaternary", 0, 2.58, "#F9F97F"), ("Neogene", 2.58, 23.03, "#FFE619"),
               ("Paleogene", 23.03, 66.0, "#FD9A52"), ("Cretaceous", 66.0, 143.1, "#7FC64E"),
               ("Jurassic", 143.1, 201.4, "#34B2C9"), ("Triassic", 201.4, 251.902, "#812B92"),
               ("Permian", 251.902, 298.9, "#F04028"), ("Carboniferous", 298.9, 358.86, "#67A599"),
               ("Devonian", 358.86, 419.62, "#CB8C37"), ("Silurian", 419.62, 443.1, "#B3E1B6"),
               ("Ordovician", 443.1, 486.85, "#009270"), ("Cambrian", 486.85, 538.8, "#7FA056"),
               ("Ediacaran", 538.8, 635, "#FED96A"), ("Cryogenian", 635, 720, "#FECC5C"),
               ("Tonian", 720, 1000, "#FEBF4E"), ("Stenian", 1000, 1200, "#FED99A"),
               ("Ectasian", 1200, 1400, "#FDCC8A"), ("Calymmian", 1400, 1600, "#FDC07A"),
               ("Statherian", 1600, 1800, "#F875A7"), ("Orosirian", 1800, 2050, "#F76898"),
               ("Rhyacian", 2050, 2300, "#F75B89"), ("Siderian", 2300, 2500, "#F74F7C"),
               ("Neoarchean", 2500, 2800, "#F99BC1"), ("Mesoarchean", 2800, 3200, "#F768A9"),
               ("Paleoarchean", 3200, 3600, "#F4449F"), ("Eoarchean", 3600, 4031, "#DA037F"),
               ("Hadean", 4031, 4567, "#AE027E")],
}
METHODS = {
    "timescale": "Geological time scale (ICS)",
    "width": "Equal intervals (fixed width in Ma)",
    "count": "Equal number of samples per group",
    "custom": "My own boundaries",
}
COLUMNS = ["Group", "From (Ma)", "To (Ma)", "Colour"]


def stats(age: np.ndarray) -> dict:
    a = np.asarray(age, float)
    ok = a[np.isfinite(a)]
    out = dict(n=int(len(a)), n_with_age=int(len(ok)), n_without_age=int(len(a) - len(ok)))
    if len(ok):
        q = np.percentile(ok, [25, 50, 75])
        out.update(min=float(ok.min()), max=float(ok.max()), mean=float(ok.mean()),
                   std=float(ok.std(ddof=1)) if len(ok) > 1 else 0.0,
                   q25=float(q[0]), median=float(q[1]), q75=float(q[2]))
    return out


def _fmt(x: float) -> str:
    return f"{x:g}" if abs(x) >= 10 or x == int(x) else f"{x:.2f}".rstrip("0").rstrip(".")


def _named(edges, colours=None) -> pd.DataFrame:
    rows = []
    for i in range(len(edges) - 1):
        lo, hi = float(edges[i]), float(edges[i + 1])
        rows.append([f"{_fmt(lo)}–{_fmt(hi)} Ma", lo, hi, (colours or PALETTE)[i % len(colours or PALETTE)]])
    return pd.DataFrame(rows, columns=COLUMNS)


def propose(age: np.ndarray, method: str, level: str = "Period", width: float = 100.0, n_groups: int = 5,
            custom: str = "", only_used: bool = True, ics_colours: bool = False) -> pd.DataFrame:
    """A starting table of groups for the chosen method."""
    a = np.asarray(age, float)
    ok = a[np.isfinite(a)]
    if not len(ok):
        return pd.DataFrame(columns=COLUMNS)
    if method == "timescale":
        t = pd.DataFrame([list(r) for r in TIMESCALE[level]], columns=COLUMNS)
        if only_used:
            used = [((ok >= lo) & ((ok < hi) | ((ok == hi) & (hi == t["To (Ma)"].max())))).any()
                    for lo, hi in zip(t["From (Ma)"], t["To (Ma)"])]
            t = t[used].reset_index(drop=True)
        if not ics_colours:        # the official colours of neighbouring intervals are often very alike
            t["Colour"] = [PALETTE[i % len(PALETTE)] for i in range(len(t))]
        return t
    if method == "width":
        w = max(float(width), 1e-6)
        lo, hi = np.floor(ok.min() / w) * w, np.ceil(ok.max() / w) * w
        if hi <= lo:
            hi = lo + w
        edges = np.arange(lo, hi + w / 2, w)
        t = _named(edges)
        if only_used:
            t = t[[((ok >= r["From (Ma)"]) & (ok < r["To (Ma)"])).any() or (i == len(t) - 1 and (ok == r["To (Ma)"]).any())
                   for i, r in t.iterrows()]].reset_index(drop=True)
            t["Colour"] = [PALETTE[i % len(PALETTE)] for i in range(len(t))]
        return t
    if method == "count":
        k = int(max(1, min(n_groups, len(np.unique(ok)))))
        edges = np.unique(np.percentile(ok, np.linspace(0, 100, k + 1)))
        if len(edges) < 2:
            edges = np.array([ok.min(), ok.min() + 1])
        edges = [float(f"{e:.4g}") for e in edges]
        return _named(edges)
    if method == "custom":
        try:
            edges = sorted({float(x) for x in custom.replace(";", ",").replace(" ", ",").split(",") if x.strip()})
        except ValueError:
            edges = []
        return _named(edges) if len(edges) >= 2 else pd.DataFrame(columns=COLUMNS)
    raise ValueError(method)


def clean(table: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Check an edited table: numbers, from < to, no overlaps, unique names. Returns (table, problems)."""
    t = table.copy()
    problems = []
    t = t.dropna(how="all")
    for c in ("From (Ma)", "To (Ma)"):
        t[c] = pd.to_numeric(t[c], errors="coerce")
    t["Group"] = t["Group"].fillna("").astype(str).str.strip().str.slice(0, 100)
    bad = t["From (Ma)"].isna() | t["To (Ma)"].isna()
    if bad.any():
        problems.append("Every group needs a number in 'From (Ma)' and 'To (Ma)'.")
    t = t[~bad]
    rev = t["From (Ma)"] >= t["To (Ma)"]
    if rev.any():
        problems.append("'From (Ma)' must be younger (smaller) than 'To (Ma)' in every group: "
                        + ", ".join(t.loc[rev, "Group"].astype(str)) + ".")
    t = t[~rev].sort_values("From (Ma)").reset_index(drop=True)
    empty = t["Group"] == ""
    t.loc[empty, "Group"] = [f"{_fmt(a)}–{_fmt(b)} Ma" for a, b in zip(t.loc[empty, "From (Ma)"], t.loc[empty, "To (Ma)"])]
    if t["Group"].duplicated().any():
        problems.append("Two groups have the same name: " + ", ".join(t.loc[t["Group"].duplicated(), "Group"]) + ".")
    over = (t["From (Ma)"].values[1:] < t["To (Ma)"].values[:-1])
    if over.any():
        problems.append("Some groups overlap: " + ", ".join(
            f"{t['Group'][i]} / {t['Group'][i + 1]}" for i in np.where(over)[0]) + ". A sample goes to the younger one.")
    col = t["Colour"].fillna("").astype(str).str.strip()
    t["Colour"] = [c if (c.startswith("#") and len(c) in (4, 7)) else PALETTE[i % len(PALETTE)]
                   for i, c in enumerate(col)]
    return t[COLUMNS], problems


def assign(age: np.ndarray, table: pd.DataFrame) -> np.ndarray:
    """Group name for every sample ('No age' / 'Outside the groups' where none applies)."""
    a = np.asarray(age, float)
    out = np.full(len(a), OUTSIDE, dtype=object)
    out[~np.isfinite(a)] = NO_AGE
    done = ~np.isfinite(a)
    if len(table):
        oldest = float(table["To (Ma)"].max())
        for _, r in table.iterrows():
            lo, hi = float(r["From (Ma)"]), float(r["To (Ma)"])
            hit = ~done & (a >= lo) & ((a < hi) | ((a == hi) & (hi == oldest)))
            out[hit] = r["Group"]
            done |= hit
    return out


def colours(table: pd.DataFrame) -> dict:
    c = {r["Group"]: r["Colour"] for _, r in table.iterrows()}
    c[NO_AGE] = GREY
    c[OUTSIDE] = "#5d5c58"
    return c


def counts(groups: np.ndarray, table: pd.DataFrame) -> pd.DataFrame:
    s = pd.Series(groups).value_counts()
    order = list(table["Group"]) + [OUTSIDE, NO_AGE]
    rows = [(g, int(s.get(g, 0))) for g in order if s.get(g, 0) or g in set(table["Group"])]
    return pd.DataFrame(rows, columns=["Group", "Samples"])
