"""Streamlit interface. `render(user=None)` draws the whole app so a future portal can embed it."""
from __future__ import annotations
import numpy as np
import pandas as pd
import streamlit as st

from . import __version__
from .io import read_table, clean_table, guess_columns, guess_meta, read_meta, REE, short_name
from . import submit as submit_mod
from . import diagnose, validate, errors, export, cluster, plots, telemetry
import time
from .imputers import METHODS, available_methods, impute, DEEP, HAS_TORCH

APP_META = dict(id="igneosuite", name="IgneoSuite", tagline="Gap-filling for incomplete igneous geochemistry",
                version=__version__)
STEPS = ["1 · Load data", "2 · Missing values", "3 · Test methods", "4 · Fill and export", "5 · Clusters",
         "6 · Submit to database", "About"]
S = st.session_state


def _user():
    return S.get("_user")


def _img(fig, caption=None):
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


def location_map(key: str):
    """Map of the samples with a question on whether the locations are correct."""
    import pydeck as pdk
    from .location import map_view
    m = S.meta
    d = pd.DataFrame({"sample": [str(x) for x in S.ids], "lat": m.latitude.values, "lon": m.longitude.values,
                      "age": [("%.0f Ma" % a) if np.isfinite(a) else "no age" for a in m.age_ma.values]})
    layer = pdk.Layer("ScatterplotLayer", d, get_position=["lon", "lat"], get_fill_color=[42, 120, 214, 190],
                      get_line_color=[11, 11, 11, 200], line_width_min_pixels=0.5, stroked=True,
                      get_radius=300, radius_min_pixels=3, radius_max_pixels=7, pickable=True)
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=pdk.ViewState(**map_view(d.lat.values, d.lon.values)),
                             map_style="light", tooltip={"text": "{sample}\n{lat}, {lon}\n{age}"}),
                    height=420)
    st.caption(f"{len(d)} samples. Hover over a point to see the sample, its coordinates and its age.")
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
    st.download_button("Download the Excel template", build_template(), "IgneoSuite_template.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       on_click=telemetry.event, args=("template", {}, _user()),
                       help="Fill in the sheet 'Data' and upload it here. The sheet 'Instructions' explains the formats.")
    up = st.file_uploader("CSV or Excel file", type=["csv", "txt", "xlsx", "xlsm", "xls"])
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
    taken = {id_col, *[v for v in meta_cols.values() if v]}
    choices = [c for c in cols if c not in taken]
    default = [c for c in S.get("value_cols", val_guess) if c in choices]
    value_cols = st.multiselect("Variables (concentrations)", choices, default=default, key="vars_" + fk)
    drop_bad = False
    if "loc_problems" in S and len(S.loc_problems):
        drop_bad = st.checkbox(f"Remove the {len(S.loc_problems)} samples with location problems and continue",
                               key="drop_" + fk)
    if st.button("Read values", type="primary", disabled=not value_cols):
        for k in ("X", "val_scat", "val_block", "est", "E", "clu", "location_check", "location_comment", "submitted_id"):
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
        S.meta = pd.DataFrame({"latitude": loc["latitude"][keep], "longitude": loc["longitude"][keep], "age_ma": age,
                               "latitude_original": sub[meta_cols["latitude"]].astype(str).str.slice(0, 60).values,
                               "longitude_original": sub[meta_cols["longitude"]].astype(str).str.slice(0, 60).values})
        rep.update(n_removed=int((~keep).sum()), n_converted=loc["n_converted"], age_rejected=age_bad,
                   precision_note=loc["precision_note"])
        S.update(X=X, ids=ids, report=rep, id_col=id_col, value_cols=value_cols, meta_cols=meta_cols)
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
        st.dataframe(pd.concat([pd.Series(S.ids, name=S.id_col),
                                S.meta[["latitude", "longitude", "age_ma"]].rename(
                                    columns={"latitude": "Latitude", "longitude": "Longitude", "age_ma": "Age (Ma)"}),
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


# ---------------------------------------------------------------- 3 validate
def page_validate():
    _need("X", "Load data first (step 1).")
    X = S.X; M = X.values.astype(float); cols = list(X.columns)
    st.header("Test the methods on your data")
    st.write("Measured values are hidden, estimated, and compared with the true values. "
             "Error is |log10(estimate / true)|, summarised as the median over variables of each variable's median error: 0.1 means a typical estimate is within a factor of 1.26.")
    avail = available_methods()
    default = [m for m in ["Median", "KNN", "MICE"] if m in avail]
    methods = st.multiselect("Methods", avail, default=S.get("methods", default),
                             help="\n".join(f"{m}: {METHODS[m][1]}" for m in avail))
    if not HAS_TORCH:
        st.caption("DAE and GAIN need PyTorch (`pip install torch`).")
    if any(m in DEEP for m in methods) or "missForest" in methods:
        st.caption("missForest, DAE and GAIN take from seconds to several minutes per run on a few thousand samples.")
    c = st.columns(3)
    reps = c[0].number_input("Repetitions", 1, 10, S.get("reps", 3))
    frac = c[1].slider("Scattered test: share of measured values hidden (%)", 1, 20, 5) / 100
    seed = c[2].number_input("Random seed", 0, 10_000, 0)
    ree_default = [x for x in cols if short_name(x) in REE]
    block = st.multiselect("Block test: variables hidden together", cols, default=S.get("block_names", ree_default),
                           help="Default is the REE. The block is hidden in samples that have all of it.")
    bfrac = st.slider("Block test: share of eligible samples (%)", 2, 30, 10) / 100
    if st.button("Run tests", type="primary", disabled=not methods):
        S.methods, S.reps, S.block_names = methods, reps, block
        bar = st.progress(0.0, "Starting"); t0 = time.time()
        S.val_scat = validate.run(M, cols, methods, "scattered", frac, reps=reps, seed0=seed,
                                  progress=lambda p, t: bar.progress(p * (0.5 if block else 1), "Scattered test: " + t))
        bidx = [cols.index(b) for b in block]
        S.val_block = (validate.run(M, cols, methods, "block", bfrac, bidx, reps, seed,
                                    progress=lambda p, t: bar.progress(0.5 + 0.5 * p, "Block test: " + t))
                       if block else pd.DataFrame())
        bar.empty()
        for k in ("est", "E"):
            S.pop(k, None)
        sm = diagnose.summary(X)
        sc = {"scattered": validate.score(S.val_scat).round(4).to_dict(orient="index")}
        if not S.val_block.empty:
            sc["block"] = validate.score(S.val_block).round(4).to_dict(orient="index")
        telemetry.run(dict(n_samples=sm["n_samples"], n_variables=sm["n_variables"],
                           pct_missing=round(sm["pct_missing"], 2), n_complete=sm["n_complete"],
                           methods=methods, repetitions=int(reps), scattered_frac=frac,
                           block_frac=bfrac if block else None, block_variables=[short_name(b) for b in block],
                           recommended_method=validate.recommend(validate.score(S.val_scat))[0],
                           scores=sc, duration_s=round(time.time() - t0, 1)), _user())
    if "val_scat" not in S:
        return
    tabs = st.tabs(["Scattered gaps", "Block gaps"])
    for tab, key in zip(tabs, ["val_scat", "val_block"]):
        with tab:
            long = S[key]
            if long.empty:
                st.write("Not run (no block variables chosen, or no sample has the whole block measured).")
                continue
            tb = validate.score(long)
            st.dataframe(_fmt(tb, 3), width='stretch')
            _img(plots.method_bars(tb))
            _img(plots.per_variable_errors(long, list(tb.index)))
            m = st.selectbox("Measured vs estimated for", list(tb.index), key=key + "_m")
            _img(plots.true_vs_est(long, m))
    rec_s, why_s = validate.recommend(validate.score(S.val_scat))
    msg = f"**Recommended method: {rec_s}.** {why_s}"
    if not S.val_block.empty:
        rec_b, _ = validate.recommend(validate.score(S.val_block))
        if rec_b != rec_s:
            msg += f" For the block test, {rec_b} did best; weigh the two by how your data are missing (step 2)."
    S.recommended = rec_s
    st.success(msg)


# ---------------------------------------------------------------- 4 impute + export
def page_fill():
    _need("X", "Load data first (step 1).")
    X = S.X; M = X.values.astype(float); cols = list(X.columns)
    st.header("Fill the gaps and export")
    if "val_scat" not in S:
        st.warning("Run the tests in step 3 first. They provide the error for every estimate.")
        st.stop()
    tested = list(S.val_scat.method.unique())
    rec = S.get("recommended", tested[0])
    method = st.selectbox("Method", tested, index=tested.index(rec) if rec in tested else 0)
    q = st.select_slider("Error band", options=[0.68, 0.90, 0.95], value=0.68,
                         format_func=lambda v: f"{int(v*100)}% of test errors")
    if st.button("Estimate missing values", type="primary"):
        with st.spinner(f"Running {method}"):
            est = impute(M, method, seed=0)
        bidx = [cols.index(b) for b in S.get("block_names", [])]
        F = errors.error_factors(S.val_scat, S.val_block, method, cols, q)
        E = errors.error_matrix(M, est, cols, F, bidx)
        S.update(est=est, E=E, F=F, fill_method=method, q=q)
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
    summary_s = validate.score(S.val_scat)
    sheets = {"Measured_estimated_error": three, "Complete_matrix": comp,
              "Error_by_variable": fac, "Test_scattered": summary_s}
    if not S.val_block.empty:
        sheets["Test_block"] = validate.score(S.val_block)
    c = st.columns(2)
    c[0].download_button("Download Excel workbook", export.to_excel(sheets, notes), "igneosuite_results.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary",
                         on_click=telemetry.event, args=("export", {"format": "xlsx"}, _user()))
    c[1].download_button("Download complete matrix (CSV)", comp.to_csv(index=False).encode(), "igneosuite_complete.csv", "text/csv",
                         on_click=telemetry.event, args=("export", {"format": "csv"}, _user()))


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
    if "kscan" in S:
        _img(plots.k_scan(S.kscan)); st.dataframe(_fmt(S.kscan, 3))
    if st.button("Run comparison", type="primary", disabled=len(base) < 2 or len(extra) < 2):
        bi = [cols.index(b) for b in base]; ei = [cols.index(e) for e in extra]
        rows = ~np.isnan(M[:, bi]).any(1)
        Zr = cluster.prepare(M[rows][:, bi])
        lr = cluster.kmeans(Zr, k)
        Zf = cluster.prepare(S.est[rows][:, ei])
        lf = cluster.match_labels(lr, cluster.kmeans(Zf, k))
        S.clu = dict(rows=rows, Zr=Zr, Zf=Zf, lr=lr, lf=lf, base=base, extra=extra)
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
        P, ev = cluster.pca(c["Zr"])
        cc = st.columns(2)
        with cc[0]:
            _img(plots.pca_scatter(P, ev, c["lr"], "Reference clusters"))
        with cc[1]:
            _img(plots.pca_scatter(P, ev, c["lf"], "Gap-filled clusters"), "Both on the reference PCA axes")
        out = pd.DataFrame({S.id_col: np.asarray(S.ids)[c["rows"]], "Reference cluster": c["lr"], "Gap-filled cluster": c["lf"]})
        st.download_button("Download cluster labels (CSV)", out.to_csv(index=False).encode(), "igneosuite_clusters.csv", "text/csv")


def page_submit():
    _need("X", "Load data first (step 1).")
    st.header("Submit your data to the IgneoSuite database")
    st.write("Share your analyses with the IgneoSuite compilation. Each sample is stored with its ID, location, "
             "age and measured values. If you filled the gaps in step 4, the estimates and their errors are "
             "stored too, kept separate from the measured values. Submissions are reviewed by Octa Insight "
             "before they are used.")
    if not telemetry.enabled():
        st.info("The database connection is not set up for this installation.")
        return
    X = S.X; M = X.values.astype(float); cols = list(X.columns)
    meta = S.meta
    c = st.columns(4)
    c[0].metric("Samples", len(X)); c[1].metric("Variables", len(cols))
    c[2].metric("With location", int((meta.latitude.notna() & meta.longitude.notna()).sum()))
    c[3].metric("With age", int(meta.age_ma.notna().sum()))
    if meta.age_ma.isna().all():
        st.info("No sample has an age. You can submit without ages, but dated samples are much more useful.")
    if S.get("location_check") not in LOC_ANSWERS:
        st.subheader("Check the locations")
        location_map("loc_answer_submit")
        if S.get("location_check") not in LOC_ANSWERS:
            st.info("Answer the question under the map before submitting.")
            return
    if S.get("location_check") == "some_wrong":
        st.warning("You said some sample locations are wrong. Please correct them in your file and upload it again "
                   "(step 1) before submitting.")
    if "submitted_id" in S:
        st.success(f"Submitted. Reference number: {S.submitted_id}. Keep it if you need to contact us about this dataset.")
    with st.form("submit_form"):
        a, b = st.columns(2)
        name = a.text_input("Author name *")
        email = b.text_input("Email *")
        aff = a.text_input("Affiliation")
        title = b.text_input("Dataset title *")
        ref = st.text_input("Publication or DOI the data come from")
        desc = st.text_area("Short description (area, rock types, analytical methods)", max_chars=4000)
        lic = st.selectbox("Licence", list(submit_mod.LICENCES), format_func=lambda k: submit_mod.LICENCES[k])
        inc = False
        if "est" in S:
            inc = st.checkbox(f"Include the {S.fill_method} estimates and their errors from step 4", value=True)
        consent = st.checkbox("I have the right to share these data, and I agree that Octa Insight stores them and "
                              "uses them under the licence chosen above. *")
        go = st.form_submit_button("Submit", type="primary")
    if go:
        problems = [m for ok, m in [(len(name.strip()) >= 2, "author name"), ("@" in email, "a valid email"),
                                    (len(title.strip()) >= 3, "dataset title"), (consent, "your consent")] if not ok]
        if S.get("location_check") == "some_wrong":
            problems.append("corrected locations (you said some are wrong: fix them in your file and upload it again)")
        if problems:
            st.error("Please add " + ", ".join(problems) + ".")
            return
        bar = st.progress(0.0, "Sending dataset")
        try:
            did = submit_mod.submit(dict(author_name=name, author_email=email, affiliation=aff, title=title,
                                         reference=ref, description=desc, licence=lic, consent=consent,
                                         location_check=S.get("location_check", "not_checked"),
                                         location_comment=S.get("location_comment") or None),
                                    S.ids, cols, M, meta,
                                    est=S.est if inc else None, E=S.E if inc else None,
                                    method=S.get("fill_method"), band=S.get("q"), user=_user(),
                                    progress=lambda p, t: bar.progress(p, "Sending samples: " + t))
        except Exception as e:
            bar.empty()
            st.error(f"Submission failed. {e}")
            return
        bar.empty()
        S.submitted_id = did
        telemetry.event("submit", {"n_samples": len(X)}, _user())
        st.rerun()


def page_about():
    st.header("About IgneoSuite")
    st.markdown(f"""
IgneoSuite {__version__} is open-source software from Octa Insight for working with incomplete igneous geochemical data.

**Workflow.** (1) Read the table and recover numbers hidden by stray spaces. (2) Describe where values are missing,
including elements that are reported together, such as the REE. (3) Hide measured values, estimate them with each method,
and score the errors, both for scattered gaps and for whole blocks. (4) Fill the gaps with the chosen method and export
every value as measured, estimated, or ± error. (5) Optionally compare clusters before and after gap-filling.

**Methods.** {"; ".join(f"*{m}*: {d}" for m, (_, d) in METHODS.items())}.
Model-based methods work on log10-transformed, standardised values.

**Reference.** Abu-Alam, T.S., Güzey, A., Khalil, T.T., Abu-Anber, M., Said, A., Abu-Alam, N.T., Ghoneim, M.
When simpler wins: recovering the structure of incomplete geochemical data. *Computers & Geosciences* (submitted).

**Privacy.** Your data are stored only if you submit them in step 6, with your consent and under the licence
you choose. Otherwise they stay in this session. To improve the software, IgneoSuite records anonymous usage
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


PAGES = dict(zip(STEPS, [page_load, page_diagnose, page_validate, page_fill, page_cluster, page_submit, page_about]))


def render(user=None):
    """Draw the app. `user` is reserved for the Octa Insight portal (None = open use).

    A portal passes an object with `.id` (Supabase auth user id) and `.access_token`; usage rows are then
    stored under that user. With `user=None` rows are anonymous.
    """
    S["_user"] = user
    telemetry.session_id()
    with st.sidebar:
        st.markdown(f"### IgneoSuite\n<span style='color:#52514e'>{APP_META['tagline']}</span>", unsafe_allow_html=True)
        step = st.radio("Steps", STEPS, key="step", label_visibility="collapsed")
        if "X" in S:
            st.caption(f"{len(S.X):,} samples · {S.X.shape[1]} variables")
        st.caption(f"v{__version__} · Octa Insight")
    PAGES[step]()
