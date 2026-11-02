"""Figures in the style of the paper (no text below 7 pt)."""
from __future__ import annotations
import io
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SEQ = LinearSegmentedColormap.from_list("seq", ["#ffffff", "#cfe0f5", "#2a78d6", "#0b2f5e"])
DIV = LinearSegmentedColormap.from_list("div", ["#eb6834", "#ffffff", "#2a78d6"])

plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7,
    "legend.fontsize": 7, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "figure.dpi": 150, "savefig.dpi": 300, "font.family": "DejaVu Sans",
})
METHOD_COLOUR = {"KNN": CAT[0], "missForest": CAT[2], "DAE": CAT[6], "MICE": CAT[3], "GAIN": CAT[4],
                 "Median": INK2, "Mean": "#9a9893"}


def to_png(fig) -> bytes:
    for t in fig.findobj(matplotlib.text.Text):
        if t.get_text() and t.get_fontsize() < 7:
            t.set_fontsize(7)
    b = io.BytesIO(); fig.savefig(b, format="png", bbox_inches="tight"); plt.close(fig)
    return b.getvalue()


def missing_bar(pv):
    d = pv.reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(6.5, 2.6))
    col = {"Major oxides": CAT[0], "Trace elements": CAT[1], "REE": CAT[2]}
    ax.bar(range(len(d)), d["Missing %"], color=[col.get(g, INK2) for g in d.Group], width=0.75)
    ax.set_xticks(range(len(d))); ax.set_xticklabels([str(v).split()[0] for v in d.Variable], rotation=90)
    ax.set_ylabel("Missing values (%)"); ax.set_ylim(0, 100); ax.grid(axis="x", visible=False)
    ax.set_xlim(-0.6, len(d) - 0.4)
    for g, c in col.items():
        if (d.Group == g).any():
            ax.bar([0], [0], color=c, label=g)
    ax.legend(loc="upper left", frameon=False, ncol=3)
    return fig


def missing_matrix(X, order_rows=True):
    M = X.isna().values
    if order_rows:
        M = M[np.argsort(M.sum(1), kind="stable")]
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    ax.imshow(~M, aspect="auto", cmap=LinearSegmentedColormap.from_list("m", ["#ffffff", CAT[0]]), interpolation="nearest")
    ax.set_xticks(range(X.shape[1])); ax.set_xticklabels([str(c).split()[0] for c in X.columns], rotation=90)
    ax.set_ylabel("Samples (sorted by number missing)"); ax.grid(False)
    ax.set_title("Measured (blue) and missing (white) values", loc="left")
    return fig


def phi_heatmap(phi):
    n = len(phi)
    fig, ax = plt.subplots(figsize=(6.5, 6.0))
    im = ax.imshow(phi.values, cmap=DIV, vmin=-1, vmax=1)
    ax.set_xticks(range(n)); ax.set_xticklabels(phi.columns, rotation=90)
    ax.set_yticks(range(n)); ax.set_yticklabels(phi.index); ax.grid(False)
    cb = fig.colorbar(im, ax=ax, shrink=0.7); cb.set_label("φ (co-missingness)")
    return fig


def method_bars(table):
    t = table.sort_values("Median |log10 error|", ascending=False)
    fig, axes = plt.subplots(1, 2, figsize=(6.5, 0.35 * len(t) + 1.2), sharey=True)
    c = [METHOD_COLOUR.get(m, INK2) for m in t.index]
    axes[0].barh(t.index, t["Median |log10 error|"], color=c)
    axes[0].set_xlabel("Median |log10(estimate/true)|")
    axes[1].barh(t.index, t["Within ×2 (%)"], color=c)
    axes[1].set_xlabel("Estimates within a factor of 2 (%)"); axes[1].set_xlim(0, 100)
    for a in axes:
        a.grid(axis="y", visible=False)
    for i, (e, w) in enumerate(zip(t["Median |log10 error|"], t["Within ×2 (%)"])):
        axes[0].text(e, i, f" {e:.3f}", va="center", fontsize=7, color=INK)
        axes[1].text(w, i, f" {w:.0f}", va="center", fontsize=7, color=INK)
    fig.tight_layout()
    return fig


def per_variable_errors(pervar, methods):
    """pervar: median |log10 error| per variable (rows) and method (columns)."""
    vars_ = list(pervar.index)
    fig, ax = plt.subplots(figsize=(6.5, 3.0))
    w = 0.8 / max(len(methods), 1)
    for i, m in enumerate(methods):
        ax.bar(np.arange(len(vars_)) + (i - (len(methods) - 1) / 2) * w, pervar[m].values, w,
               color=METHOD_COLOUR.get(m, CAT[i % 8]), label=m)
    ax.set_xticks(range(len(vars_))); ax.set_xticklabels([str(v).split()[0] for v in vars_], rotation=90)
    ax.set_ylabel("Median |log10 error|"); ax.legend(frameon=False, ncol=min(len(methods), 4)); ax.grid(axis="x", visible=False)
    return fig


def true_vs_est(sample, method):
    """sample: hidden cells with columns method, true, estimate."""
    d = sample[sample.method == method]
    fig, ax = plt.subplots(figsize=(3.2, 3.2))
    ax.scatter(d.true, d.estimate, s=4, alpha=0.4, color=METHOD_COLOUR.get(method, CAT[0]), lw=0)
    lo, hi = np.nanmin([d.true.min(), d.estimate.min()]), np.nanmax([d.true.max(), d.estimate.max()])
    xs = np.array([lo, hi])
    ax.plot(xs, xs, color=INK, lw=0.8); ax.plot(xs, 2 * xs, color=INK2, lw=0.6, ls="--"); ax.plot(xs, xs / 2, color=INK2, lw=0.6, ls="--")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Measured (hidden) value"); ax.set_ylabel(f"{method} estimate")
    ax.set_title("Dashed lines: factor of 2", loc="left", fontsize=7, color=INK2)
    return fig


def scree(ev):
    ev = np.asarray(ev); c = np.cumsum(ev); n = len(ev)
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    ax.bar(np.arange(1, n + 1), 100 * ev, color=CAT[0], width=0.7, label="Each component")
    ax.plot(np.arange(1, n + 1), 100 * c, color=CAT[1], marker="o", ms=2.5, lw=1, label="Cumulative")
    ax.axhline(80, color=INK2, ls=":", lw=0.8); ax.text(n, 81, "80%", ha="right", va="bottom", fontsize=7, color=INK2)
    ax.set_xlabel("Principal component"); ax.set_ylabel("Variance explained (%)"); ax.set_ylim(0, 105)
    ax.legend(frameon=False, loc="center right"); ax.grid(axis="x", visible=False)
    return fig


def loadings(L, names, ev):
    """L: variables × components loadings; first two components are drawn."""
    k = min(2, L.shape[1])
    fig, axes = plt.subplots(1, k, figsize=(6.5, max(2.6, 0.13 * len(names) + 0.8)), sharey=True)
    axes = np.atleast_1d(axes)
    y = np.arange(len(names))
    for j, ax in enumerate(axes):
        v = L[:, j]
        ax.barh(y, v, color=[CAT[0] if x >= 0 else CAT[1] for x in v], height=0.75)
        ax.axvline(0, color=INK2, lw=0.6)
        ax.set_title(f"PC{j + 1} ({100 * ev[j]:.0f}%)", loc="left"); ax.grid(axis="y", visible=False)
        ax.set_xlabel("Loading")
    axes[0].set_yticks(y); axes[0].set_yticklabels([str(n).split()[0] for n in names]); axes[0].invert_yaxis()
    fig.tight_layout()
    return fig


def pc_scores(P, ev, colour=None, colour_label=None, labels=None):
    fig, ax = plt.subplots(figsize=(3.4, 3.2))
    if labels is not None:
        for l in np.unique(labels):
            s = labels == l
            ax.scatter(P[s, 0], P[s, 1], s=4, alpha=0.6, lw=0, color=CAT[(int(l) - 1) % 8], label=f"C{l}")
        ax.legend(frameon=False, markerscale=2)
    elif colour is not None and np.isfinite(colour).any():
        ok = np.isfinite(colour)
        ax.scatter(P[~ok, 0], P[~ok, 1], s=4, alpha=0.4, lw=0, color="#b9b7b1", label="no value")
        sc = ax.scatter(P[ok, 0], P[ok, 1], s=4, alpha=0.7, lw=0, c=colour[ok], cmap=SEQ)
        cb = fig.colorbar(sc, ax=ax, shrink=0.8); cb.set_label(colour_label or "")
    else:
        ax.scatter(P[:, 0], P[:, 1], s=4, alpha=0.5, lw=0, color=CAT[0])
    ax.set_xlabel(f"PC1 ({100*ev[0]:.0f}%)"); ax.set_ylabel(f"PC2 ({100*ev[1]:.0f}%)")
    return fig


def k_scan(scan):
    fig, axes = plt.subplots(1, 4, figsize=(6.5, 1.9))
    for a, c, col in zip(axes, scan.columns, CAT):
        a.plot(scan.index, scan[c], marker="o", ms=3, color=col); a.set_title(c, fontsize=7); a.set_xlabel("k")
    fig.tight_layout()
    return fig


def pca_scatter(P, ev, labels, title=""):
    fig, ax = plt.subplots(figsize=(3.4, 3.2))
    for i, l in enumerate(np.unique(labels)):
        s = labels == l
        ax.scatter(P[s, 0], P[s, 1], s=4, alpha=0.6, lw=0, color=CAT[(int(l) - 1) % 8], label=f"C{l}")
    ax.set_xlabel(f"PC1 ({100*ev[0]:.0f}%)"); ax.set_ylabel(f"PC2 ({100*ev[1]:.0f}%)")
    ax.legend(frameon=False, markerscale=2); ax.set_title(title, loc="left")
    return fig


def clusters_3d(P, ev, labels, title="", azim=-60, elev=25):
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
    fig = plt.figure(figsize=(4.6, 4.2))
    ax = fig.add_subplot(projection="3d")
    for l in np.unique(labels):
        s = labels == l
        ax.scatter(P[s, 0], P[s, 1], P[s, 2], s=3, alpha=0.7, color=CAT[(int(l) - 1) % 8], label=f"C{l}", depthshade=False)
    ax.set_xlabel(f"PC1 ({100*ev[0]:.0f}%)"); ax.set_ylabel(f"PC2 ({100*ev[1]:.0f}%)"); ax.set_zlabel(f"PC3 ({100*ev[2]:.0f}%)")
    ax.view_init(elev=elev, azim=azim); ax.legend(frameon=False, markerscale=2, loc="upper left")
    ax.set_title(title, loc="left")
    return fig
