"""Optional cluster analysis to see how gap-filling changes the grouping."""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score, calinski_harabasz_score, davies_bouldin_score, adjusted_rand_score
from .transform import LogStandardiser


def prepare(X: np.ndarray) -> np.ndarray:
    t = LogStandardiser().fit(X)
    return t.transform(X)


def scan_k(Z: np.ndarray, ks=range(2, 9), seed=0, n_boot=10) -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(seed)
    sub = rng.choice(len(Z), min(len(Z), 3000), replace=False)
    for k in ks:
        km = KMeans(k, n_init=10, random_state=seed).fit(Z)
        lab = km.labels_
        aris = []
        for b in range(n_boot):
            idx = rng.choice(len(Z), int(0.8 * len(Z)), replace=False)
            kb = KMeans(k, n_init=5, random_state=seed + b + 1).fit(Z[idx])
            aris.append(adjusted_rand_score(lab, kb.predict(Z)))
        rows.append(dict(k=k, Silhouette=silhouette_score(Z[sub], lab[sub]),
                         **{"Calinski–Harabasz": calinski_harabasz_score(Z, lab),
                            "Davies–Bouldin": davies_bouldin_score(Z, lab),
                            "Stability (mean ARI)": float(np.mean(aris))}))
    return pd.DataFrame(rows).set_index("k")


def kmeans(Z: np.ndarray, k: int, seed=0) -> np.ndarray:
    return KMeans(k, n_init=20, random_state=seed).fit_predict(Z) + 1


def match_labels(ref: np.ndarray, new: np.ndarray) -> np.ndarray:
    """Relabel `new` so that its clusters overlap the reference clusters as much as possible."""
    from scipy.optimize import linear_sum_assignment
    a, b = np.unique(ref), np.unique(new)
    C = np.array([[np.sum((ref == i) & (new == j)) for j in b] for i in a])
    r, c = linear_sum_assignment(-C)
    m = {b[cj]: a[ri] for ri, cj in zip(r, c)}
    nxt = max(a) + 1
    for j in b:
        if j not in m:
            m[j] = nxt; nxt += 1
    return np.array([m[x] for x in new])


def pca(Z: np.ndarray, n=2):
    p = PCA(n).fit(Z)
    return p.transform(Z), p.explained_variance_ratio_
