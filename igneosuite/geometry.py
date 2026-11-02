"""Shape of the data cloud (the 'data geometry' section of the paper).

All measures are computed on log10-transformed, standardised values.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors

EXPLAIN = {
    "n_samples": "Samples used.",
    "n_variables": "Variables used.",
    "pcs_80": "Principal components needed to explain 80% of the variance. Few components: the data are "
              "dominated by a few trends.",
    "pcs_90": "Principal components needed to explain 90% of the variance.",
    "participation_ratio": "Effective number of dimensions from the variance spectrum "
                           "(1 = all variance on one axis; equal to the number of variables if spread evenly).",
    "twonn_dimension": "Intrinsic dimension from nearest-neighbour distances (TwoNN; Facco et al., 2017): "
                       "how many directions the samples really spread in locally.",
    "hopkins": "Hopkins statistic: about 0.5 for randomly spread points, near 1 for strongly grouped data.",
    "nn_ratio_vs_gaussian": "Median nearest-neighbour distance divided by that of a Gaussian cloud with the same "
                            "covariance. Below 1: samples sit in tighter groups than a single blob would give.",
    "same_reference_nn": "Share of samples whose nearest neighbour comes from the same reference (publication).",
    "same_reference_chance": "The same share expected by chance, given how many samples each reference has.",
}


def prepare(X: np.ndarray) -> np.ndarray:
    from .transform import LogStandardiser
    return LogStandardiser().fit(X).transform(X)


def analyse(Z: np.ndarray, refs=None, seed: int = 0, n_hopkins: int = 20) -> dict:
    n, p = Z.shape
    pca = PCA().fit(Z)
    ev = pca.explained_variance_ratio_
    c = np.cumsum(ev)
    pr = float(ev.sum() ** 2 / (ev ** 2).sum())
    nn = NearestNeighbors(n_neighbors=3).fit(Z)
    dist, ind = nn.kneighbors(Z)
    r1, r2 = dist[:, 1], dist[:, 2]
    ok = r1 > 0
    mu = np.sort(r2[ok] / r1[ok])[: int(0.9 * ok.sum())]
    twonn = float(len(mu) / np.sum(np.log(mu))) if len(mu) else np.nan
    rng = np.random.default_rng(seed)
    m = max(1, int(0.05 * n)); H = []
    for _ in range(n_hopkins):
        s = rng.choice(n, m, replace=False)
        U = rng.uniform(Z.min(0), Z.max(0), (m, p))
        u = nn.kneighbors(U, n_neighbors=1)[0][:, 0]
        w = nn.kneighbors(Z[s], n_neighbors=2)[0][:, 1]
        H.append(u.sum() / (u.sum() + w.sum()))
    G = rng.multivariate_normal(Z.mean(0), np.cov(Z.T), n)
    gnn = NearestNeighbors(n_neighbors=2).fit(G).kneighbors(G)[0][:, 1]
    metrics = dict(n_samples=int(n), n_variables=int(p),
                   pcs_80=int(np.searchsorted(c, 0.8) + 1), pcs_90=int(np.searchsorted(c, 0.9) + 1),
                   participation_ratio=pr, twonn_dimension=twonn, hopkins=float(np.mean(H)),
                   nn_ratio_vs_gaussian=float(np.median(r1) / np.median(gnn)))
    if refs is not None:
        refs = np.asarray(refs, dtype=object)
        have = np.array([r is not None and str(r).strip() not in ("", "nan", "None") for r in refs])
        if have.sum() >= 10:
            same = refs[ind[:, 1]] == refs
            metrics["same_reference_nn"] = float(same[have & have[ind[:, 1]]].mean())
            freq = pd.Series(refs[have]).value_counts(normalize=True)
            metrics["same_reference_chance"] = float((freq ** 2).sum())
    k = min(3, p)
    return dict(metrics=metrics, explained=ev.tolist(),
                loadings=pca.components_[:k].T, scores=pca.transform(Z)[:, :k])
