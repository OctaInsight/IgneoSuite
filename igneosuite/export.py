"""Writing results to Excel and CSV."""
from __future__ import annotations
import io
import numpy as np
import pandas as pd


def three_column(ids, id_name, columns, M, est, E) -> pd.DataFrame:
    """For every variable: measured value, estimated value, ± error."""
    data = {id_name: ids}
    for j, c in enumerate(columns):
        miss = np.isnan(M[:, j])
        data[f"{c} measured"] = np.where(miss, np.nan, M[:, j])
        data[f"{c} estimated"] = np.where(miss, est[:, j], np.nan)
        data[f"{c} ± error"] = np.where(miss, E[:, j], np.nan)
    return pd.DataFrame(data)


def error_range(est: np.ndarray, E: np.ndarray):
    """Low and high end of the error band of each estimate.

    The band is [estimate/f, estimate*f]; IgneoSuite reports ± = estimate*(f - 1/f)/2, so
    f = r + sqrt(r^2 + 1) with r = ±/estimate."""
    with np.errstate(divide="ignore", invalid="ignore"):
        r = E / est
        f = r + np.sqrt(r * r + 1)
        return est / f, est * f


def full_table(ids, id_name, meta: pd.DataFrame, columns, M, est, E, cl_ref=None, cl_fill=None,
               band_pct: int = 68) -> pd.DataFrame:
    """One row per sample: ID, location, age, reference, comment, clusters before and after filling, and for every
    element the measured value, the estimate, its ± error and its error range."""
    n = M.shape[0]
    data = {id_name: ids}
    for key, name in (("latitude", "Latitude"), ("longitude", "Longitude"), ("age_ma", "Age (Ma)"),
                      ("reference", "Reference"), ("comment", "Comment")):
        data[name] = meta[key].values if meta is not None and key in meta else [None] * n
    data["Cluster before filling"] = cl_ref if cl_ref is not None else [None] * n
    data["Cluster after filling"] = cl_fill if cl_fill is not None else [None] * n
    lo, hi = error_range(est, E) if est is not None and E is not None else (None, None)
    for j, c in enumerate(columns):
        miss = np.isnan(M[:, j])
        data[f"{c} measured"] = np.where(miss, np.nan, M[:, j])
        if est is not None:
            data[f"{c} estimated"] = np.where(miss, est[:, j], np.nan)
        if E is not None:
            data[f"{c} ± error"] = np.where(miss, E[:, j], np.nan)
            data[f"{c} low ({band_pct}%)"] = np.where(miss, lo[:, j], np.nan)
            data[f"{c} high ({band_pct}%)"] = np.where(miss, hi[:, j], np.nan)
    df = pd.DataFrame(data)
    for c in ("Cluster before filling", "Cluster after filling"):
        df[c] = pd.array(df[c], dtype="Int64")
    return df


def complete_matrix(ids, id_name, columns, est) -> pd.DataFrame:
    df = pd.DataFrame(est, columns=columns)
    df.insert(0, id_name, ids)
    return df


def to_excel(sheets: dict[str, pd.DataFrame], notes: list[str]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=not isinstance(df.index, pd.RangeIndex))
        pd.DataFrame({"Notes": notes}).to_excel(xw, sheet_name="Notes", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "B2"
            for col in ws.columns:
                w = max(len(str(col[0].value or "")), 8)
                ws.column_dimensions[col[0].column_letter].width = min(w + 2, 28)
    return buf.getvalue()


def default_notes(method, factors_note, n_est, columns):
    return [
        "Produced with IgneoSuite (imputation module).",
        f"Estimation method: {method}.",
        f"{n_est} missing values were estimated across {len(columns)} variables.",
        "Measured values are never changed.",
        "'± error' is half the width of the 68% error band: estimate × (f − 1/f)/2, where f = 10^q and q is the 68th "
        "percentile of |log10(estimate/true)| for that variable in the masking test.",
        factors_note,
        "Cite: Abu-Alam, T.S., et al. When simpler wins: recovering the structure of incomplete geochemical data. "
        "Computers & Geosciences (submitted).",
    ]
