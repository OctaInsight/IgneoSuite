"""Interactive charts (Plotly) with hover details and download buttons.

All 2-D charts use plain SVG traces (no WebGL), so they show in every browser. Only the 3-D cluster
view needs the browser's 3-D graphics; a slider-driven fallback is provided for browsers without it.
Each chart gets a 'Download figure (PNG, 300 dpi)' button (drawn server-side with matplotlib) and a
'Download data (CSV)' button with the numbers behind the chart.
"""
from __future__ import annotations
import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from . import plots

CAT, INK, INK2, GRID = plots.CAT, plots.INK, plots.INK2, plots.GRID
FONT = dict(family="Source Sans Pro, Arial, sans-serif", size=12, color=INK)
METHOD_COLOUR = plots.METHOD_COLOUR


def _layout(fig, height=380, **kw):
    base = dict(template="plotly_white", font=FONT, height=height, margin=dict(l=55, r=15, t=35, b=45),
                hoverlabel=dict(font_size=12), legend=dict(bgcolor="rgba(255,255,255,0.8)"))
    if "legend" in kw:
        base["legend"].update(kw.pop("legend"))
    base.update(kw)
    fig.update_layout(**base)
    fig.update_xaxes(gridcolor=GRID, linecolor=INK2, showline=True, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor=INK2, showline=True, zeroline=False)
    return fig


def _slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")[:60] or "figure"


@st.cache_data(show_spinner=False, max_entries=200)
def _png(kind: str, args: tuple, kwargs_items: tuple) -> bytes:
    fn = getattr(plots, kind)
    return plots.to_png(fn(*args, **dict(kwargs_items)))


def show(fig, name: str, key: str, data: pd.DataFrame | None = None, png: tuple | None = None,
         caption: str | None = None):
    """Draw an interactive chart with its download buttons.

    png = (matplotlib function name in plots, args tuple, kwargs dict) for the 300-dpi figure."""
    slug = _slug(name)
    st.plotly_chart(fig, width="stretch", theme=None, key=key,
                    config={"displaylogo": False, "scrollZoom": False,
                            "modeBarButtonsToRemove": ["select2d", "lasso2d"],
                            "toImageButtonOptions": {"format": "png", "filename": slug, "scale": 3}})
    if caption:
        st.caption(caption)
    c1, c2, _ = st.columns([1, 1, 2])
    if png is not None:
        kind, args, kw = png
        try:
            c1.download_button("⬇ Figure (PNG, 300 dpi)", _png(kind, tuple(args), tuple(sorted((kw or {}).items()))),
                               f"{slug}.png", "image/png", key=key + "_png")
        except Exception:
            pass
    if data is not None:
        c2.download_button("⬇ Data (CSV)", data.to_csv(index=data.index.name is not None).encode(),
                           f"{slug}.csv", "text/csv", key=key + "_csv")


# ---------------------------------------------------------------- step 2
GROUP_COLOUR = {"Major oxides": CAT[0], "Trace elements": CAT[1], "REE": CAT[2]}


def missing_bar(pv):
    fig = go.Figure()
    for g, colour in GROUP_COLOUR.items():
        d = pv[pv.Group == g]
        if len(d):
            fig.add_bar(x=[str(v).split()[0] for v in d.Variable], y=d["Missing %"], name=g, marker_color=colour,
                        customdata=np.c_[d.Variable, d.Measured, d.Missing],
                        hovertemplate="<b>%{customdata[0]}</b><br>Missing: %{y:.1f}%<br>"
                                      "Measured: %{customdata[1]}<br>Missing: %{customdata[2]}<extra></extra>")
    order = [str(v).split()[0] for v in pv.Variable]
    fig.update_xaxes(categoryorder="array", categoryarray=order, tickangle=-90)
    fig.update_yaxes(title="Missing values (%)", range=[0, 100])
    return _layout(fig, 360, barmode="group", bargap=0.15, legend_orientation="h", legend_y=1.12)


def missing_matrix(X, ids):
    M = X.notna().values.astype(int)
    order = np.argsort((1 - M).sum(1), kind="stable")
    names = [str(c).split()[0] for c in X.columns]
    text = np.array(ids)[order]
    fig = go.Figure(go.Heatmap(z=M[order], x=names, y=np.arange(len(order)), colorscale=[[0, "#ffffff"], [1, CAT[0]]],
                               showscale=False, zmin=0, zmax=1, customdata=np.repeat(text[:, None], len(names), 1),
                               hovertemplate="Sample %{customdata}<br>%{x}: %{z}<extra>1 = measured, 0 = missing</extra>"))
    fig.update_yaxes(title="Samples (sorted by number missing)", showticklabels=False, autorange="reversed")
    fig.update_xaxes(tickangle=-90)
    return _layout(fig, 420)


def phi_heatmap(phi):
    fig = go.Figure(go.Heatmap(z=phi.values, x=list(phi.columns), y=list(phi.index), zmin=-1, zmax=1,
                               colorscale=[[0, CAT[1]], [0.5, "#ffffff"], [1, CAT[0]]],
                               colorbar=dict(title="φ"),
                               hovertemplate="%{y} and %{x}<br>φ = %{z:.2f}<extra></extra>"))
    fig.update_xaxes(tickangle=-90); fig.update_yaxes(autorange="reversed")
    return _layout(fig, 620)


# ---------------------------------------------------------------- step 3
def method_bars(score):
    t = score.sort_values("Median |log10 error|", ascending=False)
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.06,
                        subplot_titles=("Median |log10(estimate/true)|", "Estimates within a factor of 2 (%)"))
    colours = [METHOD_COLOUR.get(m, INK2) for m in t.index]
    fig.add_bar(y=list(t.index), x=t["Median |log10 error|"], orientation="h", marker_color=colours, row=1, col=1,
                text=[f"{v:.3f}" for v in t["Median |log10 error|"]], textposition="outside",
                customdata=t["Typical factor (×)"],
                hovertemplate="<b>%{y}</b><br>Median error %{x:.3f}<br>typical factor ×%{customdata:.2f}<extra></extra>")
    fig.add_bar(y=list(t.index), x=t["Within ×2 (%)"], orientation="h", marker_color=colours, row=1, col=2,
                text=[f"{v:.0f}" for v in t["Within ×2 (%)"]], textposition="outside",
                hovertemplate="<b>%{y}</b><br>%{x:.1f}% within ×2<extra></extra>")
    fig.update_xaxes(range=[0, 100], row=1, col=2)
    fig.update_xaxes(range=[0, float(t["Median |log10 error|"].max()) * 1.25], row=1, col=1)
    return _layout(fig, 70 + 45 * len(t), showlegend=False)


def per_variable_errors(pervar, methods):
    names = [str(v).split()[0] for v in pervar.index]
    fig = go.Figure()
    for i, m in enumerate(methods):
        fig.add_bar(x=names, y=pervar[m].values, name=m, marker_color=METHOD_COLOUR.get(m, CAT[i % 8]),
                    customdata=np.c_[list(pervar.index), 10 ** pervar[m].values],
                    hovertemplate="<b>%{customdata[0]}</b> · " + m +
                                  "<br>Median error %{y:.3f} (×%{customdata[1]:.2f})<extra></extra>")
    fig.update_yaxes(title="Median |log10 error|"); fig.update_xaxes(tickangle=-90)
    return _layout(fig, 380, barmode="group", legend_orientation="h", legend_y=1.12)


def true_vs_est(sample, method):
    d = sample[sample.method == method]
    lo, hi = float(np.nanmin([d.true.min(), d.estimate.min()])), float(np.nanmax([d.true.max(), d.estimate.max()]))
    fig = go.Figure()
    for f, dash, nm in ((1, "solid", "1:1"), (2, "dash", "×2"), (0.5, "dash", "÷2")):
        fig.add_scatter(x=[lo, hi], y=[lo * f, hi * f], mode="lines", line=dict(color=INK if f == 1 else INK2,
                        width=1, dash=dash), name=nm, hoverinfo="skip", showlegend=False)
    fig.add_scatter(x=d.true, y=d.estimate, mode="markers", name=method, showlegend=False,
                    marker=dict(size=5, color=METHOD_COLOUR.get(method, CAT[0]), opacity=0.5),
                    customdata=np.c_[d.variable, d.estimate / d.true],
                    hovertemplate="<b>%{customdata[0]}</b><br>Measured %{x:.4g}<br>Estimated %{y:.4g}"
                                  "<br>ratio %{customdata[1]:.2f}<extra></extra>")
    fig.update_xaxes(type="log", title="Measured (hidden) value")
    fig.update_yaxes(type="log", title=f"{method} estimate", scaleanchor="x")
    return _layout(fig, 420, title=dict(text="Dashed lines: factor of 2", font=dict(size=11, color=INK2)))


# ---------------------------------------------------------------- step 5
def scree(ev):
    ev = np.asarray(ev); n = len(ev); x = np.arange(1, n + 1)
    fig = go.Figure()
    fig.add_bar(x=x, y=100 * ev, name="Each component", marker_color=CAT[0],
                hovertemplate="PC%{x}: %{y:.1f}%<extra></extra>")
    fig.add_scatter(x=x, y=100 * np.cumsum(ev), name="Cumulative", mode="lines+markers",
                    line=dict(color=CAT[1]), marker=dict(size=4), hovertemplate="PC1–PC%{x}: %{y:.1f}%<extra></extra>")
    fig.add_hline(y=80, line=dict(color=INK2, dash="dot", width=1), annotation_text="80%")
    fig.update_xaxes(title="Principal component"); fig.update_yaxes(title="Variance explained (%)", range=[0, 105])
    return _layout(fig, 380, legend=dict(x=0.6, y=0.4))


def loadings(L, names, ev):
    k = min(2, L.shape[1]); short = [str(n).split()[0] for n in names]
    fig = make_subplots(rows=1, cols=k, shared_yaxes=True, horizontal_spacing=0.05,
                        subplot_titles=[f"PC{j + 1} ({100 * ev[j]:.0f}%)" for j in range(k)])
    for j in range(k):
        v = L[:, j]
        fig.add_bar(y=short, x=v, orientation="h", row=1, col=j + 1, showlegend=False,
                    marker_color=[CAT[0] if x >= 0 else CAT[1] for x in v], customdata=list(names),
                    hovertemplate="<b>%{customdata}</b><br>PC" + str(j + 1) + " loading %{x:.3f}<extra></extra>")
    fig.update_yaxes(autorange="reversed"); fig.update_xaxes(title="Loading")
    return _layout(fig, max(320, 16 * len(names) + 90))


def _hover_sample(ids, extra: dict):
    cols = [np.asarray(ids, dtype=object)] + [np.asarray(v, dtype=object) for v in extra.values()]
    tmpl = "<b>Sample %{customdata[0]}</b>" + "".join(f"<br>{k}: %{{customdata[{i + 1}]}}" for i, k in enumerate(extra))
    return np.column_stack(cols), tmpl


def pc_scores(P, ev, ids, colour=None, colour_label=None, labels=None, extra=None):
    extra = extra or {}
    fig = go.Figure()
    xy = "<br>PC1 %{x:.2f}, PC2 %{y:.2f}<extra></extra>"
    if labels is not None:
        for l in np.unique(labels):
            s = labels == l
            cd, t = _hover_sample(np.asarray(ids)[s], {k: np.asarray(v)[s] for k, v in extra.items()})
            fig.add_scatter(x=P[s, 0], y=P[s, 1], mode="markers", name=f"C{l}", customdata=cd, hovertemplate=t + xy,
                            marker=dict(size=5, color=CAT[(int(l) - 1) % 8], opacity=0.7))
    elif colour is not None and np.isfinite(colour).any():
        ok = np.isfinite(colour)
        for sel, kw in ((~ok, dict(color="#b9b7b1")), (ok, dict(color=colour[ok], colorscale="Blues",
                                                               colorbar=dict(title=colour_label or ""), showscale=True))):
            if sel.any():
                cd, t = _hover_sample(np.asarray(ids)[sel], {k: np.asarray(v)[sel] for k, v in extra.items()})
                fig.add_scatter(x=P[sel, 0], y=P[sel, 1], mode="markers", customdata=cd, hovertemplate=t + xy,
                                name="no value" if sel is not ok else colour_label, showlegend=False,
                                marker=dict(size=5, opacity=0.75, **kw))
    else:
        cd, t = _hover_sample(ids, extra)
        fig.add_scatter(x=P[:, 0], y=P[:, 1], mode="markers", customdata=cd, hovertemplate=t + xy, showlegend=False,
                        marker=dict(size=5, color=CAT[0], opacity=0.6))
    fig.update_xaxes(title=f"PC1 ({100 * ev[0]:.0f}%)"); fig.update_yaxes(title=f"PC2 ({100 * ev[1]:.0f}%)")
    return _layout(fig, 420)


# ---------------------------------------------------------------- step 6
def k_scan(scan):
    fig = make_subplots(rows=1, cols=len(scan.columns), subplot_titles=list(scan.columns), horizontal_spacing=0.07)
    for j, (c, colour) in enumerate(zip(scan.columns, CAT)):
        fig.add_scatter(x=list(scan.index), y=scan[c], mode="lines+markers", line=dict(color=colour), row=1, col=j + 1,
                        showlegend=False, hovertemplate="k = %{x}<br>" + c + ": %{y:.3f}<extra></extra>")
    fig.update_xaxes(title="k", dtick=1)
    fig.update_annotations(font_size=11)
    return _layout(fig, 280)


def clusters_2d(P, ev, labels, ids, other_labels, other_name, title):
    fig = go.Figure()
    for l in np.unique(labels):
        s = labels == l
        cd = np.column_stack([np.asarray(ids)[s], other_labels[s]])
        fig.add_scatter(x=P[s, 0], y=P[s, 1], mode="markers", name=f"C{l} ({int(s.sum())})", customdata=cd,
                        marker=dict(size=5, color=CAT[(int(l) - 1) % 8], opacity=0.75),
                        hovertemplate=f"<b>Sample %{{customdata[0]}}</b><br>{title}: C{l}<br>"
                                      f"{other_name}: C%{{customdata[1]}}<br>PC1 %{{x:.2f}}, PC2 %{{y:.2f}}<extra></extra>")
    fig.update_xaxes(title=f"PC1 ({100 * ev[0]:.0f}%)"); fig.update_yaxes(title=f"PC2 ({100 * ev[1]:.0f}%)")
    return _layout(fig, 430, title=dict(text=title, font=dict(size=13)), legend=dict(itemsizing="constant"))


def clusters_3d(P, ev, labels, ids, other_labels, other_name, title):
    fig = go.Figure()
    for l in np.unique(labels):
        s = labels == l
        cd = np.column_stack([np.asarray(ids)[s], other_labels[s]])
        fig.add_scatter3d(x=P[s, 0], y=P[s, 1], z=P[s, 2], mode="markers", name=f"C{l} ({int(s.sum())})", customdata=cd,
                          marker=dict(size=2.6, color=CAT[(int(l) - 1) % 8], opacity=0.85),
                          hovertemplate=f"<b>Sample %{{customdata[0]}}</b><br>{title}: C{l}<br>"
                                        f"{other_name}: C%{{customdata[1]}}<br>PC1 %{{x:.2f}}, PC2 %{{y:.2f}}, "
                                        f"PC3 %{{z:.2f}}<extra></extra>")
    ax = dict(backgroundcolor="#f4f3ef", gridcolor="#d9d7d1", showbackground=True)
    fig.update_layout(scene=dict(xaxis=dict(title=f"PC1 ({100 * ev[0]:.0f}%)", **ax),
                                 yaxis=dict(title=f"PC2 ({100 * ev[1]:.0f}%)", **ax),
                                 zaxis=dict(title=f"PC3 ({100 * ev[2]:.0f}%)", **ax), aspectmode="cube"),
                      template="plotly_white", font=FONT, height=620, margin=dict(l=0, r=0, t=40, b=0),
                      title=dict(text=title, font=dict(size=13)), legend=dict(itemsizing="constant"))
    return fig


def clusters_3d_projected(P, ev, labels, ids, azim, elev, title):
    """3-D view as a rotated 2-D projection (no 3-D graphics needed)."""
    a, e = np.radians(azim), np.radians(elev)
    R1 = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    R2 = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    Q = (P[:, :3] - P[:, :3].mean(0)) @ R1.T @ R2.T
    fig = go.Figure()
    order = np.argsort(Q[:, 1])                      # far points first
    for l in np.unique(labels):
        s = order[labels[order] == l]
        fig.add_scatter(x=Q[s, 0], y=Q[s, 2], mode="markers", name=f"C{l}", customdata=np.asarray(ids)[s],
                        marker=dict(size=5, color=CAT[(int(l) - 1) % 8], opacity=0.75),
                        hovertemplate="<b>Sample %{customdata}</b><extra>C" + str(l) + "</extra>")
    for j, nm in enumerate(["PC1", "PC2", "PC3"]):              # axis arrows
        v = np.zeros(3); v[j] = np.abs(P[:, j]).max() * 0.8
        w = v @ R1.T @ R2.T
        fig.add_scatter(x=[0, w[0]], y=[0, w[2]], mode="lines+text", text=["", nm], textposition="top center",
                        line=dict(color=INK2, width=1.5), showlegend=False, hoverinfo="skip")
    fig.update_xaxes(showticklabels=False, title=None); fig.update_yaxes(showticklabels=False, title=None, scaleanchor="x")
    return _layout(fig, 520, title=dict(text=title, font=dict(size=13)), legend=dict(itemsizing="constant"))
