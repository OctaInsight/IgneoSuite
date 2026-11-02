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
