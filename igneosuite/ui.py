"""Streamlit interface. `render(user=None)` draws the whole app so a future portal can embed it."""
from __future__ import annotations
import html
import numpy as np
import pandas as pd
import streamlit as st

from . import __version__
from .io import read_table, clean_table, guess_columns, guess_meta, read_meta, REE, short_name
from . import submit as submit_mod
from . import diagnose, validate, errors, export, cluster, plots, telemetry, jobs, store, geometry, iplots, agegroups
from .facts import FACTS
import time
from .imputers import METHODS, available_methods, impute, DEEP, HAS_TORCH

APP_META = dict(id="igneosuite", name="IgneoSuite", tagline="Gap-filling for incomplete igneous geochemistry",
                version=__version__)
STEPS = ["1 · Load data", "2 · Missing values", "3 · Test methods", "4 · Fill and export", "5 · Data geometry",
         "6 · Clusters", "7 · Save & share", "About"]
S = st.session_state


def _user():
    return S.get("_user")


def _session_token():
    """Token of the signed-in Octa account, or None (local copies run without accounts)."""
    if not S.get("_user"):
        return None
    try:
        from octa_auth import token
        return token()
    except Exception:
        return None


def _img(fig, caption=None, half=False):
    if half:
        col, _ = st.columns(2)
        with col:
            st.image(plots.to_png(fig), caption=caption, width='stretch')
    else:
        st.image(plots.to_png(fig), caption=caption, width='stretch')


def _need(key, msg):
    if key not in S:
        st.info(msg)
        st.stop()


def _fmt(df, digits=3):
    return df.style.format(precision=digits, na_rep="—")


# ---------------------------------------------------------------- 1 load
LOC_ANSWERS = {"confirmed": "Yes, the locations are correct",
               "some_wrong": "No, some locations are wrong",
               "not_sure": "I am not sure"}


def _save_loc_answer(key):
    S.location_check = S[key]
    telemetry.event("locations", {"answer": S[key]}, _user())


@st.cache_data
def _world_lines():
    """Country outlines as one x/y line (None between rings), from the bundled Natural Earth file."""
    import json
    from pathlib import Path
    g = json.loads((Path(__file__).parent / "data" / "world_countries.geojson").read_text())
    xs, ys = [], []
    for f in g["features"]:
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            for ring in poly:
                xs += [p[0] for p in ring] + [None]
                ys += [p[1] for p in ring] + [None]
    return xs, ys


def location_map(key: str, groups=None, group_colours=None, group_order=None, ask=True):
    """Interactive map of the samples, drawn without WebGL or online tiles so it shows in every browser.

    With `groups` (one label per sample) the points are coloured by group instead of by having an age."""
    import plotly.graph_objects as go
    from .location import map_view
    m = S.meta
    ids = [str(x) for x in S.ids]
    d = pd.DataFrame({"sample": ids, "lat": m.latitude.values, "lon": m.longitude.values,
                      "age": [("%.0f Ma" % a) if np.isfinite(a) else "no age" for a in m.age_ma.values]})
    has_age = m.age_ma.notna().values
    xs, ys = _world_lines()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", fill="toself", fillcolor="#f2efe8",
                             line=dict(color="#8a8882", width=0.7), hoverinfo="skip", showlegend=False))
    if groups is not None:
        g = np.asarray(groups, dtype=object)
        order = group_order or list(dict.fromkeys(g))
        under = [n for n in order if n in (agegroups.NO_AGE, agegroups.OUTSIDE)]
        main = sorted([n for n in order if n not in under], key=lambda n: -int((g == n).sum()))
        layers = [(g == name, name, (group_colours or {}).get(name, "#9a9893"))
                  for name in under + main]     # grey points first, then the largest groups, small ones on top
        rank = {n: i for i, n in enumerate(order)}
        d["age"] = [f"{a} · {b}" for a, b in zip(d["age"], g)]
    else:
        layers = ((~has_age, "Without age", plots.CAT[1]), (has_age, "With age", plots.CAT[0]))
    for sel, name, colour in layers:
        if sel.any():
            fig.add_trace(go.Scatter(
                legendrank=1000 + rank.get(name, 0) if groups is not None else 1000,
                x=d.lon[sel], y=d.lat[sel], mode="markers", name=f"{name} ({int(sel.sum())})",
                marker=dict(size=6, color=colour, opacity=(0.85 if groups is None else
                                                      0.5 if name in (agegroups.NO_AGE, agegroups.OUTSIDE) else 0.9),
                            line=dict(width=0.4, color="#0b0b0b")),
                customdata=d[["sample", "age"]][sel].values,
                hovertemplate="<b>%{customdata[0]}</b><br>%{y:.4f}, %{x:.4f}<br>%{customdata[1]}<extra></extra>"))
    v = map_view(d.lat.values, d.lon.values)
    lat0 = v["latitude"]
    half_lon = 360 / 2 ** (v["zoom"] + 1.2)
    half_lat = half_lon * 0.55
    xr = [max(-180, v["longitude"] - half_lon), min(180, v["longitude"] + half_lon)]
    yr = [max(-90, lat0 - half_lat), min(90, lat0 + half_lat)]
    axis = dict(showgrid=True, gridcolor="#c9d9ea", zeroline=False, ticksuffix="°", color="#52514e",
                tickfont=dict(size=11), mirror=True, showline=True, linecolor="#8a8882")
    fig.update_layout(
        height=480, margin=dict(l=45, r=10, t=10, b=35), plot_bgcolor="#d7e6f5", paper_bgcolor="#ffffff",
        dragmode="pan", hovermode="closest", uirevision=key,
        xaxis=dict(range=xr, title=None, **axis),
        yaxis=dict(range=yr, title=None, scaleanchor="x", scaleratio=float(1 / np.cos(np.radians(lat0))), **axis),
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.9)", bordercolor="#8a8882", borderwidth=0.5,
                    font=dict(size=12)))
    st.plotly_chart(fig, width='stretch', key=key + "_map", theme=None,
                    config={"scrollZoom": True, "displaylogo": False, "displayModeBar": True,
                            "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"]})
    st.caption(f"{len(d)} samples. Scroll or pinch to zoom, drag to move, double-click or the house button to reset. "
               "Hover over a point to see the sample, its coordinates and its age."
               + (" Click a group in the legend to hide or show it; double-click to show only that group."
                  if groups is not None else ""))
    if not ask:
        return
    opts = list(LOC_ANSWERS)
    cur = S.get("location_check")
    st.radio("Are the sample locations correct?", opts, format_func=LOC_ANSWERS.get, key=key,
             index=opts.index(cur) if cur in opts else None, horizontal=True,
             on_change=_save_loc_answer, args=(key,))
    if S.get("location_check") in ("some_wrong", "not_sure"):
        S.location_comment = st.text_area("Which samples look wrong, and why? (optional)",
                                          value=S.get("location_comment", ""), max_chars=2000, key=key + "_c")
        if S.location_check == "some_wrong":
            st.warning("Please correct the coordinates in your file and upload it again. Common causes: latitude and "
                       "longitude swapped, a missing minus sign (S or W), or minutes entered as decimals.")


def page_load(with_open=True, header=True):
    from .location import check_locations, read_age
    from .template import build as build_template
    if header:
        st.header("Load data")
    st.write("Upload a table with one sample per row. Every sample needs a sample ID, latitude and longitude; "
             "age is optional but recommended. None of these are used in calculations.")
    if with_open:
        open_project_box()
    st.download_button("Download the Excel template", build_template(), "IgneoSuite_template.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       on_click=telemetry.event, args=("template", {}, _user()),
                       help="Fill in the sheet 'Data' and upload it here. The sheet 'Instructions' explains the formats.")
    up = st.file_uploader("CSV or Excel file", type=["csv", "txt", "xlsx", "xlsm", "xls"])
    if up is None and "raw" not in S and "X" in S:          # project reopened from the database
        st.info(f"Showing the saved project **{S.get('project_meta', {}).get('title', '')}**. "
                "Upload a file to start a new project instead.")
        show_loaded()
        save_bar("load")
        return
    if up is None and "raw" not in S:
        st.caption("Blank cells and placeholders such as n.d., b.d.l., '-' or '<0.5' are read as missing. "
                   "Coordinates may be decimal degrees (25.4567) or degrees-minutes-seconds (25°27'24\"N).")
        return
    if up is not None:
        sheet = 0
        if up.name.lower().endswith((".xlsx", ".xlsm", ".xls")):
            xl = pd.ExcelFile(up)
            names = xl.sheet_names
            sheet = st.selectbox("Sheet", names, index=names.index("Data") if "Data" in names else 0)
            up.seek(0)
        sig = (up.name, up.size, str(sheet))
        if S.get("sig") != sig:
            for k in list(S.keys()):
                if k not in ("step", "_user", "_sid", "_octa_auth", "module", "ex_src"):
                    del S[k]
            st.query_params.clear()
            S.raw = read_table(up, sheet)
            S.sig = sig
    raw = S.raw
    fk = str(abs(hash(S.get("sig"))) % 10**8)          # new widgets for every new file
    id_guess, val_guess = guess_columns(raw)
    cols = list(raw.columns)
    id_col = st.selectbox("Sample-ID column", cols, index=cols.index(S.get("id_col", id_guess)), key="id_" + fk)
    mg = S.get("meta_cols", guess_meta(raw))
    pick = "(choose a column)"
    mc = st.columns(3)
    meta_cols = {}
    for box, key, label, none in zip(mc, ["latitude", "longitude", "age_ma"],
                                     ["Latitude *", "Longitude *", "Age (Ma), optional"], [pick, pick, "(none)"]):
        opts = [none] + [c for c in cols if c != id_col]
        cur = mg.get(key) if mg.get(key) in opts else none
        v = box.selectbox(label, opts, index=opts.index(cur), key=f"meta_{key}_{fk}")
        meta_cols[key] = None if v == none else v
    mc2 = st.columns(3)
    for box, key, label in zip(mc2, ["reference", "comment"], ["Reference of each sample, optional",
                                                             "Comment on each sample, optional"]):
        opts = ["(none)"] + [c for c in cols if c != id_col and c not in meta_cols.values()]
        cur = mg.get(key) if mg.get(key) in opts else "(none)"
        v = box.selectbox(label, opts, index=opts.index(cur), key=f"meta_{key}_{fk}")
        meta_cols[key] = None if v == "(none)" else v
    taken = {id_col, *[v for v in meta_cols.values() if v]}
    choices = [c for c in cols if c not in taken]
    default = [c for c in S.get("value_cols", val_guess) if c in choices]
    value_cols = st.multiselect("Variables (concentrations)", choices, default=default, key="vars_" + fk)
    drop_bad = False
    if "loc_problems" in S and len(S.loc_problems):
        drop_bad = st.checkbox(f"Remove the {len(S.loc_problems)} samples with location problems and continue",
                               key="drop_" + fk)
    if st.button("Read values", type="primary", disabled=not value_cols):
        for k in ("X", "val_scat", "val_block", "est", "E", "clu", "geo", "location_check", "location_comment",
                  "submitted_id", "saved", "changed"):
            S.pop(k, None)
        if not meta_cols["latitude"] or not meta_cols["longitude"]:
            S.pop("loc_problems", None)
            st.error("Latitude and longitude are required. Choose the columns that hold them. If your table has no "
                     "coordinates, add them (the Excel template shows the format) and upload the file again.")
            st.stop()
        if meta_cols["latitude"] == meta_cols["longitude"]:
            st.error("Latitude and longitude must be two different columns.")
            st.stop()
        ids_all = raw[id_col].astype(str).values
        loc = check_locations(ids_all, raw[meta_cols["latitude"]], raw[meta_cols["longitude"]])
        S.loc_problems = loc["problems"]
        if loc["swapped"]:
            st.error("Many latitudes are beyond ±90° while all longitudes are within ±90°. Latitude and longitude "
                     "look swapped: choose the columns the other way round.")
            st.stop()
        if len(loc["problems"]) and not drop_bad:
            st.rerun()
        keep = loc["valid"]
        if not keep.any():
            st.error("No sample has a valid location.")
            st.stop()
        sub = raw.loc[keep].reset_index(drop=True)
        X, ids, rep = clean_table(sub, id_col, value_cols)
        if meta_cols["age_ma"]:
            age, age_bad = read_age(sub[meta_cols["age_ma"]])
        else:
            age, age_bad = np.full(len(sub), np.nan), 0
        def _text(col, n):
            if not col:
                return [None] * len(sub)
            return [None if (v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() == "")
                    else str(v).strip()[:n] for v in sub[col]]
        S.meta = pd.DataFrame({"latitude": loc["latitude"][keep], "longitude": loc["longitude"][keep], "age_ma": age,
                               "latitude_original": sub[meta_cols["latitude"]].astype(str).str.slice(0, 60).values,
                               "longitude_original": sub[meta_cols["longitude"]].astype(str).str.slice(0, 60).values,
                               "reference": _text(meta_cols.get("reference"), 1000),
                               "comment": _text(meta_cols.get("comment"), 2000)})
        rep.update(n_removed=int((~keep).sum()), n_converted=loc["n_converted"], age_rejected=age_bad,
                   precision_note=loc["precision_note"])
        S.update(X=X, ids=ids, report=rep, id_col=id_col, value_cols=value_cols, meta_cols=meta_cols)
        _changed("load")
        sm = diagnose.summary(X)
        telemetry.event("load", dict(n_samples=sm["n_samples"], n_variables=sm["n_variables"],
                                     pct_missing=round(sm["pct_missing"], 2), n_complete=sm["n_complete"],
                                     recovered=rep["counts"]["recovered"], n_location_removed=rep["n_removed"],
                                     n_with_age=int(np.isfinite(age).sum())), _user())
    if "X" not in S and "loc_problems" in S and len(S.loc_problems):
        P = S.loc_problems
        st.error(f"{len(P)} samples have no valid location. Every sample needs a latitude and a longitude. "
                 "Correct them in your file and upload it again, or tick the box above to remove these samples.")
        st.dataframe(P, hide_index=True, width='stretch')
        st.download_button("Download the list of problems (CSV)", P.to_csv(index=False).encode(),
                           "IgneoSuite_location_problems.csv", "text/csv")
        return
    if "X" in S:
        show_loaded()
        save_bar("load")


def show_loaded():
    if True:
        rep = S.report
        c = st.columns(4)
        c[0].metric("Samples", rep["n_rows"]); c[1].metric("Variables", rep["n_cols"])
        c[2].metric("Values read", rep["counts"]["number"] + rep["counts"]["recovered"])
        c[3].metric("Missing", rep["counts"]["missing"] + rep["counts"]["text"])
        if rep.get("n_removed"):
            st.warning(f"{rep['n_removed']} samples without a valid location were removed.")
        if rep.get("n_converted"):
            st.info(f"{rep['n_converted']} coordinates were converted to decimal degrees "
                    "(from degrees-minutes-seconds or N/S/E/W notation).")
        if rep.get("precision_note"):
            st.warning(rep["precision_note"])
        n_age = int(S.meta.age_ma.notna().sum())
        if not S.meta_cols.get("age_ma"):
            st.info("No age column chosen. Age is optional, but data with ages are much more useful.")
        elif n_age < len(S.meta):
            st.info(f"{n_age} of {len(S.meta)} samples have an age."
                    + (f" {rep['age_rejected']} values could not be read or were outside 0–4,600 Ma." if rep.get("age_rejected") else ""))
        if rep["counts"]["recovered"]:
            st.success(f"{rep['counts']['recovered']} numbers contained hidden spaces or a decimal comma and were recovered.")
        if rep["text_examples"]:
            st.warning("Some cells could not be read as numbers and were set to missing: " +
                       "; ".join(f"{k}: {', '.join(v[:4])}" for k, v in rep["text_examples"].items()))
        if rep["nonpositive"]:
            st.warning("Zero or negative values found in " + ", ".join(rep["nonpositive"]) +
                       ". These variables are treated on a linear scale instead of a log scale.")
        st.subheader("Sample locations")
        location_map("loc_answer_load")
        st.subheader("Data")
        n_ref = int(S.meta.get("reference", pd.Series(dtype=object)).notna().sum())
        if n_ref:
            st.caption(f"{n_ref} samples have a reference; "
                       f"{int(S.meta.get('comment', pd.Series(dtype=object)).notna().sum())} have a comment.")
        extra = [c for c in ("reference", "comment") if c in S.meta and S.meta[c].notna().any()]
        st.dataframe(pd.concat([pd.Series(S.ids, name=S.id_col),
                                S.meta[["latitude", "longitude", "age_ma"] + extra].rename(
                                    columns={"latitude": "Latitude", "longitude": "Longitude", "age_ma": "Age (Ma)",
                                             "reference": "Reference", "comment": "Comment"}),
                                S.X], axis=1).head(200), width='stretch')



# ---------------------------------------------------------------- 2 diagnose
def page_diagnose():
    _need("X", "Load data first (step 1).")
    X = S.X
    st.header("Missing values")
    sm = diagnose.summary(X)
    c = st.columns(4)
    c[0].metric("Missing cells", f"{sm['n_missing']:,} ({sm['pct_missing']:.1f}%)")
    c[1].metric("Complete samples", f"{sm['n_complete']:,} ({100*sm['n_complete']/max(sm['n_samples'],1):.1f}%)")
    c[2].metric("Samples with no values", sm["n_empty_rows"])
    c[3].metric("Empty variables", len(sm["empty_cols"]))
    if sm["empty_cols"]:
        st.warning("No measured values in: " + ", ".join(sm["empty_cols"]) + ". These cannot be estimated.")
    pv = diagnose.per_variable(X)
    t1, t2, t3, t4 = st.tabs(["By variable", "Pattern", "Co-missingness", "Blocks"])
    with t1:
        iplots.show(iplots.missing_bar(pv), "Missing values by variable", "fig_missing_bar",
                    data=pv.set_index("Variable"), png=("missing_bar", (pv,), {}))
        st.dataframe(_fmt(pv.set_index("Variable"), 2), width='stretch')
    with t2:
        iplots.show(iplots.missing_matrix(X, S.ids), "Missingness pattern", "fig_missing_matrix",
                    data=pd.concat([pd.Series(S.ids, name=S.id_col), X.notna().astype(int)], axis=1).set_index(S.id_col),
                    png=("missing_matrix", (X,), {}), caption="Blue: measured; white: missing. Hover to see the sample.")
        cc = diagnose.completeness_curve(X)
        st.caption("Complete samples as variables are added from most to least complete")
        st.dataframe(_fmt(cc.set_index("n_variables"), 1), width='stretch', height=250)
    with t3:
        phi = diagnose.co_missing_phi(X)
        if phi.empty:
            st.write("Too few variables with missing values.")
        else:
            iplots.show(iplots.phi_heatmap(phi), "Co-missingness phi", "fig_phi", data=phi,
                        png=("phi_heatmap", (phi,), {}),
                        caption="High φ: the two variables tend to be missing in the same samples.")
    with t4:
        g = diagnose.groups(X)
        ree = g.get("REE", [])
        st.write(f"Detected groups: " + "; ".join(f"**{k}** ({len(v)})" for k, v in g.items()))
        if ree:
            bp = diagnose.block_pattern(X, ree)
            st.write("REE reported together:")
            st.dataframe(pd.Series(bp, name="Samples").to_frame(), width='content')
            if bp["Partly measured"] < 0.3 * max(bp["All measured"] + bp["None measured"], 1):
                st.info("The REE are mostly all present or all absent. Use the block test in step 3, "
                        "because it mirrors the way these values are actually missing.")
    save_bar("missing")


# ---------------------------------------------------------------- 3 validate
TEST_NAMES = {"scat": "scattered-gap test", "block": "block test"}


def _job_key(kind):
    return f"{telemetry.session_id()}:{kind}"


def collect_jobs():
    """Move finished background tests into the session (runs on every page)."""
    for kind, store in (("scat", "val_scat"), ("block", "val_block")):
        job = jobs.get(_job_key(kind))
        if not job or job["status"] == "running":
            continue
        jobs.pop(_job_key(kind))
        if job["status"] == "done" and (job["result"] is None or job["result"].empty):
            S[f"{kind}_error"] = "no measured values could be hidden with these settings."
        elif job["status"] == "done":
            S[store] = validate.compact(job["result"])
            S[f"{kind}_params"] = job["info"]
            _changed("test_scattered" if kind == "scat" else "test_block")
            S[f"{kind}_seconds"] = job["finished"] - job["started"]
            S[f"{kind}_just_done"] = True
            for k in ("est", "E"):
                S.pop(k, None)
            _log_run(kind, job)
        elif job["status"] == "error":
            S[f"{kind}_error"] = job["error"]
        else:
            S[f"{kind}_error"] = "The test was stopped."


def _log_run(kind, job):
    try:
        long = job["result"]; info = job["info"]
        sm = diagnose.summary(S.X)
        sc = {("scattered" if kind == "scat" else "block"): validate.score(long).round(4).to_dict(orient="index")} if not long.empty else {}
        telemetry.run(dict(n_samples=sm["n_samples"], n_variables=sm["n_variables"],
                           pct_missing=round(sm["pct_missing"], 2), n_complete=sm["n_complete"],
                           methods=info["methods"], repetitions=int(info["reps"]),
                           scattered_frac=info["frac"] if kind == "scat" else None,
                           block_frac=info["frac"] if kind == "block" else None,
                           block_variables=[short_name(b) for b in info.get("block", [])],
                           recommended_method=validate.recommend(validate.score(long))[0] if not long.empty else None,
                           scores=sc, duration_s=round(job["finished"] - job["started"], 1)), _user())
    except Exception:
        pass


def running(kind=None):
    kinds = [kind] if kind else ["scat", "block"]
    return any((j := jobs.get(_job_key(k))) and j["status"] == "running" for k in kinds)


def _fmt_time(sec):
    sec = int(sec)
    return f"{sec // 60} min {sec % 60:02d} s" if sec >= 60 else f"{sec} s"


@st.fragment(run_every=2)
def progress_panel(kind):
    """Live status of a running test, with rotating facts. Reruns the page when the test ends."""
    job = jobs.get(_job_key(kind))
    if not job:
        return
    if job["status"] != "running":
        st.rerun(scope="app")
        return
    el = time.time() - job["started"]
    st.progress(job["progress"], f"{TEST_NAMES[kind].capitalize()}: {job['text']}")
    st.markdown(f"**Working…** {_fmt_time(el)} so far. Expected: {job['eta']}.")
    st.warning("Please do not refresh, close or reload this page: the calculation would start again from "
               "scratch. You may look at other steps meanwhile; the test keeps running.")
    fact = FACTS[(int(el // 8) + job.get("fact0", 0)) % len(FACTS)]
    st.info(f"💡 {fact}")
    if st.button("Stop this test", key=f"stop_{kind}",
                 help="Stops after the method that is running now has finished."):
        jobs.cancel(_job_key(kind))
        st.toast("Stopping after the current method finishes…")


def _start(kind, M, cols, methods, scenario, frac, bidx, reps, seed, info, eta):
    S.pop(f"{kind}_error", None)
    try:
        job = jobs.start(_job_key(kind), validate.run, M.copy(), cols, list(methods), scenario, frac,
                         block_cols=bidx, reps=int(reps), seed0=int(seed))
    except jobs.Busy as e:
        S[f"{kind}_error"] = str(e)
        return
    job["info"] = info
    job["eta"] = eta
    job["fact0"] = int(np.random.default_rng().integers(len(FACTS)))


def page_validate():
    _need("X", "Load data first (step 1).")
    X = S.X; M = X.values.astype(float); cols = list(X.columns)
    st.header("Test the methods on your data")
    st.write("Measured values are hidden, estimated, and compared with the true values. "
             "Error is |log10(estimate / true)|, summarised as the median over variables of each variable's "
             "median error: 0.1 means a typical estimate is within a factor of 1.26.")
    busy = running()
    avail = available_methods()
    default = [m for m in ["Median", "KNN", "MICE"] if m in avail]
    methods = st.multiselect("Methods", avail, default=S.get("methods", default), disabled=busy,
                             help="\n".join(f"{m}: {METHODS[m][1]}" for m in avail))
    if not HAS_TORCH:
        st.caption("DAE and GAIN need PyTorch (`pip install torch`).")
    c = st.columns(3)
    reps = c[0].number_input("Repetitions", 1, 10, S.get("reps", 3), disabled=busy)
    seed = c[2].number_input("Random seed", 0, 10_000, S.get("seed", 0), disabled=busy)

    # ---- test 1: scattered gaps
    st.subheader("Test 1 · Scattered gaps")
    frac = st.slider("Share of measured values hidden (%)", 1, 20, S.get("frac_pct", 5), disabled=busy) / 100
    lo, hi = validate.estimate_seconds(methods, len(X), len(cols), reps)
    eta = validate.describe_seconds(lo, hi)
    b1, m1 = st.columns([1, 3], vertical_alignment="top")
    go1 = b1.button("Run test 1", type="primary", disabled=not methods or busy, key="run_scat")
    with m1:
        if running("scat"):
            progress_panel("scat")
        elif S.get("scat_error"):
            st.error(f"Test 1 did not finish: {S.scat_error}")
        elif S.pop("scat_just_done", False):
            st.success(f"✅ Test 1 is complete ({_fmt_time(S.get('scat_seconds', 0))}). "
                       "Next: run test 2 (block gaps) below, or go straight to step 4.")
        elif "val_scat" in S:
            st.success("✅ Test 1 is complete.")
        elif methods:
            st.info(f"⏱️ This may take {eta} with the methods you chose and {len(X):,} samples × {len(cols)} "
                    "variables. Slower methods (missForest, DAE, GAIN) and larger tables take longer. "
                    "While it runs, please do not refresh or close the page.")
    if go1:
        S.methods, S.reps, S.seed, S.frac_pct = methods, reps, seed, int(round(frac * 100))
        for k in ("val_scat", "val_block", "scat_error", "block_error"):
            S.pop(k, None)
        _start("scat", M, cols, methods, "scattered", frac, None, reps, seed,
               dict(methods=methods, reps=int(reps), frac=frac, seed=int(seed)), eta)
        telemetry.event("test", {"kind": "scattered", "methods": methods, "reps": int(reps)}, _user())
        st.rerun()

    # ---- test 2: block gaps
    st.subheader("Test 2 · Block gaps")
    ree_default = [x for x in cols if short_name(x) in REE]
    block = st.multiselect("Variables hidden together", cols, default=S.get("block_names", ree_default),
                           disabled=busy, help="Default is the REE. The block is hidden in samples that have all of it.")
    bfrac = st.slider("Share of eligible samples (%)", 2, 30, S.get("bfrac_pct", 10), disabled=busy) / 100
    n_elig = int((~np.isnan(M[:, [cols.index(b) for b in block]])).all(1).sum()) if block else 0
    ready1 = "val_scat" in S
    b2, m2 = st.columns([1, 3], vertical_alignment="top")
    go2 = b2.button("Run test 2", type="primary", key="run_block",
                    disabled=busy or not ready1 or not block or n_elig == 0)
    with m2:
        if running("block"):
            progress_panel("block")
        elif S.get("block_error"):
            st.error(f"Test 2 did not finish: {S.block_error}")
        elif S.pop("block_just_done", False) or S.get("val_block"):
            st.success("✅ Both tests are complete. You are ready to go to **step 4 · Fill and export**.")
        elif not ready1:
            st.info("Run test 1 first. Test 2 uses the same methods and repetitions.")
        elif not block:
            st.info("Choose the variables that are usually reported together (for example the REE).")
        elif n_elig == 0:
            st.warning("No sample has all of these variables measured, so this block cannot be tested.")
        else:
            lo2, hi2 = validate.estimate_seconds(S.get("methods", methods), int(n_elig * bfrac) + len(X), len(cols),
                                                 S.get("reps", reps))
            st.info(f"⏱️ Test 1 is done. Test 2 hides the {len(block)} chosen variables together in "
                    f"{int(n_elig * bfrac)} of the {n_elig} samples that have all of them. It may take "
                    f"{validate.describe_seconds(lo2, hi2)}. Please do not refresh or close the page while it runs.")
    if go2:
        S.block_names, S.bfrac_pct = block, int(round(bfrac * 100))
        S.pop("val_block", None); S.pop("block_error", None)
        lo2, hi2 = validate.estimate_seconds(S.methods, len(X), len(cols), S.reps)
        _start("block", M, cols, S.methods, "block", bfrac, [cols.index(b) for b in block], S.reps, S.get("seed", 0),
               dict(methods=S.methods, reps=int(S.reps), frac=bfrac, block=block, seed=int(S.get("seed", 0))),
               validate.describe_seconds(lo2, hi2))
        telemetry.event("test", {"kind": "block", "methods": S.methods, "reps": int(S.reps)}, _user())
        st.rerun()

    # ---- results
    have = [(k, n) for k, n in (("val_scat", "Test 1 · Scattered gaps"), ("val_block", "Test 2 · Block gaps"))
            if S.get(k)]
    if not have:
        return
    st.subheader("Results")
    if len(have) == 2:
        cmp = pd.DataFrame({"Test 1 · scattered: median |log10 error|": S.val_scat["score"]["Median |log10 error|"],
                            "Test 1 · within ×2 (%)": S.val_scat["score"]["Within ×2 (%)"],
                            "Test 2 · block: median |log10 error|": S.val_block["score"]["Median |log10 error|"],
                            "Test 2 · within ×2 (%)": S.val_block["score"]["Within ×2 (%)"]})
        st.caption("Both tests side by side")
        st.dataframe(_fmt(cmp, 3), width='stretch')
    for key, name in have:
        res = S[key]
        st.markdown(f"#### {name}")
        if key == "val_block":
            bp = S.get("block_params", {})
            st.caption(f"{len(bp.get('block', []))} variables hidden together: "
                       f"{', '.join(short_name(b) for b in bp.get('block', []))}.")
        tb = res["score"]
        st.dataframe(_fmt(tb, 3), width='stretch')
        tname = "Test 1 scattered" if key == "val_scat" else "Test 2 block"
        iplots.show(iplots.method_bars(tb), f"{tname} method errors", f"fig_{key}_bars", data=tb,
                    png=("method_bars", (tb,), {}))
        iplots.show(iplots.per_variable_errors(res["pervar"], list(tb.index)), f"{tname} errors by variable",
                    f"fig_{key}_pervar", data=res["pervar"], png=("per_variable_errors", (res["pervar"], list(tb.index)), {}))
        m = st.selectbox("Measured vs estimated for", list(tb.index), key=key + "_m")
        half, _ = st.columns(2)
        with half:
            smp = res["sample"]
            iplots.show(iplots.true_vs_est(smp, m), f"{tname} measured vs estimated {m}", f"fig_{key}_tve",
                        data=smp[smp.method == m].reset_index(drop=True), png=("true_vs_est", (smp, m), {}))
    rec_s, why_s = validate.recommend(S.val_scat["score"])
    msg = f"**Recommended method: {rec_s}.** {why_s}"
    if S.get("val_block"):
        rec_b, _ = validate.recommend(S.val_block["score"])
        if rec_b != rec_s:
            msg += f" For the block test, {rec_b} did best; weigh the two by how your data are missing (step 2)."
    S.recommended = rec_s
    st.success(msg)
    save_bar("test")


# ---------------------------------------------------------------- 4 impute + export
def page_fill():
    _need("X", "Load data first (step 1).")
    X = S.X; M = X.values.astype(float); cols = list(X.columns)
    st.header("Fill the gaps and export")
    if running():
        st.info("A test from step 3 is still running. Its progress is shown in step 3; this page will be ready "
                "when it finishes. Please do not refresh or close the page.")
        st.stop()
    if "val_scat" not in S:
        st.warning("Run the tests in step 3 first. They provide the error for every estimate.")
        st.stop()
    tested = list(S.val_scat["score"].index)
    rec = S.get("recommended", tested[0])
    method = st.selectbox("Method", tested, index=tested.index(rec) if rec in tested else 0)
    q = st.select_slider("Error band", options=[0.68, 0.90, 0.95], value=0.68,
                         format_func=lambda v: f"{int(v*100)}% of test errors")
    if st.button("Estimate missing values", type="primary"):
        with st.spinner(f"Running {method}"):
            est = impute(M, method, seed=0)
        bidx = [cols.index(b) for b in S.get("block_names", [])]
        F = errors.error_factors(S.val_scat, S.get("val_block"), method, cols, q)
        E = errors.error_matrix(M, est, cols, F, bidx)
        S.update(est=est, E=E, F=F, fill_method=method, q=q)
        _changed("fill")
        telemetry.event("fill", dict(method=method, q=q, n_estimated=int((np.isnan(M) & np.isfinite(est)).sum())), _user())
    if "est" not in S:
        return
    est, E, F = S.est, S.E, S.F
    n_est = int((np.isnan(M) & np.isfinite(est)).sum())
    st.success(f"{n_est:,} values estimated with {S.fill_method}. Measured values are unchanged.")
    fac = F.copy()
    fac["Factor (scattered)"] = 10 ** fac.q_scattered
    fac["Factor (block)"] = 10 ** fac.q_block
    st.caption(f"Typical error factor per variable ({int(S.q*100)}% of test errors fall within this factor)")
    st.dataframe(_fmt(fac[["Factor (scattered)", "Factor (block)", "n_scattered", "n_block"]], 2), width='stretch')
    three = export.three_column(S.ids, S.id_col, cols, M, est, E)
    comp = export.complete_matrix(S.ids, S.id_col, cols, est)
    gaps = np.isnan(M).any(1)
    st.caption("Preview: first 100 samples with at least one estimated value")
    st.dataframe(three[gaps].head(100), width='stretch')
    note = ("For block variables in samples where the whole block was missing, the block-test error is used; "
            "otherwise the scattered-test error." if S.get("block_names") else "Errors come from the scattered test.")
    notes = export.default_notes(S.fill_method, note, n_est, cols)
    summary_s = S.val_scat["score"]
    sheets = {"Measured_estimated_error": three, "Complete_matrix": comp,
              "Error_by_variable": fac, "Test_scattered": summary_s}
    if S.get("val_block"):
        sheets["Test_block"] = S.val_block["score"]
    c = st.columns(2)
    c[0].download_button("Download Excel workbook", export.to_excel(sheets, notes), "igneosuite_results.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary",
                         on_click=telemetry.event, args=("export", {"format": "xlsx"}, _user()))
    c[1].download_button("Download complete matrix (CSV)", comp.to_csv(index=False).encode(), "igneosuite_complete.csv", "text/csv",
                         on_click=telemetry.event, args=("export", {"format": "csv"}, _user()))
    save_bar("fill")


# ---------------------------------------------------------------- 5 clusters
def page_cluster():
    _need("X", "Load data first (step 1).")
    st.header("Clusters before and after gap-filling")
    if "est" not in S:
        st.info("Estimate the missing values in step 4 first.")
        st.stop()
    X = S.X; cols = list(X.columns); M = X.values.astype(float)
    st.write("K-means on log-standardised values. Compare a small set of well-measured variables "
             "(measured values only, complete samples) with the gap-filled data.")
    comp = X.notna().mean().sort_values(ascending=False)
    base_default = [c for c in comp.index if comp[c] >= 0.8]
    base = st.multiselect("Reference variables (measured only)", cols, default=base_default)
    extra = st.multiselect("Variables for the gap-filled run", cols, default=cols)
    k = st.slider("Number of clusters", 2, 10, 4)
    if st.button("Scan k (2–8) on the reference variables"):
        rows = ~np.isnan(M[:, [cols.index(b) for b in base]]).any(1)
        Z = cluster.prepare(M[rows][:, [cols.index(b) for b in base]])
        with st.spinner("Scanning"):
            S.kscan = cluster.scan_k(Z)
        _changed("clusters")
    if "kscan" in S:
        iplots.show(iplots.k_scan(S.kscan), "Cluster number scan", "fig_kscan", data=S.kscan,
                    png=("k_scan", (S.kscan,), {}))
    if st.button("Run comparison", type="primary", disabled=len(base) < 2 or len(extra) < 2):
        bi = [cols.index(b) for b in base]; ei = [cols.index(e) for e in extra]
        rows = ~np.isnan(M[:, bi]).any(1)
        Zr = cluster.prepare(M[rows][:, bi])
        lr = cluster.kmeans(Zr, k)
        Zf = cluster.prepare(S.est[rows][:, ei])
        lf = cluster.match_labels(lr, cluster.kmeans(Zf, k))
        P, ev = cluster.pca(Zr)
        S.clu = dict(rows=rows, lr=lr, lf=lf, base=base, extra=extra, k=k, P=P, ev=np.asarray(ev))
        _changed("clusters")
        telemetry.event("cluster", dict(k=k, n_reference_vars=len(base), n_filled_vars=len(extra),
                                        same_cluster_pct=round(float(100 * np.mean(lr == lf)), 2)), _user())
    if "clu" in S:
        c = S.clu
        from sklearn.metrics import adjusted_rand_score
        kept = 100 * np.mean(c["lr"] == c["lf"])
        m = st.columns(3)
        m[0].metric("Samples compared", int(c["rows"].sum()))
        m[1].metric("Same cluster", f"{kept:.1f}%")
        m[2].metric("ARI", f"{adjusted_rand_score(c['lr'], c['lf']):.2f}")
        ct = pd.crosstab(pd.Series(c["lr"], name=f"Reference ({len(c['base'])} vars)"),
                         pd.Series(c["lf"], name=f"Gap-filled ({len(c['extra'])} vars)"))
        st.dataframe(ct)
        P, ev = np.asarray(c["P"]), np.asarray(c["ev"])
        ids_c = np.asarray(S.ids)[c["rows"]]
        lr, lf = np.asarray(c["lr"]), np.asarray(c["lf"])
        coords = pd.DataFrame(P, columns=[f"PC{i + 1}" for i in range(P.shape[1])])
        coords.insert(0, S.id_col, ids_c); coords["Reference cluster"] = lr; coords["Gap-filled cluster"] = lf
        coords = coords.set_index(S.id_col)
        st.markdown("#### 2-D view (PC1–PC2)")
        cc = st.columns(2)
        with cc[0]:
            iplots.show(iplots.clusters_2d(P, ev, lr, ids_c, lf, "Gap-filled", "Reference clusters"),
                        "Reference clusters PC1 PC2", "fig_clu_ref", data=coords,
                        png=("pca_scatter", (P, ev, lr, "Reference clusters"), {}))
        with cc[1]:
            iplots.show(iplots.clusters_2d(P, ev, lf, ids_c, lr, "Reference", "Gap-filled clusters"),
                        "Gap-filled clusters PC1 PC2", "fig_clu_fill", data=coords,
                        png=("pca_scatter", (P, ev, lf, "Gap-filled clusters"), {}))
        st.caption("Both on the axes of the reference PCA. Hover over a sample to see its number and its cluster "
                   "in both runs.")
        if P.shape[1] >= 3:
            st.markdown("#### 3-D view (PC1–PC2–PC3)")
            which = st.radio("Colour by", ["Gap-filled clusters", "Reference clusters"], horizontal=True, key="clu3d_which")
            lab, oth, oname = (lf, lr, "Reference") if which == "Gap-filled clusters" else (lr, lf, "Gap-filled")
            from . import viewer3d
            viewer3d.show(P[:, :3], ev, lab, ids_c, [f"{which}: C{a} · {oname}: C{b}" for a, b in zip(lab, oth)],
                          which, plots.CAT, file_name=iplots._slug(f"{which} 3D"))
            c1, c2, _ = st.columns([1, 1, 2])
            try:
                c1.download_button("⬇ Figure (PNG, 300 dpi)",
                                   iplots._png("clusters_3d", (P, ev, lab, which), ()),
                                   iplots._slug(f"{which} 3D") + ".png", "image/png", key="fig_clu_3d_png")
            except Exception:
                pass
            c2.download_button("⬇ Data (CSV)", coords.to_csv().encode(), iplots._slug(f"{which} 3D") + ".csv",
                               "text/csv", key="fig_clu_3d_csv")
        else:
            st.info("The 3-D view needs at least three reference variables and a fresh run of the comparison.")
        st.markdown("#### Download")
        a, b = _sample_clusters()
        band = int(round(100 * float(S.get("q") or 0.68)))
        full = export.full_table(S.ids, S.id_col, S.meta, cols, M, S.est, S.get("E"), a, b, band)
        n_in = int(pd.notna(full["Cluster after filling"]).sum())
        notes = [
            "Produced with IgneoSuite (cluster comparison, step 6).",
            f"One row per sample ({len(full):,} samples; {n_in:,} were clustered).",
            f"Cluster before filling: k-means (k = {c['k']}) on the measured values of the reference variables "
            f"({', '.join(c['base'])}); only samples with all of them measured.",
            f"Cluster after filling: k-means (k = {c['k']}) on the gap-filled values of {len(c['extra'])} variables; "
            "cluster numbers are matched to the reference run.",
            "Empty cluster cells: the sample was not in the comparison (a reference variable was missing).",
            f"For each element: measured value; estimated value (only where the measurement was missing, "
            f"method: {S.get('fill_method')}); ± error; and the {band}% error range (low – high).",
            "± error = estimate × (f − 1/f)/2 and range = [estimate/f, estimate × f], where f = 10^q and q is the "
            f"{band}th percentile of |log10(estimate/true)| for that element in the masking test.",
            "Cite: Abu-Alam, T.S., et al. When simpler wins: recovering the structure of incomplete geochemical data. "
            "Computers & Geosciences (submitted).",
        ]
        sheets = {"Samples": full, "Cluster_comparison": ct}
        st.download_button("⬇ Download all data and clusters (Excel)", export.to_excel(sheets, notes),
                           "igneosuite_clusters_full.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary",
                           key="clu_full_xlsx", on_click=telemetry.event, args=("export", {"format": "clusters_xlsx"}, _user()))
        st.caption("The Excel file has one row per sample: ID, latitude, longitude, age, reference, comment, the "
                   "cluster before and after filling, and for every element the measured value, the estimate, its "
                   f"± error and its {band}% range. Saving this step stores all of it in your project.")
    if "clu" in S or "kscan" in S:
        save_bar("clusters")


# ---------------------------------------------------------------- 5 geometry
def page_geometry():
    _need("X", "Load data first (step 1).")
    X = S.X; cols = list(X.columns); M = X.values.astype(float)
    st.header("Data geometry")
    st.write("How the samples spread in composition space: how many directions carry the variation, whether "
             "the samples form groups, and which elements define the main trends (principal components). "
             "All measures use log10-transformed, standardised values.")
    sources = ["Gap-filled data (step 4)", "Measured values only (complete samples)"]
    have_est = "est" in S
    gp = S.get("geo_params", {})
    src = st.radio("Data", sources, horizontal=True,
                   index=sources.index(gp.get("source", sources[0 if have_est else 1])))
    if src == sources[0] and not have_est:
        st.info("Fill the gaps in step 4 first, or use the measured values only.")
        st.stop()
    comp = X.notna().mean()
    default = cols if src == sources[0] else [c for c in cols if comp[c] >= 0.8]
    use = st.multiselect("Variables", cols, default=[c for c in gp.get("variables", default) if c in cols])
    A = (S.est if src == sources[0] else M)[:, [cols.index(c) for c in use]] if use else np.empty((len(X), 0))
    rows = ~np.isnan(A).any(1) if use else np.zeros(len(X), bool)
    st.caption(f"{int(rows.sum()):,} samples have all chosen variables.")
    if st.button("Calculate", type="primary", disabled=len(use) < 3 or rows.sum() < 20):
        with st.spinner("Calculating the geometry of the data…"):
            Z = geometry.prepare(A[rows])
            refs = S.meta["reference"].values[rows] if "reference" in S.meta else None
            res = geometry.analyse(Z, refs=refs)
        res["rows"] = np.where(rows)[0]
        res["variables"] = use
        S.geo, S.geo_params = res, dict(source=src, variables=use)
        _changed("geometry")
        telemetry.event("geometry", {"source": src, "n_variables": len(use), "n_samples": int(rows.sum())}, _user())
    if "geo" not in S:
        return
    g = S.geo
    m = g["metrics"]
    labels = {"n_samples": "Samples", "n_variables": "Variables", "pcs_80": "Components for 80% of variance",
              "pcs_90": "Components for 90% of variance", "participation_ratio": "Participation ratio",
              "twonn_dimension": "Intrinsic dimension (TwoNN)", "hopkins": "Hopkins statistic",
              "nn_ratio_vs_gaussian": "Nearest-neighbour distance ÷ Gaussian",
              "same_reference_nn": "Nearest neighbour from the same reference",
              "same_reference_chance": "… expected by chance"}
    tab = pd.DataFrame([{"Measure": labels[k], "Value": (f"{100*v:.1f}%" if k.startswith("same_reference")
                                                         else f"{v:.2f}" if isinstance(v, float) else f"{v:,}"),
                         "What it means": geometry.EXPLAIN[k]} for k, v in m.items()])
    st.table(tab.set_index("Measure"))
    ev = np.asarray(g["explained"])
    c1, c2 = st.columns(2)
    with c1:
        iplots.show(iplots.scree(ev), "Variance explained", "fig_scree",
                    data=pd.DataFrame({"component": [f"PC{i + 1}" for i in range(len(ev))], "explained": ev,
                                       "cumulative": np.cumsum(ev)}).set_index("component"),
                    png=("scree", (ev,), {}), caption="Variance explained by each component")
    with c2:
        rows = np.asarray(g["rows"])
        colour_opts = ["None"] + (["Age (Ma)"] if S.meta.age_ma.iloc[rows].notna().any() else []) + \
                      (["Cluster (step 6)"] if "clu" in S else [])
        how = st.selectbox("Colour samples by", colour_opts, key="geo_colour")
        kw = {}
        if how == "Age (Ma)":
            kw = dict(colour=S.meta.age_ma.values[rows].astype(float), colour_label="Age (Ma)")
        elif how == "Cluster (step 6)":
            lab = np.zeros(len(X), int); lab[np.where(S.clu["rows"])[0]] = S.clu["lf"]
            kw = dict(labels=lab[rows]) if (lab[rows] > 0).all() else {}
        Psc = np.asarray(g["scores"])
        ids_r = np.asarray(S.ids)[rows]
        age_txt = [f"{a:.0f} Ma" if np.isfinite(a) else "—" for a in S.meta.age_ma.values[rows].astype(float)]
        extra = {"Age": age_txt}
        if "reference" in S.meta and S.meta.reference.notna().any():
            extra["Reference"] = [r if isinstance(r, str) else "—" for r in S.meta.reference.values[rows]]
        sc = pd.DataFrame(Psc, columns=[f"PC{i + 1}" for i in range(Psc.shape[1])])
        sc.insert(0, S.id_col, ids_r)
        iplots.show(iplots.pc_scores(Psc, ev, ids_r, extra=extra, **kw), "PC scores", "fig_pcscores",
                    data=sc.set_index(S.id_col), png=("pc_scores", (Psc, ev), kw),
                    caption="Samples on the first two principal components. Hover to see each sample.")
    Lg = np.asarray(g["loadings"])
    iplots.show(iplots.loadings(Lg, g["variables"], ev), "PC loadings", "fig_loadings",
                data=pd.DataFrame(Lg, index=pd.Index(g["variables"], name="variable"),
                                  columns=[f"PC{i + 1}" for i in range(Lg.shape[1])]),
                png=("loadings", (Lg, list(g["variables"]), ev), {}),
                caption="Loadings: how strongly each element defines PC1 and PC2. Elements with long bars of the "
                        "same sign rise and fall together.")
    save_bar("geometry")


# ---------------------------------------------------------------- 7 save
def page_save():
    _need("X", "Load data first (step 1).")
    st.header("Save & share")
    if not store.enabled():
        st.info("The database connection is not set up for this installation.")
        return
    if _role() == "view":
        _view_only_note()
        return
    st.write("Your work is saved as a private project: the data, and the settings and results of every step you "
             "have saved. Reopen it later to continue where you stopped, without repeating the calculations.")
    pm = S.get("project_meta", {})
    with st.form("project_form"):
        a, b = st.columns(2)
        title = a.text_input("Dataset name *", value=pm.get("title", ""))
        ref = b.text_input("DOI or reference of the compilation", value=pm.get("reference") or "")
        desc = st.text_area("Short description (area, rock types, analytical methods)", value=pm.get("description") or "",
                            max_chars=4000)
        a, b, c = st.columns(3)
        name = a.text_input("Author name", value=pm.get("author_name") or "")
        email = b.text_input("Email", value=pm.get("author_email") or "")
        aff = c.text_input("Affiliation", value=pm.get("affiliation") or "")
        lics = list(submit_mod.LICENCES)
        lic = st.selectbox("Licence", lics, index=lics.index(pm.get("licence", "CC-BY-4.0")),
                           format_func=lambda k: submit_mod.LICENCES[k])
        share = st.checkbox("Share this dataset with the IgneoSuite compilation (reviewed by Octa Insight first)",
                            value=bool(pm.get("shared", False)))
        go = st.form_submit_button("Save everything", type="primary")
    if go:
        if len(title.strip()) < 3:
            st.error("Please give the dataset a name (at least 3 characters).")
        elif share and S.get("location_check") == "some_wrong":
            st.error("You said some sample locations are wrong. Correct them before sharing the dataset.")
        else:
            S.project_meta = dict(title=title.strip(), reference=ref.strip() or None, description=desc.strip() or None,
                                  author_name=name.strip() or None, author_email=email.strip() or None,
                                  affiliation=aff.strip() or None, licence=lic, shared=share)
            do_save(["load", "missing", "test", "fill", "geometry", "clusters", "age_groups"], meta_changed=True)
    project_info()
    share_box()


ROLE_LABEL = {"view": "Can view", "edit": "Can edit"}


def share_box():
    """Owner: share the saved project with Octa users and/or invite people by email."""
    tok = _session_token()
    p = S.get("project")
    if not tok or not p:
        if tok:
            st.caption("Save the project first; then you can share it with other people.")
        return
    try:
        role = store.my_role(tok, p["id"])
    except Exception:
        role = None
    if role != "owner":
        if role == "edit":
            st.caption("This project was shared with you. Only its owner can share it further.")
        return
    st.divider()
    st.subheader("👥 Share this project")
    st.caption("People you share with see the project under *Shared with me* in step 1. "
               "**Can view**: they can open it and look at every step. **Can edit**: they can also save changes.")
    a, b = st.columns([3, 1], vertical_alignment="bottom")
    q = a.text_input("Find Octa users (name, username or email)", key="share_q")
    if b.button("Search", key="share_search") and len(q.strip()) >= 3:
        try:
            S._share_found = store.find_users(tok, q.strip())
        except Exception as e:
            st.error(str(e))
    found = {u["username"]: f"{u['name'] or u['username']} ({u['username']})"
                            + (f" · {u['affiliation']}" if u.get("affiliation") else "")
             for u in S.get("_share_found", [])}
    if "share_q" in S and S.get("_share_found") == [] and q.strip():
        st.caption("No Octa user matches. You can invite them by email below.")
    picked = st.multiselect("Octa users to share with", list(found), format_func=found.get, key="share_pick") \
        if found else []
    emails = st.text_area("And/or invite by email (one per line; people without an Octa account get an invitation "
                          "and see the project after they register with that email)", key="share_emails", height=80)
    role_new = st.radio("Access", list(ROLE_LABEL), format_func=ROLE_LABEL.get, horizontal=True, key="share_role")
    if st.button("Share", type="primary", key="share_go"):
        people = list(picked) + [e.strip() for e in emails.replace(",", "\n").splitlines() if e.strip()]
        if not people:
            st.error("Choose an Octa user or type an email address.")
        else:
            try:
                out = store.share(tok, p["id"], people, role_new)
            except Exception as e:
                out = {"ok": False, "error": str(e)}
            if not out.get("ok"):
                st.error(out.get("error", "Sharing failed."))
            else:
                _share_emails(out, role_new)
                for k in ("share_pick", "share_emails", "_share_found", "share_q"):
                    S.pop(k, None)
                st.rerun()
    if S.get("_share_msg"):
        kind, msg = S.pop("_share_msg")
        getattr(st, kind)(msg)
    try:
        current = store.shares(tok, p["id"])
    except Exception:
        current = []
    if current:
        st.markdown("**Shared with**")
        for x in current:
            c1, c2, c3 = st.columns([4, 1.4, 1], vertical_alignment="center")
            who = f"{x['name']} ({x['username']})" if x.get("name") else (x.get("username") or x["email"])
            c1.markdown(f"{who} · {x['email']}" + ("" if x.get("registered") else " · *invited, no account yet*"))
            c2.caption(ROLE_LABEL.get(x["role"], x["role"]))
            if c3.button("Remove", key=f"unshare_{x['email']}"):
                store.unshare(tok, p["id"], x["email"])
                st.rerun()


def _share_emails(out, role):
    """Tell the people a project was shared with; invite those without an account."""
    added = [x for x in out.get("added", []) if x.get("status") in ("user", "invited")]
    unknown = [x["person"] for x in out.get("added", []) if x.get("status") == "unknown"]
    sent, failed = 0, 0
    try:
        from octa_auth import mail
        can_mail = mail.enabled()
    except Exception:
        can_mail = False
    by, title = out.get("by") or "An IgneoSuite user", out.get("project") or "a project"
    access = "look at" if role == "view" else "look at and work on"
    for x in added if can_mail else []:
        try:
            if x["status"] == "user":
                mail.send(x["email"], f"{by} shared an IgneoSuite project with you",
                          [f"Dear {html.escape(x.get('name') or x.get('username') or '')},".replace("Dear ,", "Hello,"),
                           f"{html.escape(by)} shared the IgneoSuite project <b>{html.escape(title)}</b> with you. "
                           f"You can {access} it.",
                           "Log in to IgneoSuite and open it from <i>📂 Open a saved project → Shared with me</i> in step 1."],
                          button=("Open IgneoSuite", WEB_APP))
            else:
                mail.send(x["email"], f"{by} invited you to an IgneoSuite project",
                          ["Hello,",
                           f"{html.escape(by)} invited you to the IgneoSuite project <b>{html.escape(title)}</b>, so "
                           f"that you can {access} it. IgneoSuite is a free tool for testing, filling and exploring "
                           "gaps in igneous geochemical data.",
                           f"Create a free Octa account with this email address ({html.escape(x['email'])}); the "
                           "project then appears under <i>Shared with me</i> in step 1."],
                          button=("Create my account", WEB_APP.rstrip("/") + "/?register=1"))
            sent += 1
        except Exception:
            failed += 1
    msg = f"Shared with {len(added)} {'person' if len(added) == 1 else 'people'}."
    if can_mail and sent:
        msg += f" {sent} email{'s' if sent != 1 else ''} sent."
    if failed or (added and not can_mail):
        msg += " Some people could not be emailed; tell them yourself that the project is waiting for them."
    if unknown:
        msg += f" Not found (not a username or email): {', '.join(unknown)}."
    S._share_msg = ("warning" if unknown or failed else "success", msg)


# ---------------------------------------------------------------- saving and reopening
STEP_PAGES = {"load": 0, "missing": 1, "test_scattered": 2, "test_block": 2, "fill": 3, "geometry": 4, "clusters": 5}
STEP_LABEL = {"load": "step 1", "missing": "step 2", "test": "step 3", "fill": "step 4", "geometry": "step 5",
              "clusters": "step 6", "age_groups": "the age groups"}


def _changed(step):
    S.setdefault("changed", {})[step] = time.time()


def _available(step) -> bool:
    return {"load": "X" in S, "missing": "X" in S, "test": bool(S.get("val_scat")), "fill": "est" in S,
            "geometry": "geo" in S, "clusters": "clu" in S or "kscan" in S,
            "age_groups": S.get("age_table") is not None and len(S.age_table) > 0}[step]


def _sample_clusters():
    """Cluster number of every sample before and after filling (None where a sample was not clustered)."""
    c = S.get("clu")
    if not c:
        return None, None
    n = len(S.ids)
    rows = np.asarray(c["rows"])
    if rows.dtype != bool:                      # restored projects keep the row indices
        mask = np.zeros(n, bool); mask[rows.astype(int)] = True; rows = mask
    a = np.full(n, None, dtype=object); b = np.full(n, None, dtype=object)
    a[rows] = [int(v) for v in c["lr"]]
    b[rows] = [int(v) for v in c["lf"]]
    return a, b


def _rows_for_samples():
    cols = list(S.X.columns)
    a, b = _sample_clusters()
    rows = submit_mod.sample_rows("x", S.ids, cols, S.X.values.astype(float), S.meta,
                                  S.get("est"), S.get("E"), a, b)
    g = _sample_age_groups()
    if g is not None:
        for r, v in zip(rows, g):
            r["age_group"] = v
    for r, i in zip(rows, range(len(rows))):
        r.pop("dataset_id", None)
        for c in ("reference", "comment"):
            if c in S.meta:
                v = S.meta[c].iloc[i]
                r[c] = None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)
    return rows


def _pack(step):
    """(params, results) to store for one step."""
    X = S.X
    if step == "load":
        return (dict(id_column=S.id_col, column_map=S.meta_cols, variables=list(X.columns),
                     file=(S.get("sig") or [None])[0]),
                dict(report=S.report))
    if step == "missing":
        ree = diagnose.groups(X).get("REE", [])
        return ({}, dict(summary=diagnose.summary(X), per_variable=diagnose.per_variable(X),
                         co_missing_phi=diagnose.co_missing_phi(X), completeness=diagnose.completeness_curve(X),
                         groups=diagnose.groups(X), ree_pattern=diagnose.block_pattern(X, ree)))
    if step == "test_scattered":
        return S.get("scat_params", {}), S.val_scat
    if step == "test_block":
        return S.get("block_params", {}), S.val_block
    if step == "fill":
        return (dict(method=S.fill_method, error_band=S.q, block_variables=S.get("block_names", [])),
                dict(error_factors=S.F, n_estimated=int((np.isnan(X.values) & np.isfinite(S.est)).sum())))
    if step == "geometry":
        return S.geo_params, S.geo
    if step == "clusters":
        c = S.get("clu", {})
        res = {"k_scan": S.get("kscan")}
        if c:
            res.update(rows=np.where(c["rows"])[0], reference_labels=c["lr"], filled_labels=c["lf"],
                       pca_scores=c["P"], pca_explained=c["ev"],
                       crosstab=pd.crosstab(pd.Series(c["lr"], name="reference"), pd.Series(c["lf"], name="filled")))
        return (dict(reference_variables=c.get("base"), filled_variables=c.get("extra"), k=c.get("k")), res)
    if step == "age_groups":
        g = _sample_age_groups()
        return (dict(S.get("age_params", {}), table=S.age_table.to_dict(orient="records")),
                dict(stats=agegroups.stats(S.meta.age_ma.values),
                     counts=agegroups.counts(agegroups.assign(S.meta.age_ma.values, S.age_table), S.age_table)
                     .to_dict(orient="records"),
                     n_grouped=int(sum(v is not None for v in g))))
    raise KeyError(step)


def _dataset_meta():
    m = dict(S.get("project_meta", {}))
    m.update(n_samples=len(S.X), n_variables=S.X.shape[1], variables=list(S.X.columns), id_column=S.id_col,
             column_map=S.meta_cols, location_check=S.get("location_check", "not_checked"),
             location_comment=S.get("location_comment") or None, n_with_age=int(S.meta.age_ma.notna().sum()),
             session_id=telemetry.session_id())
    if "est" in S:
        m.update(estimation_method=S.fill_method, error_band=S.q)
    return m


def do_save(steps, meta_changed=False):
    """Save the given steps (and everything they depend on) to the project, creating it if needed."""
    user = _user()
    new = "project" not in S
    p = S.get("project") or store.new_project()
    saved = S.setdefault("saved", {})
    changed = S.get("changed", {})
    todo = [x for x in steps if _available(x)]
    with st.status("Saving to the IgneoSuite database…", expanded=True) as box:
        try:
            if new or meta_changed or "load" in todo:
                st.write("Project details")
                store.save_dataset(p, _dataset_meta(), user)
                S.project = p
            if new or ("load" in todo and changed.get("load", 0) > saved.get("load", 0)) or \
                    ("fill" in todo and changed.get("fill", 0) > saved.get("fill", 0)):
                bar = st.progress(0.0, "Samples")
                store.save_samples(p, _rows_for_samples(), user, progress=lambda f: bar.progress(f, "Samples"))
                saved["samples"] = time.time()
            for step in todo:
                parts = ["test_scattered", "test_block"] if step == "test" else [step]
                for part in parts:
                    if part == "test_block" and not S.get("val_block"):
                        continue
                    st.write(f"{STEP_LABEL[step].capitalize()}: settings and results")
                    params, results = _pack(part)
                    store.save_step(p, part, params, results, user)
                    if part == "age_groups":
                        g = _sample_age_groups()
                        store.save_age_groups(p, [dict(row_number=i + 1, g=v) for i, v in enumerate(g)
                                                  if v is not None], user)
                    if part == "clusters":
                        a, b = _sample_clusters()
                        if a is not None:
                            store.save_clusters(p, [dict(row_number=i + 1, a=a[i], b=b[i]) for i in range(len(a))
                                                    if a[i] is not None], user)
                saved[step] = time.time()
            if "test" in todo and not S.get("val_block"):
                store.delete_step(p, "test_block", user)
            box.update(label="Saved.", state="complete", expanded=False)
        except Exception as e:
            box.update(label="Saving failed.", state="error", expanded=True)
            st.error(str(e))
            return False
    tok = _session_token()
    if tok and not store.by_account(p) and S.get("_claimed") != p["id"]:
        try:
            store.claim(p, tok)
            S._claimed = p["id"]
        except Exception:
            pass
    if store.by_account(p):
        st.query_params["project"] = p["id"]
        if "key" in st.query_params:
            del st.query_params["key"]
    else:
        st.query_params.update({"project": p["id"], "key": p["key"]})
    telemetry.event("save", {"steps": todo, "new": new}, user)
    st.toast("Saved ✅")
    return True


def project_info():
    if "project" not in S:
        return
    p = S.project
    st.success(f"Saved project: **{S.get('project_meta', {}).get('title', '')}**")
    if _session_token():
        st.markdown("The project is kept in **your account**: open it again from *📂 Open a saved project* in "
                    "step 1 whenever you are logged in. To work on it with others, share it below.")
        return
    if store.by_account(p):
        return
    st.markdown("To continue later, keep this page's address (it now contains your project), or note your "
                "**project code**. Anyone with the code can open the project, so keep it private.")
    st.code(store.project_code(p), language=None)


def _role():
    """owner / edit / view for the open project (None when there is no account)."""
    p = S.get("project")
    if not p:
        return "owner"
    if p.get("role"):
        return p["role"]
    return None if store.by_account(p) else "owner"


def _view_only_note():
    p = S.get("project", {})
    st.info(f"🔒 You can look at this project, which {p.get('owner') or 'its owner'} shared with you, but not "
            "save changes to it. Ask the owner for edit rights if you need them.")


def save_bar(step):
    """Save button at the bottom of a step."""
    st.divider()
    if not store.enabled():
        st.caption("Saving is not set up for this installation.")
        return
    if _role() == "view":
        _view_only_note()
        return
    saved = S.get("saved", {}).get(step, 0)
    changed = S.get("changed", {}).get("test_scattered" if step == "test" else step, 0)
    if step == "test":
        changed = max(changed, S.get("changed", {}).get("test_block", 0))
    if "project" not in S:
        with st.form(f"first_save_{step}"):
            st.markdown(f"**💾 Save your work** – the data and the results of {STEP_LABEL[step]} are stored "
                        "in the IgneoSuite database, so you can continue later without repeating calculations.")
            a, b = st.columns(2)
            title = a.text_input("Dataset name *", key=f"t_{step}")
            ref = b.text_input("DOI or reference of the compilation", key=f"r_{step}")
            go = st.form_submit_button(f"Save {STEP_LABEL[step]}", type="primary")
        if go:
            if len(title.strip()) < 3:
                st.error("Please give the dataset a name (at least 3 characters).")
                return
            S.project_meta = dict(title=title.strip(), reference=ref.strip() or None, licence="CC-BY-4.0")
            if do_save(["load", step] if step != "load" else ["load"]):
                st.rerun()
        return
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    go = c1.button(f"💾 Save {STEP_LABEL[step]}", key=f"save_{step}", type="primary")
    if saved and saved >= changed:
        c2.caption(f"Saved at {time.strftime('%H:%M', time.localtime(saved))} in project "
                   f"“{S.get('project_meta', {}).get('title', '')}”.")
    elif saved:
        c2.caption("Changed since the last save.")
    else:
        c2.caption("Not saved yet.")
    if go and do_save([step]):
        st.rerun()


def _project_row(d, key, label_extra="", delete_col=False, d_id=None, pending=False):
    if delete_col:
        c1, c2, c3 = st.columns([5, 1, 1.3], vertical_alignment="center")
        tok = _session_token()
        if pending:
            if c3.button("Cancel deletion", key=f"undel_{d_id}"):
                store.cancel_delete(tok, d_id)
                st.rerun()
        elif c3.button("🗑 Delete", key=f"del_{d_id}"):
            S._del_target = None if S.get("_del_target") == d_id else d_id
            st.rerun()
    else:
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
    when = str(d.get("updated_at") or "")[:16].replace("T", " ")
    last = STEP_LABEL.get(d.get("last_step") or "", d.get("last_step") or "")
    title = (d.get("title") or "Untitled").replace("*", "").replace("_", " ")
    c1.markdown(f"**{title}**{label_extra} · {d.get('n_samples') or 0:,} samples"
                f"{' · last saved: ' + last if last else ''} · {when}")
    return c2.button("Open", key=key)


def _delete_form(tok, d):
    """Owner asks for a project to be deleted; an Octa administrator must approve it."""
    with st.container(border=True):
        n = d.get("n_shares") or 0
        st.markdown(f"**Delete “{d.get('title') or 'Untitled'}”?**")
        st.write("Deleting removes the data, the filled values and the saved results of every step"
                 + (f", and the project disappears for the {n} {'person' if n == 1 else 'people'} you shared it with"
                    if n else "") + ". To protect you from mistakes, nothing is deleted until an Octa Insight "
                 "administrator approves the request. You can cancel it until then.")
        reason = st.text_area("Why should it be deleted? (comment for the administrator)", key=f"del_reason_{d['id']}",
                              max_chars=2000, height=80)
        sure = st.checkbox("I understand that the project and everything saved with it will be deleted for good once "
                           "approved.", key=f"del_sure_{d['id']}")
        c1, c2 = st.columns(2)
        if c1.button("Send deletion request", type="primary", disabled=not sure, key=f"del_go_{d['id']}"):
            try:
                out = store.request_delete(tok, d["id"], reason)
            except Exception as e:
                out = {"ok": False, "error": str(e)}
            if not out.get("ok"):
                st.error(out.get("error", "The request could not be sent."))
                return
            _notify_admin_delete(out, reason)
            S._del_target = None
            S._del_msg = ("Your deletion request was sent. An administrator will review it; the project stays "
                          "available until then.")
            st.rerun()
        if c2.button("Keep the project", key=f"del_no_{d['id']}"):
            S._del_target = None
            st.rerun()


def _notify_admin_delete(out, reason):
    try:
        from octa_auth import mail
        if not mail.enabled():
            return
        admin = st.secrets["email"]["user"]
        mail.send(admin, f"IgneoSuite: deletion request for “{out.get('title')}”",
                  [f"{html.escape(out.get('by') or 'A user')} asked to delete the IgneoSuite project "
                   f"<b>{html.escape(out.get('title') or '')}</b>.",
                   f"Comment: {html.escape(reason or '(none)')}",
                   "Log in to IgneoSuite as administrator and open the <i>Admin</i> page to approve or reject it."],
                  button=("Open IgneoSuite", WEB_APP))
    except Exception:
        pass


def _notify_owner_decision(out, comment):
    try:
        from octa_auth import mail
        if not mail.enabled() or not out.get("owner_email"):
            return
        ok = out.get("status") == "approved"
        mail.send(out["owner_email"],
                  f"IgneoSuite: your project “{out.get('title')}” was {'deleted' if ok else 'not deleted'}",
                  [f"Dear {html.escape(out.get('owner_name') or 'IgneoSuite user')},",
                   (f"your request was approved: the project <b>{html.escape(out.get('title') or '')}</b> and "
                    "everything saved with it have been deleted." if ok else
                    f"your request to delete <b>{html.escape(out.get('title') or '')}</b> was not approved; "
                    "the project is still in your account.")]
                  + ([f"Comment from the administrator: {html.escape(comment)}"] if comment else []),
                  button=("Open IgneoSuite", WEB_APP))
    except Exception:
        pass


def page_admin():
    st.header("Admin · deletion requests")
    tok = _session_token()
    try:
        out = store.admin_delete_requests(tok)
    except Exception as e:
        st.error(str(e))
        return
    if not out.get("ok"):
        st.error(out.get("error", "Admins only."))
        return
    if S.get("_admin_msg"):
        st.success(S.pop("_admin_msg"))
    reqs = out.get("requests", [])
    pending = [r for r in reqs if r["status"] == "pending"]
    st.caption("Project owners ask here for a project to be deleted. Approving deletes the project, its samples, "
               "filled values, saved steps and all shares, for good. Rejecting keeps everything.")
    if not pending:
        st.info("No deletion requests are waiting.")
    for r in pending:
        with st.container(border=True):
            when = str(r.get("created_at") or "")[:16].replace("T", " ")
            st.markdown(f"**{html.escape(r.get('title') or 'Untitled')}** · {r.get('n_samples') or 0:,} samples · "
                        f"shared with {r.get('n_shares') or 0}")
            st.markdown(f"Owner: {html.escape(r.get('owner') or '')} ({html.escape(r.get('owner_email') or '')}) · "
                        f"asked {when}")
            st.markdown(f"Owner's comment: *{html.escape(r.get('reason') or '(none)')}*")
            if not r.get("exists"):
                st.caption("The project no longer exists.")
            comment = st.text_input("Your comment (sent to the owner)", key=f"adm_c_{r['id']}")
            sure = st.checkbox("Yes, delete this project and everything linked to it", key=f"adm_s_{r['id']}")
            c1, c2, _ = st.columns([1.3, 1, 3])
            for col, label, approve, kw in ((c1, "Approve and delete", True, dict(type="primary", disabled=not sure)),
                                            (c2, "Reject", False, {})):
                if col.button(label, key=f"adm_{'y' if approve else 'n'}_{r['id']}", **kw):
                    try:
                        res = store.admin_decide_delete(tok, r["id"], approve, comment)
                    except Exception as e:
                        res = {"ok": False, "error": str(e)}
                    if not res.get("ok"):
                        st.error(res.get("error"))
                    else:
                        _notify_owner_decision(res, comment)
                        S._admin_msg = (f"“{r.get('title')}” was deleted." if approve else
                                        f"The request for “{r.get('title')}” was rejected.")
                        st.rerun()
    done = [r for r in reqs if r["status"] != "pending"]
    if done:
        st.subheader("Earlier requests")
        st.dataframe(pd.DataFrame([dict(Project=r.get("title"), Owner=r.get("owner_email"), Status=r["status"],
                                        Asked=str(r.get("created_at") or "")[:16].replace("T", " "),
                                        Decided=str(r.get("decided_at") or "")[:16].replace("T", " "),
                                        By=r.get("decided_by"), Reason=r.get("reason"),
                                        Comment=r.get("admin_comment")) for r in done]),
                     hide_index=True, use_container_width=True)


def open_project_box():
    if not store.enabled():
        return
    tok = _session_token()
    with st.expander("📂 Open a saved project", expanded=bool(tok) and "X" not in S):
        if not tok:
            if S.get("_accounts"):
                st.caption("Log in to see your projects and the projects others shared with you.")
                return
            # installations without Octa accounts: open with the code given when the project was saved
            code = st.text_input("Project code", placeholder="paste the code you got when you saved", key="open_code")
            if st.button("Open", key="open_btn"):
                p = store.parse_code(code)
                if not p:
                    st.error("That does not look like a project code.")
                else:
                    open_project(p)
            return
        try:
            mine, shared = store.my_projects(tok), store.shared_with_me(tok)
        except Exception as e:
            st.caption(f"Your projects could not be listed. {e}")
            return
        if S.get("_del_msg"):
            st.success(S.pop("_del_msg"))
        st.markdown("**My projects**")
        if not mine:
            st.caption("Projects you save while logged in will be listed here.")
        for d in mine[:50]:
            extra = " · 🗑 *deletion requested, waiting for approval*" if d.get("delete_requested") else ""
            if _project_row(d, f"mine_{d['id']}", extra, delete_col=True, d_id=d["id"],
                            pending=bool(d.get("delete_requested"))):
                open_project({"id": d["id"], "key": store.account_key(tok), "role": "owner"})
            if S.get("_del_target") == d["id"]:
                _delete_form(tok, d)
        st.markdown("**Shared with me**")
        if not shared:
            st.caption("Projects other IgneoSuite users share with you will be listed here.")
        for d in shared[:50]:
            who = d.get("owner") or d.get("owner_username") or "another user"
            badge = "can edit" if d.get("role") == "edit" else "view only"
            if _project_row(d, f"shared_{d['id']}", f" · from {who} · {badge}"):
                open_project({"id": d["id"], "key": store.account_key(tok), "role": d.get("role", "view"),
                              "owner": who})


def open_project(p):
    user = _user()
    try:
        with st.spinner("Opening the saved project…"):
            out = store.load(p, user)
    except Exception as e:
        st.error(f"The project could not be opened. {e}")
        return False
    S._pending_open = (p, out)          # applied at the start of the next run, before the sidebar exists
    telemetry.event("resume", {"last_step": out["dataset"].get("last_step")}, user)
    st.rerun()


def restore(p, out):
    """Rebuild the session from a saved project."""
    d, steps, rows = out["dataset"], out["steps"], out["samples"]
    for k in list(S.keys()):
        if k not in ("_user", "_sid", "_octa_auth", "module", "ex_src"):
            del S[k]
    cols = list(d.get("variables") or (steps.get("load", {}).get("params", {}).get("variables") or []))
    meas = pd.DataFrame([r.get("measured") or {} for r in rows]).reindex(columns=cols).astype(float)
    S.X = meas
    S.ids = np.array([str(r.get("sample_id")) for r in rows])
    S.meta = pd.DataFrame({k: [r.get(k) for r in rows] for k in
                           ("latitude", "longitude", "age_ma", "latitude_original", "longitude_original",
                            "reference", "comment")})
    for k in ("latitude", "longitude", "age_ma"):
        S.meta[k] = pd.to_numeric(S.meta[k]).astype(float)
    lp = steps.get("load", {})
    S.id_col = d.get("id_column") or lp.get("params", {}).get("id_column") or "Sample"
    S.meta_cols = d.get("column_map") or lp.get("params", {}).get("column_map") or {}
    S.value_cols = cols
    S.report = lp.get("results", {}).get("report") or dict(
        n_rows=len(meas), n_cols=len(cols), counts=dict(number=int(meas.notna().values.sum()), recovered=0,
                                                       missing=int(meas.isna().values.sum()), text=0),
        text_examples={}, nonpositive={})
    if d.get("location_check") in LOC_ANSWERS:
        S.location_check = d["location_check"]
    if d.get("location_comment"):
        S.location_comment = d["location_comment"]
    S.project = p
    S.project_meta = {k: d.get(k) for k in ("title", "reference", "description", "author_name", "author_email",
                                            "affiliation", "licence", "shared")}
    now = time.time()
    saved = {"load": now, "samples": now}
    if "missing" in steps:
        saved["missing"] = now
    for part, store_key, pkey in (("test_scattered", "val_scat", "scat_params"), ("test_block", "val_block", "block_params")):
        if part in steps and steps[part]["results"]:
            S[store_key] = steps[part]["results"]
            S[pkey] = steps[part]["params"]
            saved["test"] = now
    if "test_scattered" in steps:
        sp = steps["test_scattered"]["params"]
        S.methods, S.reps, S.seed = sp.get("methods", []), sp.get("reps", 3), sp.get("seed", 0)
        S.frac_pct = int(round(100 * sp.get("frac", 0.05)))
        S.recommended = validate.recommend(S.val_scat["score"])[0]
    if "test_block" in steps:
        bp = steps["test_block"]["params"]
        S.block_names, S.bfrac_pct = bp.get("block", []), int(round(100 * bp.get("frac", 0.1)))
    if "fill" in steps and any(r.get("estimated") for r in rows):
        est_df = pd.DataFrame([r.get("estimated") or {} for r in rows]).reindex(columns=cols).astype(float)
        err_df = pd.DataFrame([r.get("estimate_error") or {} for r in rows]).reindex(columns=cols).astype(float)
        M = meas.values
        S.est = np.where(np.isnan(M), est_df.values, M)
        S.E = np.where(np.isnan(M), err_df.values, np.nan)
        fp = steps["fill"]["params"]
        S.fill_method, S.q = fp.get("method"), fp.get("error_band", 0.68)
        S.F = steps["fill"]["results"].get("error_factors")
        saved["fill"] = now
    if "geometry" in steps:
        S.geo, S.geo_params = steps["geometry"]["results"], steps["geometry"]["params"]
        saved["geometry"] = now
    if "clusters" in steps:
        r, pp = steps["clusters"]["results"], steps["clusters"]["params"]
        if r.get("k_scan") is not None:
            S.kscan = r["k_scan"]
        if r.get("rows") is not None:
            mask = np.zeros(len(rows), bool); mask[np.asarray(r["rows"], int)] = True
            S.clu = dict(rows=mask, lr=np.asarray(r["reference_labels"]), lf=np.asarray(r["filled_labels"]),
                         base=pp.get("reference_variables"), extra=pp.get("filled_variables"), k=pp.get("k"),
                         P=np.asarray(r["pca_scores"]), ev=np.asarray(r["pca_explained"]))
        saved["clusters"] = now
    if "age_groups" in steps:
        ap = steps["age_groups"]["params"]
        t = pd.DataFrame(ap.get("table") or [], columns=agegroups.COLUMNS)
        S.age_table, S.age_base = t, t.copy()
        S.age_params = {k: v for k, v in ap.items() if k != "table"}
        S.age_ver = S.get("age_ver", 0) + 1
        saved["age_groups"] = now
    S.saved = saved
    S.changed = {}
    last = d.get("last_step")
    if not S.get("module"):
        S.module = "explore" if "age_groups" in steps else "fill"
    if S.module == "explore":
        S.step = EX_STEPS[1] if S.meta.age_ma.notna().any() else EX_STEPS[2]
    else:
        S.step = STEPS[STEP_PAGES.get(last, 0)]
    S.resumed = d.get("title")
    st.query_params.update({"project": p["id"], "key": p["key"]})


# ================================================================ IgneoSuite 2: modules
MODULES = {"fill": "Fill gaps in a large dataset", "explore": "Plot and explore the data"}
EX_STEPS = ["1 · Load data", "2 · Age groups", "3 · Plots and parameters", "4 · Save & share", "About"]


def _goto(step):
    S._goto = step


def _sample_age_groups():
    """Age group of every sample (None without an age), or None when no grouping was made."""
    t = S.get("age_table")
    if t is None or not len(t) or "meta" not in S:
        return None
    lab = agegroups.assign(S.meta.age_ma.values, t)
    return [None if v == agegroups.NO_AGE else str(v) for v in lab]


def choose_module(m):
    S.module = m
    S.step = (STEPS if m == "fill" else EX_STEPS)[0]
    st.query_params["module"] = m


def page_modules():
    st.header("What would you like to do?")
    st.write("IgneoSuite has two modules. Both start with the same step: load your data, check the sample "
             "locations on a map and save it.")
    a, b = st.columns(2)
    with a.container(border=True):
        st.markdown("### 🧩 Fill gaps in a large dataset")
        st.write("Look at the missing values, test the gap-filling methods on your own data, fill the gaps with an "
                 "error for every estimate, and check the structure of the data (geometry and clusters).")
        st.button("Start gap-filling", type="primary", key="mod_fill", on_click=choose_module, args=("fill",),
                  use_container_width=True)
    with b.container(border=True):
        st.markdown("### 📊 Plot and explore the data")
        st.write("Plot the data and look at its statistics and geochemical parameters. Use a dataset you saved in "
                 "IgneoSuite (for example after gap-filling), or upload a new file, small or large, complete or "
                 "with gaps. Samples with ages can be grouped by age and shown on the map.")
        st.button("Start exploring", type="primary", key="mod_explore", on_click=choose_module, args=("explore",),
                  use_container_width=True)


def _saved_lists():
    """My projects / Shared with me, to open one (module 2a)."""
    tok = _session_token()
    if not store.enabled():
        st.info("Saved datasets are not available in this installation. Upload a file instead.")
        return
    if not tok:
        if S.get("_accounts"):
            st.info("Log in to see your saved datasets and those shared with you.")
        else:
            code = st.text_input("Project code", placeholder="paste the code you got when you saved", key="ex_code")
            if st.button("Open", key="ex_code_btn"):
                p = store.parse_code(code)
                st.error("That does not look like a project code.") if not p else open_project(p)
        return
    try:
        mine, shared = store.my_projects(tok), store.shared_with_me(tok)
    except Exception as e:
        st.error(f"Your datasets could not be listed. {e}")
        return
    st.markdown("**My projects**")
    if not mine:
        st.caption("Nothing saved yet. Datasets you save while logged in appear here.")
    for d in mine[:50]:
        if _project_row(d, f"ex_mine_{d['id']}"):
            open_project({"id": d["id"], "key": store.account_key(tok), "role": "owner"})
    st.markdown("**Shared with me**")
    if not shared:
        st.caption("Datasets other IgneoSuite users share with you appear here.")
    for d in shared[:50]:
        who = d.get("owner") or d.get("owner_username") or "another user"
        badge = "can edit" if d.get("role") == "edit" else "view only"
        if _project_row(d, f"ex_shared_{d['id']}", f" · from {who} · {badge}"):
            open_project({"id": d["id"], "key": store.account_key(tok), "role": d.get("role", "view"), "owner": who})


def _next_after_load():
    if "X" not in S:
        return
    st.divider()
    if S.meta.age_ma.notna().any():
        st.button("Next: step 2 · Age groups →", type="primary", on_click=_goto, args=(EX_STEPS[1],), key="ex_next1")
    else:
        st.info("This dataset has no ages, so the age grouping (step 2) is skipped.")
        st.button("Next: step 3 · Plots and parameters →", type="primary", on_click=_goto, args=(EX_STEPS[2],),
                  key="ex_next1")


def page_explore_load():
    st.header("Load data")
    src = st.radio("Which data do you want to explore?", ["saved", "upload"], horizontal=True, key="ex_src",
                   format_func={"saved": "A dataset saved in IgneoSuite", "upload": "Upload a new file"}.get)
    if src == "saved":
        st.caption("For example a dataset you filled in the gap-filling module. Filled values and their errors "
                   "come with it.")
        if "X" in S:
            st.info(f"Open now: **{S.get('project_meta', {}).get('title', 'unsaved data')}**. "
                    "Choose another one below to replace it.")
        with st.expander("📂 Choose a saved dataset", expanded="X" not in S):
            _saved_lists()
        if "X" in S:
            show_loaded()
            save_bar("load")
    else:
        st.caption("The file has the same layout as in the gap-filling module: sample ID, latitude, longitude, "
                   "age (optional), reference and comment (optional), then the elements and element ratios. It can "
                   "be small or large, complete or with missing values.")
        page_load(with_open=False, header=False)
    _next_after_load()


def _age_hist(age, lab, table, col):
    import plotly.graph_objects as go
    ok = np.isfinite(age)
    fig = go.Figure()
    order = list(table["Group"]) + [agegroups.OUTSIDE]
    for g in order:
        sel = ok & (lab == g)
        if sel.any():
            fig.add_trace(go.Histogram(x=age[sel], name=f"{g} ({int(sel.sum())})", marker_color=col.get(g, "#9a9893"),
                                       nbinsx=60, opacity=0.9,
                                       hovertemplate="%{x} Ma: %{y} samples<extra>" + g + "</extra>"))
    fig.update_layout(barmode="stack", height=320, margin=dict(l=50, r=10, t=10, b=40), plot_bgcolor="#ffffff",
                      xaxis=dict(title="Age (Ma)", gridcolor="#ecebe7"), yaxis=dict(title="Samples", gridcolor="#ecebe7"),
                      legend=dict(font=dict(size=11), traceorder="normal"))
    return fig


def page_age():
    _need("X", "Load data first (step 1).")
    st.header("Age groups")
    age = S.meta.age_ma.values.astype(float)
    if not np.isfinite(age).any():
        st.info("This dataset has no ages, so there is nothing to group. Continue with step 3.")
        st.button("Next: step 3 · Plots and parameters →", type="primary", on_click=_goto, args=(EX_STEPS[2],))
        return
    sm = agegroups.stats(age)
    st.subheader("Age statistics")
    m = st.columns(6)
    m[0].metric("With age", f"{sm['n_with_age']:,}")
    m[1].metric("Without age", f"{sm['n_without_age']:,}")
    m[2].metric("Youngest", f"{sm['min']:,.1f} Ma")
    m[3].metric("Oldest", f"{sm['max']:,.1f} Ma")
    m[4].metric("Median", f"{sm['median']:,.1f} Ma")
    m[5].metric("Mean ± SD", f"{sm['mean']:,.0f} ± {sm['std']:,.0f}")
    st.caption(f"Middle half of the ages: {sm['q25']:,.1f}–{sm['q75']:,.1f} Ma (25th–75th percentile).")

    st.subheader("Group the samples by age")
    ap = S.get("age_params", {})
    methods = list(agegroups.METHODS)
    c1, c2 = st.columns([2, 3])
    method = c1.selectbox("Grouping", methods, format_func=agegroups.METHODS.get,
                          index=methods.index(ap.get("method", "timescale")), key="age_method")
    opts = {}
    with c2:
        if method == "timescale":
            levels = list(agegroups.TIMESCALE)
            opts["level"] = st.radio("Level of the time scale", levels, horizontal=True,
                                     index=levels.index(ap.get("level", "Period")), key="age_level")
            o1, o2 = st.columns(2)
            opts["only_used"] = o1.checkbox("Only the intervals that contain samples", value=True, key="age_used")
            opts["ics_colours"] = o2.checkbox("Official time-scale colours", value=bool(ap.get("ics_colours", False)),
                                              key="age_ics", help="The ICS chart colours. Neighbouring intervals can "
                                                                  "look alike on the map.")
        elif method == "width":
            opts["width"] = st.number_input("Interval width (Ma)", min_value=0.1, value=float(ap.get("width", 100.0)),
                                            step=10.0, key="age_width")
            opts["only_used"] = st.checkbox("Only the intervals that contain samples", value=True, key="age_used_w")
        elif method == "count":
            opts["n_groups"] = st.slider("Number of groups", 2, 12, int(ap.get("n_groups", 5)), key="age_n")
        else:
            opts["custom"] = st.text_input("Boundaries in Ma, separated by commas",
                                           value=ap.get("custom", "0, 66, 252, 541, 1000, 2500"), key="age_custom",
                                           help="For example 0, 66, 252, 541: groups 0–66, 66–252 and 252–541 Ma.")
    fresh = S.get("age_table") is None
    if st.button("Make the groups", type="primary" if fresh else "secondary", key="age_make") or fresh:
        t = agegroups.propose(age, method, **opts)
        if not len(t):
            st.error("These settings give no groups. For your own boundaries, give at least two numbers.")
            return
        S.age_base, S.age_table = t, t.copy()
        S.age_params = dict(method=method, **opts)
        S.age_ver = S.get("age_ver", 0) + 1
        _changed("age_groups")
    st.markdown("**The groups** · rename them, change their limits or colours (hex code such as #2a78d6), "
                "add rows at the bottom or delete rows. Ages from ‘From’ up to (not including) ‘To’ belong to a group.")
    edited = st.data_editor(S.age_base, num_rows="dynamic", hide_index=True, use_container_width=True,
                            key=f"age_editor_{S.get('age_ver', 0)}",
                            column_config={"Group": st.column_config.TextColumn(max_chars=100, required=True),
                                           "From (Ma)": st.column_config.NumberColumn(format="%.2f", min_value=0),
                                           "To (Ma)": st.column_config.NumberColumn(format="%.2f", min_value=0),
                                           "Colour": st.column_config.TextColumn(max_chars=7)})
    table, problems = agegroups.clean(edited)
    for p_ in problems:
        st.warning(p_)
    if not table.equals(S.age_table.reset_index(drop=True) if S.get("age_table") is not None else None):
        S.age_table = table
        _changed("age_groups")
    if not len(table):
        st.info("Add at least one group.")
        return
    lab = agegroups.assign(age, table)
    col = agegroups.colours(table)
    cnt = agegroups.counts(lab, table)
    c1, c2 = st.columns([1, 2])
    with c1:
        st.dataframe(cnt, hide_index=True, use_container_width=True)
    with c2:
        iplots.show(_age_hist(age, lab, table, col), "Age histogram by group", "fig_age_hist",
                    data=pd.DataFrame({S.id_col: S.ids, "Age (Ma)": age, "Age group": lab}).set_index(S.id_col))
    n_out = int((lab == agegroups.OUTSIDE).sum())
    if n_out:
        st.warning(f"{n_out} samples with an age fall outside every group. Widen the groups or add one.")
    st.subheader("Map of the age groups")
    order = list(table["Group"]) + [agegroups.OUTSIDE, agegroups.NO_AGE]
    location_map("age_map", groups=lab, group_colours=col, group_order=order, ask=False)
    save_bar("age_groups")
    if S.get("saved", {}).get("age_groups"):
        st.button("Next: step 3 · Plots and parameters →", type="primary", on_click=_goto, args=(EX_STEPS[2],),
                  key="age_next")
    else:
        st.caption("Save the groups to keep them with your project, then continue with step 3.")
        st.button("Continue to step 3 without saving →", on_click=_goto, args=(EX_STEPS[2],), key="age_next_nosave")


def page_plots():
    _need("X", "Load data first (step 1).")
    st.header("Plots and parameters")
    st.info("This step is being built: plots, statistics and geochemical parameters of your data. "
            "Your data" + (" and age groups are" if S.get("age_table") is not None else " is") + " ready for it.")


def page_about():
    st.header("About IgneoSuite")
    st.markdown(f"""
IgneoSuite {__version__} is open-source software from Octa Insight for working with incomplete igneous geochemical data.

**Workflow.** (1) Read the table and recover numbers hidden by stray spaces. (2) Describe where values are missing,
including elements that are reported together, such as the REE. (3) Hide measured values, estimate them with each method,
and score the errors, both for scattered gaps and for whole blocks. (4) Fill the gaps with the chosen method and export
every value as measured, estimated, or ± error. (5) Describe the geometry of the data: dimensions, grouping and the
principal components. (6) Optionally compare clusters before and after gap-filling. (7) Save the project, and share
it with the IgneoSuite compilation if you wish. Every step can be saved and reopened later.

**Methods.** {"; ".join(f"*{m}*: {d}" for m, (_, d) in METHODS.items())}.
Model-based methods work on log10-transformed, standardised values.

**Licence.** IgneoSuite is free software: you can redistribute it and/or modify it under the terms of the
GNU Affero General Public License, version 3 only (AGPL-3.0-only). It comes with no warranty. The complete source code
of the version you are using is at [github.com/OctaInsight/IgneoSuite](https://github.com/OctaInsight/IgneoSuite).
© 2026 Octa Insight. Produced by Octa Systems.

**How to cite.** Please cite the paper and the software (the sidebar has copy buttons and a BibTeX file):

{CITE_PAPER}

{cite_software()}

**Privacy.** Your data are stored only when you press a Save button, under the licence you
choose. Saved projects are private: they can be opened only with their project code (and, later, by their owner
after signing in). Unsaved work stays in this browser session. To improve the software, IgneoSuite records anonymous usage
statistics (table size, share missing, methods tested and their error scores), never data values or sample IDs.
""")
    if telemetry.enabled():
        with st.form("feedback", clear_on_submit=True):
            st.subheader("Send feedback")
            rating = st.select_slider("How useful was IgneoSuite?", options=[1, 2, 3, 4, 5], value=4)
            msg = st.text_area("Comments, problems or ideas", max_chars=4000)
            email = st.text_input("Email (optional, if you would like a reply)")
            if st.form_submit_button("Send"):
                ok = telemetry.feedback(rating, msg, email.strip() or None, _user())
                st.success("Thank you, your feedback was sent.") if ok else st.error("Sending failed. Please try again later.")


ADMIN_STEP = "🛡 Admin"
PAGES = dict(zip(STEPS, [page_load, page_diagnose, page_validate, page_fill, page_geometry, page_cluster, page_save,
                         page_about]))


EX_PAGES = dict(zip(EX_STEPS, [page_explore_load, page_age, page_plots, page_save, page_about]))

SOURCE_URL = "https://github.com/OctaInsight/IgneoSuite"


CITE_PAPER = ("Abu-Alam, T.S., Güzey, A., Khalil, T.T., Abu-Anber, M., Said, A., Abu-Alam, N.T., Ghoneim, M., 2026. "
              "When simpler wins: recovering the structure of incomplete geochemical data. "
              "Computers & Geosciences (submitted).")


DOI = "10.5281/zenodo.23919430"
WEB_APP = "https://igneosuite.streamlit.app/"
SOFTWARE_TITLE = ("IgneoSuite 1.0.0: an open-source application for testing, filling and exploring gaps in "
                  "igneous geochemical data")


def cite_software():
    return ("Abu-Alam, T.S., Güzey, A., Khalil, T.T., Abu-Anber, M., Said, A., Abu-Alam, N.T., Ghoneim, M., "
            f"2026. {SOFTWARE_TITLE}. Zenodo. https://doi.org/{DOI}. Web app: {WEB_APP}")


def _bibtex():
    return (
        "@article{AbuAlam2026simpler,\n"
        "  author  = {Abu-Alam, Tamer S. and G{\\\"u}zey, Alparslan and Khalil, Thoraya T. and Abu-Anber, Mohamed and\n"
        "             Said, Ahmed and Abu-Alam, Nour El-Din T. and Ghoneim, Mohamed},\n"
        "  title   = {When simpler wins: recovering the structure of incomplete geochemical data},\n"
        "  journal = {Computers \\& Geosciences},\n  year    = {2026},\n  note    = {Submitted}\n}\n\n"
        "@software{AbuAlam2026IgneoSuite,\n"
        "  author    = {Abu-Alam, Tamer S. and G{\\\"u}zey, Alparslan and Khalil, Thoraya T. and Abu-Anber, Mohamed and\n"
        "               Said, Ahmed and Abu-Alam, Nour El-Din T. and Ghoneim, Mohamed},\n"
        f"  title     = {{{SOFTWARE_TITLE}}},\n"
        f"  version   = {{{__version__}}},\n  year      = {{2026}},\n  publisher = {{Zenodo}},\n"
        f"  doi       = {{{DOI}}},\n  url       = {{https://doi.org/{DOI}}},\n"
        f"  note      = {{Web app: {WEB_APP}}},\n  license   = {{AGPL-3.0-only}}\n}}\n")


def _sidebar_footer():
    from pathlib import Path
    st.divider()
    st.markdown("<style>[data-testid='stSidebar'] pre, [data-testid='stSidebar'] pre code"
                "{font-size:0.72rem !important;line-height:1.35 !important;font-family:'Source Sans Pro',"
                "Arial,sans-serif !important}</style>", unsafe_allow_html=True)
    st.markdown("**📖 How to cite**")
    st.caption("If IgneoSuite helps your work, please cite the paper and the software:")
    st.code(CITE_PAPER, language=None, wrap_lines=True)
    st.code(cite_software(), language=None, wrap_lines=True)
    st.download_button("⬇ BibTeX", _bibtex().encode(), "IgneoSuite_citation.bib", "text/plain", key="cite_bib")
    st.markdown(
        f"<div style='font-size:0.82rem;line-height:1.5;color:#52514e'>"
        f"<b style='color:#0b0b0b'>IgneoSuite {__version__}</b><br>"
        f"© 2026 Octa Insight · Produced by Octa Systems<br>"
        f"Free software under the <a href='https://www.gnu.org/licenses/agpl-3.0.html' target='_blank'>GNU AGPL v3</a> · "
        f"<a href='{SOURCE_URL}' target='_blank'>Source code</a></div>", unsafe_allow_html=True)
    logo = Path(__file__).parent / "data" / "octa_logo.png"
    if logo.exists():
        import base64
        b64 = base64.b64encode(logo.read_bytes()).decode()
        # full-resolution image, scaled by the browser so it stays sharp on high-density screens
        st.markdown(f"<img src='data:image/png;base64,{b64}' alt='Octa Insight' "
                    f"style='width:150px;height:auto;margin-top:6px;image-rendering:auto'>", unsafe_allow_html=True)


def render(user=None, app=None):
    """Draw the app. `user` is reserved for the Octa Insight portal (None = open use).

    A portal passes an object with `.id` (Supabase auth user id) and `.access_token`; usage rows are then
    stored under that user. With `user=None` rows are anonymous.
    """
    S["_user"] = user
    S["_accounts"] = app is not None
    telemetry.session_id()
    if not S.get("module") and st.query_params.get("module") in MODULES:
        S.module = st.query_params["module"]
    if "_goto" in S:
        S.step = S.pop("_goto")
    if "_pending_open" in S:
        p, out = S.pop("_pending_open")
        restore(p, out)
    qp = st.query_params
    tok = _session_token()
    if store.enabled() and "project" in qp and ("key" in qp or tok) and \
            S.get("project", {}).get("id") != qp["project"] and not S.get("_resume_failed"):
        p = {"id": qp["project"], "key": qp.get("key") or store.account_key(tok)}
        if "key" not in qp:
            try:
                p["role"] = store.my_role(tok, p["id"]) or "view"
            except Exception:
                p["role"] = "view"
        try:
            with st.spinner("Opening your saved project…"):
                restore(p, store.load(p, user))
        except Exception as e:
            S._resume_failed = True
            st.error(f"The saved project in this link could not be opened. {e}")
    collect_jobs()
    if not S.get("module"):
        with st.sidebar:
            st.markdown(f"### IgneoSuite\n<span style='color:#52514e'>{APP_META['tagline']}</span>",
                        unsafe_allow_html=True)
            if app is not None:
                st.divider()
                from octa_auth import sidebar as account_box
                account_box(app)
            _sidebar_footer()
        page_modules()
        return
    if st.query_params.get("module") != S.module:
        st.query_params["module"] = S.module
    with st.sidebar:
        st.markdown(f"### IgneoSuite\n<span style='color:#52514e'>{APP_META['tagline']}</span>", unsafe_allow_html=True)
        a, b = st.columns([3, 2], vertical_alignment="center")
        a.markdown(f"<span style='font-size:.85rem;color:#52514e'>Module</span><br><b>{MODULES[S.module]}</b>",
                   unsafe_allow_html=True)
        if b.button("Change", key="mod_change", use_container_width=True):
            S.module = None
            if "module" in st.query_params:
                del st.query_params["module"]
            st.rerun()
        is_admin = bool(user) and isinstance(user, dict) and user.get("role") == "admin"
        steps_now = STEPS if S.module == "fill" else EX_STEPS
        options = steps_now + ([ADMIN_STEP] if is_admin else [])
        if S.get("step") not in options:
            S.step = steps_now[0]
        step = st.radio("Steps", options, key="step", label_visibility="collapsed")
        if "X" in S:
            st.caption(f"{len(S.X):,} samples · {S.X.shape[1]} variables")
        if "project" in S:
            st.caption(f"💾 Project: {S.get('project_meta', {}).get('title', '')}")
        if running():
            st.caption("⏳ A test is running (step 3).")
        if app is not None:
            st.divider()
            from octa_auth import sidebar as account_box
            account_box(app)
        _sidebar_footer()
    if S.get("resumed"):
        st.success(f"Welcome back. The saved project **{S.pop('resumed')}** is open, with the results of every "
                   "saved step. You are at the last step you saved.")
    pages = PAGES if S.module == "fill" else EX_PAGES
    (page_admin if step == ADMIN_STEP else pages[step])()
