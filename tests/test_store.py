"""Save a whole project to an in-memory stand-in for the database functions, reopen it, compare."""
import json, os, sys, time
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
from streamlit.testing.v1 import AppTest
from igneosuite import store


class FakeDB:
    """Mimics the igneosuite_* functions (JSON in, JSON out, key check)."""
    def __init__(self):
        self.d, self.samples, self.steps, self.keys = {}, {}, {}, {}

    def __call__(self, fn, payload, user=None, timeout=90):
        payload = json.loads(json.dumps(store.encode(payload)))      # what really travels
        pid, key = payload["p_id"], payload["p_key"]
        if fn != "igneosuite_save_dataset" or pid in self.d:
            assert self.keys.get(pid) == key, "wrong key"
        if fn == "igneosuite_save_dataset":
            self.keys.setdefault(pid, key)
            self.d.setdefault(pid, {"id": pid}).update(payload["p_meta"])
        elif fn == "igneosuite_save_samples":
            if payload["p_first"]:
                self.samples[pid] = []
            self.samples[pid] += payload["p_rows"]
        elif fn == "igneosuite_save_step":
            self.steps.setdefault(pid, {})[payload["p_step"]] = {"params": payload["p_params"],
                                                                 "results": payload["p_results"]}
            self.d[pid]["last_step"] = payload["p_step"]
        elif fn == "igneosuite_delete_step":
            self.steps.get(pid, {}).pop(payload["p_step"], None)
        elif fn == "igneosuite_load_dataset":
            return {"dataset": self.d[pid], "steps": self.steps.get(pid, {})}
        elif fn == "igneosuite_load_samples":
            return self.samples[pid][payload["p_offset"]: payload["p_offset"] + payload["p_limit"]]
        return None


def _app_script():
    return '''
import streamlit as st, sys
sys.path.insert(0, %r)
from igneosuite import store, telemetry
import tests_fake_db
store._rpc = tests_fake_db.DB
store.enabled = lambda: True
telemetry.enabled = lambda: False
from igneosuite.ui import render
render()
''' % ROOT


def test_save_and_reopen(tmp_path):
    import types
    db = FakeDB()
    sys.modules["tests_fake_db"] = types.SimpleNamespace(DB=db)
    script = tmp_path / "app_fake.py"; script.write_text(_app_script())
    from make_demo import demo
    from igneosuite.io import clean_table, guess_columns
    raw = demo(); i, v = guess_columns(raw); X, ids, rep = clean_table(raw, i, v)
    at = AppTest.from_file(str(script), default_timeout=300).run()
    meta = pd.DataFrame({"latitude": raw.Latitude.astype(float).clip(-90, 90).values,
                         "longitude": raw.Longitude.astype(float).values, "age_ma": raw["Age (Ma)"].astype(float).values,
                         "latitude_original": raw.Latitude.astype(str).values, "longitude_original": raw.Longitude.astype(str).values,
                         "reference": np.array(["Ref A", "Ref B", None], dtype=object)[np.arange(len(raw)) % 3],
                         "comment": [None] * len(raw)})
    for k, val in dict(raw=raw, X=X, ids=ids, report=rep, id_col=i, value_cols=v, meta=meta,
                       meta_cols={"latitude": "Latitude", "longitude": "Longitude", "age_ma": "Age (Ma)"}).items():
        at.session_state[k] = val
    # step 3: run test 1 and 2
    at.sidebar.radio[0].set_value("3 · Test methods").run()
    at.multiselect[0].set_value(["Median", "KNN"]); at.number_input[0].set_value(1)
    at.button(key="run_scat").click().run()
    for _ in range(60):
        time.sleep(1); at.run()
        if "val_scat" in at.session_state: break
    at.button(key="run_block").click().run()
    for _ in range(60):
        time.sleep(1); at.run()
        if "val_block" in at.session_state: break
    assert not at.exception
    # first save from step 3 creates the project
    at.text_input(key="t_test").set_value("Demo project")
    at.button[-1].click().run()
    assert not at.exception, at.exception
    pid = at.session_state["project"]["id"]
    assert len(db.samples[pid]) == len(X) and {"load", "test_scattered", "test_block"} <= set(db.steps[pid])
    # step 4: fill and save
    at.sidebar.radio[0].set_value("4 · Fill and export").run()
    at.button[0].click().run()
    at.button(key="save_fill").click().run()
    assert not at.exception and "fill" in db.steps[pid]
    assert sum(1 for r in db.samples[pid] if r.get("estimated")) > 0
    # step 5: geometry and save
    at.sidebar.radio[0].set_value("5 · Data geometry").run()
    at.button[0].click().run()
    assert "geo" in at.session_state
    at.button(key="save_geometry").click().run()
    assert "geometry" in db.steps[pid]
    score = at.session_state["val_scat"]["score"].copy()
    est = at.session_state["est"].copy()
    geo_m = dict(at.session_state["geo"]["metrics"])

    # a new browser session opens the project from its link
    at2 = AppTest.from_file(str(script), default_timeout=300)
    at2.query_params["project"] = pid; at2.query_params["key"] = at.session_state["project"]["key"]
    at2.run()
    assert not at2.exception, at2.exception
    s2 = at2.session_state
    assert s2["step"] == "5 · Data geometry"
    assert np.allclose(s2["X"].values, X.values, equal_nan=True)
    assert np.allclose(s2["est"], est, equal_nan=True)
    pd.testing.assert_frame_equal(s2["val_scat"]["score"], score, check_dtype=False, check_names=False)
    assert s2["val_block"]["score"].shape[0] == 2
    assert s2["geo"]["metrics"] == geo_m
    r3 = list(s2["meta"].reference[:3]); assert r3[:2] == ["Ref A", "Ref B"] and pd.isna(r3[2])
    for step in ["1 · Load data", "2 · Missing values", "3 · Test methods", "4 · Fill and export",
                 "5 · Data geometry", "7 · Save & share"]:
        at2.sidebar.radio[0].set_value(step).run(); assert not at2.exception, (step, at2.exception)
    # wrong key is refused
    at3 = AppTest.from_file(str(script), default_timeout=300)
    at3.query_params["project"] = pid; at3.query_params["key"] = "x" * 32
    at3.run()
    assert "X" not in at3.session_state and at3.error
