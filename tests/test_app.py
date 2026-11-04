import pytest
import os, sys, numpy as np, pandas as pd
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


def _meta(raw, ids):
    from igneosuite.io import guess_meta
    from igneosuite.location import check_locations, read_age
    g = guess_meta(raw)
    loc = check_locations(ids, raw[g["latitude"]], raw[g["longitude"]])
    age, _ = read_age(raw[g["age_ma"]])
    return g, loc, pd.DataFrame({"latitude": loc["latitude"], "longitude": loc["longitude"], "age_ma": age,
                                 "latitude_original": raw[g["latitude"]].astype(str).values,
                                 "longitude_original": raw[g["longitude"]].astype(str).values})


def test_coordinates():
    from igneosuite.location import parse_coordinate as p
    assert p("25°27'24\"N", "latitude") == (25.456666666666667, "converted")
    assert p("25 27 24 S", "latitude")[0] < 0 and p("33.12W", "longitude")[0] == -33.12
    assert p("25,5", "latitude") == (25.5, "ok") and p(95, "latitude")[1] == "out_of_range"
    assert p("25.4 E", "latitude")[1] == "wrong_hemisphere" and p("abc", "longitude")[1] == "unreadable"
    assert p("25 70 00 N", "latitude")[1] == "unreadable" and p(None, "latitude")[1] == "missing"


def test_location_check_and_submission_rows():
    from igneosuite.submit import sample_rows
    raw = demo()
    i, v = guess_columns(raw)
    assert "Latitude" not in v and "Age (Ma)" not in v
    g, loc, meta = _meta(raw, raw[i].astype(str).values)
    assert g["latitude"] == "Latitude" and g["age_ma"] == "Age (Ma)" and g["reference"] is None
    assert len(loc["problems"]) == 1 and loc["problems"].Row.iloc[0] == 4 and not loc["valid"][2]
    assert not loc["swapped"]
    from igneosuite.location import check_locations
    sw = check_locations(["a", "b", "c"], pd.Series([120.5, 121.0, 119.8]), pd.Series([30.1, 31.2, 29.9]))
    assert sw["swapped"]
    X, ids, _ = clean_table(raw, i, v)
    M = X.values; est = impute(M, "KNN"); E = np.where(np.isnan(M), 0.1 * est, np.nan)
    rows = sample_rows("d", ids, list(X.columns), M, meta, est, E)
    r = rows[0]
    assert r["row_number"] == 1 and r["sample_id"] == "S0000" and r["age_ma"] == meta.age_ma.iloc[0]
    assert r["latitude_original"] == str(raw.Latitude.iloc[0])
    assert set(r["measured"]).isdisjoint(r["estimated"]) and set(r["estimated"]) == set(r["estimate_error"])
    assert len(r["measured"]) + len(r["estimated"]) == len(X.columns)


def test_template_reads_back():
    import io
    from igneosuite.template import build
    from igneosuite.io import guess_meta
    raw = pd.read_excel(io.BytesIO(build()), sheet_name="Data", dtype=object)
    i, v = guess_columns(raw)
    g = guess_meta(raw)
    assert i == "Sample ID" and g == {"latitude": "Latitude", "longitude": "Longitude", "age_ma": "Age (Ma)",
                                      "reference": "Reference", "comment": "Comment"}
    assert len(v) == 45
    from igneosuite.location import check_locations
    loc = check_locations(raw[i].values, raw.Latitude, raw.Longitude)
    assert loc["valid"].all() and loc["n_converted"] == 1


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
    s = validate.compact(validate.run(M, cols, ["Median", "KNN"], "scattered", 0.05, reps=2))
    b = validate.compact(validate.run(M, cols, ["Median", "KNN"], "block", 0.1, list(range(8, 22)), reps=2))
    assert s["score"].index[0] == "KNN" and b["score"].index[0] == "KNN"
    est = impute(M, "KNN")
    F = errors.error_factors(s, b, "KNN", cols)
    E = errors.error_matrix(M, est, cols, F, list(range(8, 22)))
    assert np.isnan(E[~np.isnan(M)]).all() and (E[np.isnan(M)] > 0).all()
    three = export.three_column(ids, i, cols, M, est, E)
    assert three.shape[1] == 1 + 3 * len(cols)
    assert len(export.to_excel({"a": three}, ["n"])) > 1000


def test_geometry():
    from igneosuite import geometry
    (X, ids, _), i, v = _data()
    est = impute(X.values, "KNN")
    refs = np.array(["A", "B", "C"])[np.arange(len(X)) % 3]
    g = geometry.analyse(geometry.prepare(est), refs=refs)
    m = g["metrics"]
    assert 1 <= m["pcs_80"] <= X.shape[1] and 0 < m["hopkins"] < 1 and m["twonn_dimension"] > 0
    assert abs(m["same_reference_chance"] - 1 / 3) < 0.01
    assert g["loadings"].shape == (X.shape[1], 3) and g["scores"].shape == (len(X), 3)


def test_full_table_ranges_and_clusters():
    import numpy as np, pandas as pd
    from igneosuite import export
    M = np.array([[50.0, np.nan], [np.nan, 2.0], [55.0, 3.0]])
    est = np.array([[50.0, 4.0], [52.0, 2.0], [55.0, 3.0]])
    f = 10 ** 0.1
    E = np.where(np.isnan(M), est * (f - 1 / f) / 2, np.nan)
    meta = pd.DataFrame({"latitude": [1.0, 2.0, 3.0], "longitude": [4.0, 5.0, 6.0], "age_ma": [10.0, None, 30.0],
                         "reference": ["A", None, "C"], "comment": [None, "x", None]})
    t = export.full_table(["s1", "s2", "s3"], "Sample", meta, ["SiO2", "Rb"], M, est, E,
                          np.array([1, None, 2], dtype=object), np.array([1, None, 1], dtype=object))
    assert list(t.columns[:8]) == ["Sample", "Latitude", "Longitude", "Age (Ma)", "Reference", "Comment",
                                   "Cluster before filling", "Cluster after filling"]
    assert t.loc[0, "Rb low (68%)"] == pytest.approx(4.0 / f) and t.loc[0, "Rb high (68%)"] == pytest.approx(4.0 * f)
    assert np.isnan(t.loc[0, "SiO2 estimated"]) and t.loc[1, "SiO2 estimated"] == 52.0
    assert pd.isna(t.loc[1, "Cluster before filling"]) and t.loc[2, "Cluster before filling"] == 2
    from igneosuite.submit import sample_rows
    rows = sample_rows("x", ["s1", "s2", "s3"], ["SiO2", "Rb"], M, meta.assign(latitude_original="", longitude_original=""),
                       est, E, np.array([1, None, 2], dtype=object), np.array([1, None, 1], dtype=object))
    assert rows[0]["estimate_range"]["Rb"] == pytest.approx([4.0 / f, 4.0 * f])
    assert rows[1]["cluster_reference"] is None and rows[2]["cluster_filled"] == 1
