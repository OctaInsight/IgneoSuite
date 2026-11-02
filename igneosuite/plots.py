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


def per_variable_errors(long, methods):
    vars_ = list(dict.fromkeys(long.variable))
    fig, ax = plt.subplots(figsize=(6.5, 3.0))
    w = 0.8 / max(len(methods), 1)
    for i, m in enumerate(methods):
        med = long[long.method == m].groupby("variable").log_err.median().reindex(vars_)
        ax.bar(np.arange(len(vars_)) + (i - (len(methods) - 1) / 2) * w, med.values, w,
               color=METHOD_COLOUR.get(m, CAT[i % 8]), label=m)
    ax.set_xticks(range(len(vars_))); ax.set_xticklabels([str(v).split()[0] for v in vars_], rotation=90)
    ax.set_ylabel("Median |log10 error|"); ax.legend(frameon=False, ncol=min(len(methods), 4)); ax.grid(axis="x", visible=False)
    return fig


def true_vs_est(long, method, max_points=4000):
    d = long[(long.method == method) & (long.true > 0) & (long.estimate > 0)]
    if len(d) > max_points:
        d = d.sample(max_points, random_state=0)
    fig, ax = plt.subplots(figsize=(3.4, 3.4))
    ax.scatter(d.true, d.estimate, s=4, alpha=0.4, color=METHOD_COLOUR.get(method, CAT[0]), lw=0)
    lo, hi = np.nanmin([d.true.min(), d.estimate.min()]), np.nanmax([d.true.max(), d.estimate.max()])
    xs = np.array([lo, hi])
    ax.plot(xs, xs, color=INK, lw=0.8); ax.plot(xs, 2 * xs, color=INK2, lw=0.6, ls="--"); ax.plot(xs, xs / 2, color=INK2, lw=0.6, ls="--")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Measured (hidden) value"); ax.set_ylabel(f"{method} estimate")
    ax.set_title("Dashed lines: factor of 2", loc="left", fontsize=7, color=INK2)
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
