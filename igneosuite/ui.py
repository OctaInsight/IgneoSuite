"""Streamlit interface. `render(user=None)` draws the whole app so a future portal can embed it."""
from __future__ import annotations
import numpy as np
import pandas as pd
import streamlit as st

from . import __version__
from .io import read_table, clean_table, guess_columns, guess_meta, read_meta, REE, short_name
from . import submit as submit_mod
from . import diagnose, validate, errors, export, cluster, plots, telemetry, jobs, store, geometry
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


def location_map(key: str):
    """Interactive map of the samples, drawn without WebGL or online tiles so it shows in every browser."""
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
    for sel, name, colour in ((~has_age, "Without age", plots.CAT[1]), (has_age, "With age", plots.CAT[0])):
        if sel.any():
            fig.add_trace(go.Scatter(
                x=d.lon[sel], y=d.lat[sel], mode="markers", name=f"{name} ({int(sel.sum())})",
                marker=dict(size=6, color=colour, opacity=0.85, line=dict(width=0.4, color="#0b0b0b")),
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
               "Hover over a point to see the sample, its coordinates and its age.")
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


def page_load():
    from .location import check_locations, read_age
    from .template import build as build_template
    st.header("Load data")
    st.write("Upload a table with one sample per row. Every sample needs a sample ID, latitude and longitude; "
             "age is optional but recommended. None of these are used in calculations.")
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
                if k not in ("step", "_user", "_sid"):
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
        _img(plots.missing_bar(pv))
        st.dataframe(_fmt(pv.set_index("Variable"), 2), width='stretch')
    with t2:
        _img(plots.missing_matrix(X))
        cc = diagnose.completeness_curve(X)
        st.caption("Complete samples as variables are added from most to least complete")
        st.dataframe(_fmt(cc.set_index("n_variables"), 1), width='stretch', height=250)
    with t3:
        phi = diagnose.co_missing_phi(X)
        if phi.empty:
            st.write("Too few variables with missing values.")
        else:
            _img(plots.phi_heatmap(phi), "High φ: the two variables tend to be missing in the same samples.")
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
    job = jobs.start(_job_key(kind), validate.run, M.copy(), cols, list(methods), scenario, frac,
                     block_cols=bidx, reps=int(reps), seed0=int(seed))
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
        _img(plots.method_bars(tb))
        _img(plots.per_variable_errors(res["pervar"], list(tb.index)))
        m = st.selectbox("Measured vs estimated for", list(tb.index), key=key + "_m")
        _img(plots.true_vs_est(res["sample"], m), half=True)
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
        _img(plots.k_scan(S.kscan)); st.dataframe(_fmt(S.kscan, 3))
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
        P, ev = c["P"], c["ev"]
        cc = st.columns(2)
        with cc[0]:
            _img(plots.pca_scatter(P, ev, c["lr"], "Reference clusters"))
        with cc[1]:
            _img(plots.pca_scatter(P, ev, c["lf"], "Gap-filled clusters"), "Both on the reference PCA axes")
        out = pd.DataFrame({S.id_col: np.asarray(S.ids)[c["rows"]], "Reference cluster": c["lr"], "Gap-filled cluster": c["lf"]})
        st.download_button("Download cluster labels (CSV)", out.to_csv(index=False).encode(), "igneosuite_clusters.csv", "text/csv")
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
        st.image(plots.to_png(plots.scree(ev)), width='stretch', caption="Variance explained by each component")
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
        st.image(plots.to_png(plots.pc_scores(np.asarray(g["scores"]), ev, **kw)), width='stretch',
                 caption="Samples on the first two principal components")
    _img(plots.loadings(np.asarray(g["loadings"]), g["variables"], ev),
         "Loadings: how strongly each element defines PC1 and PC2. Elements with long bars of the same sign rise and fall together.")
    save_bar("geometry")


# ---------------------------------------------------------------- 7 save
def page_save():
    _need("X", "Load data first (step 1).")
    st.header("Save & share")
    if not store.enabled():
        st.info("The database connection is not set up for this installation.")
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
        consent = st.checkbox("I have the right to store these data, and I agree that Octa Insight keeps them in the "
                              "IgneoSuite database under the licence chosen above. *", value=bool(pm.get("consent")))
        go = st.form_submit_button("Save everything", type="primary")
    if go:
        if len(title.strip()) < 3 or not consent:
            st.error("Please give the dataset a name (at least 3 characters) and tick the consent box.")
        elif share and S.get("location_check") == "some_wrong":
            st.error("You said some sample locations are wrong. Correct them before sharing the dataset.")
        else:
            S.project_meta = dict(title=title.strip(), reference=ref.strip() or None, description=desc.strip() or None,
                                  author_name=name.strip() or None, author_email=email.strip() or None,
                                  affiliation=aff.strip() or None, licence=lic, shared=share, consent=True)
            do_save(["load", "missing", "test", "fill", "geometry", "clusters"], meta_changed=True)
    project_info()


# ---------------------------------------------------------------- saving and reopening
STEP_PAGES = {"load": 0, "missing": 1, "test_scattered": 2, "test_block": 2, "fill": 3, "geometry": 4, "clusters": 5}
STEP_LABEL = {"load": "step 1", "missing": "step 2", "test": "step 3", "fill": "step 4", "geometry": "step 5",
              "clusters": "step 6"}


def _changed(step):
    S.setdefault("changed", {})[step] = time.time()


def _available(step) -> bool:
    return {"load": "X" in S, "missing": "X" in S, "test": bool(S.get("val_scat")), "fill": "est" in S,
            "geometry": "geo" in S, "clusters": "clu" in S or "kscan" in S}[step]


def _rows_for_samples():
    cols = list(S.X.columns)
    rows = submit_mod.sample_rows("x", S.ids, cols, S.X.values.astype(float), S.meta,
                                  S.get("est"), S.get("E"))
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
                saved[step] = time.time()
            if "test" in todo and not S.get("val_block"):
                store.delete_step(p, "test_block", user)
            box.update(label="Saved.", state="complete", expanded=False)
        except Exception as e:
            box.update(label="Saving failed.", state="error", expanded=True)
            st.error(str(e))
            return False
    st.query_params.update({"project": p["id"], "key": p["key"]})
    telemetry.event("save", {"steps": todo, "new": new}, user)
    st.toast("Saved ✅")
    return True


def project_info():
    if "project" not in S:
        return
    p = S.project
    st.success(f"Saved project: **{S.get('project_meta', {}).get('title', '')}**")
    st.markdown("To continue later, keep this page's address (it now contains your project), or note your "
                "**project code**. Anyone with the code can open the project, so keep it private.")
    st.code(store.project_code(p), language=None)


def save_bar(step):
    """Save button at the bottom of a step."""
    st.divider()
    if not store.enabled():
        st.caption("Saving is not set up for this installation.")
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
            consent = st.checkbox("I have the right to store these data, and I agree that Octa Insight keeps them in "
                                  "the IgneoSuite database. *", key=f"c_{step}")
            go = st.form_submit_button(f"Save {STEP_LABEL[step]}", type="primary")
        if go:
            if len(title.strip()) < 3 or not consent:
                st.error("Please give the dataset a name (at least 3 characters) and tick the consent box.")
                return
            S.project_meta = dict(title=title.strip(), reference=ref.strip() or None, consent=True, licence="CC-BY-4.0")
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


def open_project_box():
    if not store.enabled():
        return
    with st.expander("📂 Open a saved project"):
        code = st.text_input("Project code", placeholder="paste the code you got when you saved", key="open_code")
        if st.button("Open", key="open_btn"):
            p = store.parse_code(code)
            if not p:
                st.error("That does not look like a project code.")
            else:
                open_project(p)


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
        if k not in ("_user", "_sid"):
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
                                            "affiliation", "licence", "shared", "consent")}
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
    S.saved = saved
    S.changed = {}
    last = d.get("last_step")
    S.step = STEPS[STEP_PAGES.get(last, 0)]
    S.resumed = d.get("title")
    st.query_params.update({"project": p["id"], "key": p["key"]})


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

**Reference.** Abu-Alam, T.S., Güzey, A., Khalil, T.T., Abu-Anber, M., Said, A., Abu-Alam, N.T., Ghoneim, M.
When simpler wins: recovering the structure of incomplete geochemical data. *Computers & Geosciences* (submitted).

**Privacy.** Your data are stored only when you press a Save button, with your consent and under the licence you
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


PAGES = dict(zip(STEPS, [page_load, page_diagnose, page_validate, page_fill, page_geometry, page_cluster, page_save,
                         page_about]))


def render(user=None):
    """Draw the app. `user` is reserved for the Octa Insight portal (None = open use).

    A portal passes an object with `.id` (Supabase auth user id) and `.access_token`; usage rows are then
    stored under that user. With `user=None` rows are anonymous.
    """
    S["_user"] = user
    telemetry.session_id()
    if "_pending_open" in S:
        p, out = S.pop("_pending_open")
        restore(p, out)
    qp = st.query_params
    if store.enabled() and "project" in qp and "key" in qp and S.get("project", {}).get("id") != qp["project"]             and not S.get("_resume_failed"):
        p = {"id": qp["project"], "key": qp["key"]}
        try:
            with st.spinner("Opening your saved project…"):
                restore(p, store.load(p, user))
        except Exception as e:
            S._resume_failed = True
            st.error(f"The saved project in this link could not be opened. {e}")
    collect_jobs()
    with st.sidebar:
        st.markdown(f"### IgneoSuite\n<span style='color:#52514e'>{APP_META['tagline']}</span>", unsafe_allow_html=True)
        step = st.radio("Steps", STEPS, key="step", label_visibility="collapsed")
        if "X" in S:
            st.caption(f"{len(S.X):,} samples · {S.X.shape[1]} variables")
        if "project" in S:
            st.caption(f"💾 Project: {S.get('project_meta', {}).get('title', '')}")
        if running():
            st.caption("⏳ A test is running (step 3).")
        st.caption(f"v{__version__} · Octa Insight")
    if S.get("resumed"):
        st.success(f"Welcome back. The saved project **{S.pop('resumed')}** is open, with the results of every "
                   "saved step. You are at the last step you saved.")
    PAGES[step]()
