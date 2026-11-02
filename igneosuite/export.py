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
