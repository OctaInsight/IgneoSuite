"""Element-specific errors for every estimated value."""
from __future__ import annotations
import numpy as np
import pandas as pd


def error_factors(test_s: dict, test_b: dict | None, method: str, columns: list[str], q: float = 0.68) -> pd.DataFrame:
    """Per variable: q-th percentile of |log10 error| from the scattered test and, where tested, the block test.

    `test_s` and `test_b` are compact test results (validate.compact)."""
    key = f"{q:.2f}"

    def col(test):
        if not test or method not in test["q"][key]:
            return pd.Series(np.nan, index=columns), pd.Series(0, index=columns)
        return (test["q"][key][method].reindex(columns).astype(float),
                test["counts"][method].reindex(columns).fillna(0).astype(int))

    qs, ns = col(test_s)
    qb, nb = col(test_b)
    t = pd.DataFrame({"q_scattered": qs, "q_block": qb, "n_scattered": ns, "n_block": nb}, index=columns)
    t.index.name = "variable"
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
