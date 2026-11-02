"""Describing the missing-value structure of a geochemical table."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .io import element_group, short_name


def summary(X: pd.DataFrame) -> dict:
    miss = X.isna()
    n, p = X.shape
    return dict(
        n_samples=n, n_variables=p,
        n_missing=int(miss.values.sum()), pct_missing=100 * miss.values.mean() if n * p else 0.0,
        n_complete=int((~miss.any(axis=1)).sum()),
        n_empty_rows=int(miss.all(axis=1).sum()),
        empty_cols=[c for c in X.columns if miss[c].all()],
    )


def per_variable(X: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in X.columns:
        v = X[c].dropna()
        rows.append(dict(Variable=c, Group=element_group(c), Measured=len(v),
                         Missing=int(X[c].isna().sum()), **{"Missing %": 100 * X[c].isna().mean()},
                         Median=v.median() if len(v) else np.nan,
                         Min=v.min() if len(v) else np.nan, Max=v.max() if len(v) else np.nan))
    return pd.DataFrame(rows)


def groups(X: pd.DataFrame) -> dict[str, list[str]]:
    g: dict[str, list[str]] = {}
    for c in X.columns:
        g.setdefault(element_group(c), []).append(c)
    return g


def co_missing_phi(X: pd.DataFrame) -> pd.DataFrame:
    """Phi coefficient between the missingness indicators of every pair of variables."""
    M = X.isna().astype(float)
    keep = [c for c in M.columns if 0 < M[c].mean() < 1]
    if len(keep) < 2:
        return pd.DataFrame()
    C = np.corrcoef(M[keep].values.T)
    return pd.DataFrame(C, index=[short_name(c) for c in keep], columns=[short_name(c) for c in keep])


def block_pattern(X: pd.DataFrame, cols: list[str]) -> dict:
    """How often a group of variables (e.g. the REE) is all present, all absent or partial."""
    if not cols:
        return {}
    m = X[cols].notna()
    k = m.sum(axis=1)
    return {"All measured": int((k == len(cols)).sum()), "None measured": int((k == 0).sum()),
            "Partly measured": int(((k > 0) & (k < len(cols))).sum())}


def completeness_curve(X: pd.DataFrame) -> pd.DataFrame:
    """Samples that are complete when variables are added in order of completeness."""
    order = X.notna().mean().sort_values(ascending=False).index
    rows, mask = [], np.ones(len(X), bool)
    for i, c in enumerate(order, 1):
        mask &= X[c].notna().values
        rows.append(dict(n_variables=i, variable=c, complete_samples=int(mask.sum()), pct=100 * mask.mean()))
    return pd.DataFrame(rows)
