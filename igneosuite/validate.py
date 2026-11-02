"""Masking validation: hide measured values, re-estimate them, and score each method."""
from __future__ import annotations
import time
import numpy as np
import pandas as pd
from .imputers import impute


def mask_scattered(M: np.ndarray, frac: float, rng: np.random.Generator) -> np.ndarray:
    """Hide a random fraction of the measured cells, keeping at least one value per sample."""
    obs = np.argwhere(~np.isnan(M))
    pick = obs[rng.choice(len(obs), int(frac * len(obs)), replace=False)]
    hide = np.zeros(M.shape, bool)
    hide[pick[:, 0], pick[:, 1]] = True
    return hide


def mask_block(M: np.ndarray, cols: list[int], frac: float, rng: np.random.Generator) -> np.ndarray:
    """Hide a whole group of variables in a fraction of the samples that have the group complete."""
    hide = np.zeros(M.shape, bool)
    if not cols:
        return hide
    full = np.where((~np.isnan(M[:, cols])).all(1))[0]
    n = int(frac * len(full))
    if n == 0:
        return hide
    rows = rng.choice(full, n, replace=False)
    hide[np.ix_(rows, cols)] = True
    return hide


def log_errors(true: np.ndarray, est: np.ndarray) -> np.ndarray:
    """|log10(estimate/true)|; NaN where either value is non-positive."""
    with np.errstate(divide="ignore", invalid="ignore"):
        e = np.abs(np.log10(est / true))
    e[(true <= 0) | (est <= 0) | ~np.isfinite(e)] = np.nan
    return e


def run(M: np.ndarray, columns: list[str], methods: list[str], scenario: str = "scattered",
        frac: float = 0.05, block_cols: list[int] | None = None, reps: int = 3, seed0: int = 0,
        progress=None) -> pd.DataFrame:
    """Return a long table: one row per hidden cell per method per repetition."""
    out = []
    total = reps * len(methods)
    step = 0
    for r in range(reps):
        rng = np.random.default_rng(seed0 + r)
        hide = mask_scattered(M, frac, rng) if scenario == "scattered" else mask_block(M, block_cols or [], frac, rng)
        if not hide.any():
            continue
        Mm = M.copy(); Mm[hide] = np.nan
        ii, jj = np.where(hide)
        true = M[ii, jj]
        for m in methods:
            if progress:
                progress(step / total, f"running {m}, repetition {r + 1} of {reps}")
            t0 = time.time()
            est_full = impute(Mm, m, seed=seed0 + r)
            dt = time.time() - t0
            est = est_full[ii, jj]
            err = log_errors(true, est)
            out.append(pd.DataFrame(dict(method=m, rep=r, variable=np.array(columns)[jj], col=jj, row=ii,
                                         true=true, estimate=est, log_err=err, seconds=dt)))
            step += 1
            if progress:
                progress(step / total, f"{m} finished, repetition {r + 1} of {reps}")
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _var_median(d):
    """Median over variables of the per-variable median |log10 error| (each element weighted equally)."""
    return d.groupby("variable").log_err.median().median()


def score(long: pd.DataFrame) -> pd.DataFrame:
    """Summary per method, ranked by median |log10 error| (mean over repetitions).

    The headline error is the median over variables of each variable's median error, so that
    well-measured majors do not dominate; this is the statistic reported in the paper.
    """
    if long.empty:
        return pd.DataFrame()
    g = long.groupby("method")
    per_rep = long.groupby(["method", "rep"])
    med = per_rep.apply(_var_median).groupby("method").mean()
    t = pd.DataFrame({
        "Median |log10 error|": med,
        "Typical factor (×)": 10 ** med,
        "Within ×1.25 (%)": per_rep.log_err.apply(lambda e: 100 * (e <= np.log10(1.25)).mean()).groupby("method").mean(),
        "Within ×2 (%)": per_rep.log_err.apply(lambda e: 100 * (e <= np.log10(2)).mean()).groupby("method").mean(),
        "90th pct |log10 error|": g.log_err.quantile(0.9),
        "Seconds per run": per_rep.seconds.first().groupby("method").mean(),
        "Hidden cells per run": per_rep.size().groupby("method").mean().round().astype(int),
    }).sort_values("Median |log10 error|")
    t.insert(0, "Rank", range(1, len(t) + 1))
    return t


def per_variable(long: pd.DataFrame, method: str, q: float = 0.68) -> pd.DataFrame:
    d = long[long.method == method]
    g = d.groupby("variable", sort=False)
    return pd.DataFrame({"Median |log10 error|": g.log_err.median(),
                         f"q{int(q*100)} |log10 error|": g.log_err.quantile(q),
                         "Within ×2 (%)": g.log_err.apply(lambda e: 100 * (e <= np.log10(2)).mean()),
                         "Hidden cells": g.size()})


def recommend(table: pd.DataFrame, tolerance: float = 0.01) -> tuple[str, str]:
    """Pick the most accurate method; prefer a faster one if it is within `tolerance` in log10 error."""
    if table.empty:
        return "", ""
    best = table.index[0]
    e0 = table.loc[best, "Median |log10 error|"]
    close = table[table["Median |log10 error|"] <= e0 + tolerance]
    fast = close["Seconds per run"].idxmin()
    if fast != best:
        why = (f"{fast} is within {tolerance:.2f} log10 units of the most accurate method ({best}) "
               f"and runs faster, so it is recommended.")
        return fast, why
    return best, f"{best} gave the lowest median error."


# Seconds per run measured on 2,737 samples x 45 variables (one CPU core of a laptop), and how each
# method scales with the number of samples (a) and variables (b).
_BASE = {"Mean": (0.01, 1, 1), "Median": (0.02, 1, 1), "KNN": (1.5, 2, 1), "MICE": (7, 1, 2),
         "missForest": (110, 1.1, 2), "DAE": (30, 1, 1), "GAIN": (25, 0.3, 1)}


def estimate_seconds(methods, n, p, reps) -> tuple[float, float]:
    """Rough range (low, high) of the time one test takes, in seconds."""
    t = sum(_BASE.get(m, (10, 1, 1))[0] * (n / 2737) ** _BASE.get(m, (10, 1, 1))[1]
            * (p / 45) ** _BASE.get(m, (10, 1, 1))[2] for m in methods) * reps
    return t, t * 3      # web servers are often slower than a laptop


def describe_seconds(lo, hi) -> str:
    def f(x):
        return f"{x:.0f} seconds" if x < 90 else f"{x / 60:.0f} minutes" if x < 5400 else f"{x / 3600:.1f} hours"
    if hi < 20:
        return "less than half a minute"
    return f"about {f(lo)} to {f(hi)}"


QUANTILES = (0.68, 0.90, 0.95)


def compact(long: pd.DataFrame, max_points: int = 1500, seed: int = 0) -> dict:
    """Everything later steps and figures need from a test, small enough to store.

    score    – summary per method (table and bar chart)
    pervar   – median |log10 error| per variable (rows) and method (columns)
    q        – per quantile: |log10 error| quantile per variable and method (error bands in step 4)
    counts   – hidden cells per variable and method
    sample   – up to `max_points` hidden cells per method (measured-vs-estimated figure)
    """
    if long.empty:
        return {}
    order = list(dict.fromkeys(long.variable))
    pervar = long.groupby(["variable", "method"]).log_err.median().unstack(1).reindex(order)
    q = {f"{x:.2f}": long.groupby(["variable", "method"]).log_err.quantile(x).unstack(1).reindex(order)
         for x in QUANTILES}
    counts = long.groupby(["variable", "method"]).log_err.count().unstack(1).reindex(order)
    ok = long[(long.true > 0) & (long.estimate > 0)]
    sample = pd.concat([d.sample(min(len(d), max_points), random_state=seed) for _, d in ok.groupby("method")]
                       )[["method", "variable", "true", "estimate"]].reset_index(drop=True)
    return dict(score=score(long), pervar=pervar, q=q, counts=counts, sample=sample)
