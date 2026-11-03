"""Imputation methods compared in Abu-Alam et al. ('When simpler wins')."""
from __future__ import annotations
import numpy as np
from sklearn.experimental import enable_iterative_imputer  # noqa: F401
from sklearn.impute import KNNImputer, IterativeImputer
from sklearn.linear_model import BayesianRidge
from sklearn.ensemble import RandomForestRegressor
from .transform import LogStandardiser
import os

# Streamlit Community Cloud gives an app about 2 CPU cores; using more only gets the app throttled.
N_THREADS = max(1, min(2, os.cpu_count() or 1))

try:
    import torch
    import torch.nn as nn
    torch.set_num_threads(N_THREADS)
    HAS_TORCH = True
except Exception:  # pragma: no cover
    HAS_TORCH = False


def _empty_cols(M):
    return np.all(np.isnan(M), 0)


def mean_impute(M, seed=0):
    return np.where(np.isnan(M), np.nanmean(M, 0), M)


def median_impute(M, seed=0):
    return np.where(np.isnan(M), np.nanmedian(M, 0), M)


def knn_impute(M, seed=0, k=5):
    t = LogStandardiser().fit(M)
    Z = KNNImputer(n_neighbors=k, weights="distance", keep_empty_features=True).fit_transform(t.transform(M))
    return np.where(np.isnan(M), t.inverse(Z), M)


def mice_impute(M, seed=0, max_iter=20):
    t = LogStandardiser().fit(M)
    Z = IterativeImputer(estimator=BayesianRidge(), max_iter=max_iter, tol=1e-3, initial_strategy="median",
                         random_state=seed, keep_empty_features=True).fit_transform(t.transform(M))
    return np.where(np.isnan(M), t.inverse(Z), M)


def missforest_impute(M, seed=0, n_trees=50, max_iter=5):
    t = LogStandardiser().fit(M)
    est = RandomForestRegressor(n_estimators=n_trees, min_samples_leaf=2, max_features=0.33, n_jobs=N_THREADS, random_state=seed)
    Z = IterativeImputer(estimator=est, max_iter=max_iter, tol=1e-3, initial_strategy="median",
                         random_state=seed, keep_empty_features=True).fit_transform(t.transform(M))
    return np.where(np.isnan(M), t.inverse(Z), M)


def dae_impute(M, seed=0, epochs=500, drop=0.25, hidden=(128, 64), lr=1e-3, batch=128):
    """Denoising autoencoder (Vincent et al., 2008; Gondara and Wang, 2018)."""
    if not HAS_TORCH:
        raise RuntimeError("PyTorch is not installed; the denoising autoencoder is unavailable.")
    torch.manual_seed(seed)
    t = LogStandardiser().fit(M)
    Z = t.transform(M)
    obs = ~np.isnan(Z)
    X = torch.tensor(np.where(obs, Z, 0.0), dtype=torch.float32)
    O = torch.tensor(obs, dtype=torch.float32)
    p = Z.shape[1]
    h1, h2 = hidden
    net = nn.Sequential(nn.Linear(2 * p, h1), nn.ReLU(), nn.Linear(h1, h2), nn.ReLU(), nn.Linear(h2, h1), nn.ReLU(), nn.Linear(h1, p))
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=1e-5)
    n = len(X)
    for _ in range(epochs):
        perm = torch.randperm(n)
        for i in range(0, n, batch):
            b = perm[i:i + batch]
            x, o = X[b], O[b]
            keep = (torch.rand_like(o) > drop).float() * o
            out = net(torch.cat([x * keep, keep], 1))
            loss = (((out - x) ** 2) * o).sum() / o.sum().clamp(min=1)
            opt.zero_grad(); loss.backward(); opt.step()
    with torch.no_grad():
        R = net(torch.cat([X, O], 1)).numpy()
    return np.where(np.isnan(M), t.inverse(np.where(obs, Z, R)), M)


def gain_impute(M, seed=0, iters=5000, batch=128, hint=0.9, alpha=100, lr=1e-3):
    """Generative adversarial imputation nets (Yoon et al., 2018)."""
    if not HAS_TORCH:
        raise RuntimeError("PyTorch is not installed; GAIN is unavailable.")
    torch.manual_seed(seed)
    t = LogStandardiser().fit(M)
    Z = t.transform(M)
    obs = ~np.isnan(Z)
    lo, hi = np.nanmin(Z, 0), np.nanmax(Z, 0)
    lo = np.where(np.isfinite(lo), lo, 0); hi = np.where(np.isfinite(hi), hi, 1)
    N = (Z - lo) / (hi - lo + 1e-9)
    X = torch.tensor(np.where(obs, N, 0.0), dtype=torch.float32)
    Mk = torch.tensor(obs, dtype=torch.float32)
    n, p = X.shape
    G = nn.Sequential(nn.Linear(2 * p, p), nn.ReLU(), nn.Linear(p, p), nn.ReLU(), nn.Linear(p, p), nn.Sigmoid())
    D = nn.Sequential(nn.Linear(2 * p, p), nn.ReLU(), nn.Linear(p, p), nn.ReLU(), nn.Linear(p, p), nn.Sigmoid())
    oG, oD = torch.optim.Adam(G.parameters(), lr=lr), torch.optim.Adam(D.parameters(), lr=lr)
    for _ in range(iters):
        b = torch.randint(0, n, (min(batch, n),))
        x, m = X[b], Mk[b]
        xin = m * x + (1 - m) * torch.rand_like(x) * 0.01
        H = (torch.rand_like(m) < hint).float() * m
        g = G(torch.cat([xin, m], 1)); xhat = m * x + (1 - m) * g
        d = D(torch.cat([xhat.detach(), H], 1))
        lD = -torch.mean(m * torch.log(d + 1e-8) + (1 - m) * torch.log(1 - d + 1e-8))
        oD.zero_grad(); lD.backward(); oD.step()
        g = G(torch.cat([xin, m], 1)); xhat = m * x + (1 - m) * g
        d = D(torch.cat([xhat, H], 1))
        lG = -torch.mean((1 - m) * torch.log(d + 1e-8)) + alpha * torch.sum((m * x - m * g) ** 2) / torch.sum(m)
        oG.zero_grad(); lG.backward(); oG.step()
    with torch.no_grad():
        g = G(torch.cat([Mk * X + (1 - Mk) * torch.rand_like(X) * 0.01, Mk], 1)).numpy()
    Zg = np.where(obs, N, g) * (hi - lo + 1e-9) + lo
    return np.where(np.isnan(M), t.inverse(Zg), M)


METHODS = {
    "Mean": (mean_impute, "Column mean of the measured values"),
    "Median": (median_impute, "Column median of the measured values"),
    "KNN": (knn_impute, "Distance-weighted k-nearest neighbours, k = 5 (Troyanskaya et al., 2001)"),
    "MICE": (mice_impute, "Chained equations with Bayesian ridge regression (van Buuren and Groothuis-Oudshoorn, 2011)"),
    "missForest": (missforest_impute, "Chained random forests (Stekhoven and Bühlmann, 2012)"),
    "DAE": (dae_impute, "Denoising autoencoder (Gondara and Wang, 2018)"),
    "GAIN": (gain_impute, "Generative adversarial imputation nets (Yoon et al., 2018)"),
}
DEEP = {"DAE", "GAIN"}


def available_methods():
    return [m for m in METHODS if HAS_TORCH or m not in DEEP]


def impute(M: np.ndarray, method: str, seed: int = 0) -> np.ndarray:
    f = METHODS[method][0]
    out = f(M.astype(float), seed=seed)
    empty = _empty_cols(M)
    out[:, empty] = np.nan
    return out
