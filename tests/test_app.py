import os, sys, numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
from make_demo import demo
from igneosuite.io import clean_table, guess_columns
from igneosuite import validate, errors, export
from igneosuite.imputers import impute, available_methods


def _data():
    raw = demo()
    i, v = guess_columns(raw)
    return clean_table(raw, i, v), i, v


def test_meta_and_submission_rows():
    from igneosuite.io import guess_meta, read_meta
    from igneosuite.submit import sample_rows
    raw = demo()
    g = guess_meta(raw)
    assert g == {"latitude": "Latitude", "longitude": "Longitude", "age_ma": "Age (Ma)"}
    meta, bad = read_meta(raw, g)
    assert bad["latitude"] == 1 and np.isnan(meta.latitude.iloc[2])
    i, v = guess_columns(raw)
    assert "Latitude" not in v and "Age (Ma)" not in v
    X, ids, _ = clean_table(raw, i, v)
    M = X.values; est = impute(M, "KNN"); E = np.where(np.isnan(M), 0.1 * est, np.nan)
    rows = sample_rows("d", ids, list(X.columns), M, meta, est, E)
    r = rows[0]
    assert r["row_number"] == 1 and r["sample_id"] == "S0000" and r["age_ma"] == meta.age_ma.iloc[0]
    assert set(r["measured"]).isdisjoint(r["estimated"]) and set(r["estimated"]) == set(r["estimate_error"])
    assert len(r["measured"]) + len(r["estimated"]) == len(X.columns)


def test_reading():
    (X, ids, rep), i, v = _data()
    assert i == "Sample" and len(v) == 22
    assert rep["counts"]["recovered"] >= 1 and X.iloc[5, 6] == 1234


def test_methods_keep_measured_and_fill():
    (X, _, _), _, _ = _data()
    M = X.values
    for m in available_methods():
        if m in ("DAE", "GAIN"):
            continue
        E = impute(M, m)
        assert np.allclose(E[~np.isnan(M)], M[~np.isnan(M)])
        assert not np.isnan(E).any()


def test_knn_beats_median_and_errors():
    (X, ids, _), i, v = _data()
    M = X.values; cols = list(X.columns)
    s = validate.run(M, cols, ["Median", "KNN"], "scattered", 0.05, reps=2)
    b = validate.run(M, cols, ["Median", "KNN"], "block", 0.1, list(range(8, 22)), reps=2)
    ts, tb = validate.score(s), validate.score(b)
    assert ts.index[0] == "KNN" and tb.index[0] == "KNN"
    est = impute(M, "KNN")
    F = errors.error_factors(s, b, "KNN", cols)
    E = errors.error_matrix(M, est, cols, F, list(range(8, 22)))
    assert np.isnan(E[~np.isnan(M)]).all() and (E[np.isnan(M)] > 0).all()
    three = export.three_column(ids, i, cols, M, est, E)
    assert three.shape[1] == 1 + 3 * len(cols)
    assert len(export.to_excel({"a": three}, ["n"])) > 1000
