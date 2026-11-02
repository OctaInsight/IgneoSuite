"""Element-specific errors for every estimated value."""
from __future__ import annotations
import numpy as np
import pandas as pd


def error_factors(long_scat: pd.DataFrame, long_block: pd.DataFrame | None, method: str,
                  columns: list[str], q: float = 0.68) -> pd.DataFrame:
    """Per variable: q-th percentile of |log10 error| (scattered and, where tested, block)."""
    rows = []
    for c in columns:
        s = long_scat[(long_scat.method == method) & (long_scat.variable == c)].log_err.dropna()
        b = (long_block[(long_block.method == method) & (long_block.variable == c)].log_err.dropna()
             if long_block is not None and not long_block.empty else pd.Series(dtype=float))
        rows.append(dict(variable=c,
                         q_scattered=s.quantile(q) if len(s) else np.nan,
                         q_block=b.quantile(q) if len(b) else np.nan,
                         n_scattered=len(s), n_block=len(b)))
    t = pd.DataFrame(rows).set_index("variable")
    fallback = np.nanmedian(t.q_scattered) if t.q_scattered.notna().any() else np.nan
    t["q_scattered"] = t.q_scattered.fillna(fallback)
    return t


def error_matrix(M: np.ndarray, est: np.ndarray, columns: list[str], factors: pd.DataFrame,
                 block_cols: list[int] | None = None) -> np.ndarray:
    """± error for each estimated cell; NaN for measured cells.

    The scattered-test error applies by default. For a block variable in a sample that lacks
    every block variable, the block-test error applies. ± = estimate × (f − 1/f)/2, f = 10^q.
    """
    miss = np.isnan(M)
    qs = factors.loc[columns, "q_scattered"].values.astype(float)
    Q = np.broadcast_to(qs, M.shape).copy()
    if block_cols:
        qb = factors.loc[[columns[j] for j in block_cols], "q_block"].values.astype(float)
        whole = miss[:, block_cols].all(1)
        for k, j in enumerate(block_cols):
            if np.isfinite(qb[k]):
                Q[whole, j] = qb[k]
    f = 10 ** Q
    E = est * (f - 1 / f) / 2
    E[~miss] = np.nan
    return E
