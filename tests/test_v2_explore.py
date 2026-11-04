"""IgneoSuite 2: module choice, Plot-and-explore step 1 and step 2 (age groups), save and reopen."""
import json, os, sys, time, types
import numpy as np, pandas as pd, pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
from streamlit.testing.v1 import AppTest
from igneosuite import agegroups, store
from test_store import FakeDB


def test_grouping_logic():
    age = np.array([1.0, 50, 100, 300, 600, 2600, np.nan])
    t = agegroups.propose(age, "timescale", level="Era")
    assert list(t.Group) == ["Cenozoic", "Mesozoic", "Paleozoic", "Neoproterozoic", "Neoarchean"]
    lab = agegroups.assign(age, t)
    assert list(lab) == ["Cenozoic", "Cenozoic", "Mesozoic", "Paleozoic", "Neoproterozoic", "Neoarchean", "No age"]
    w = agegroups.propose(age, "width", width=1000)
    assert list(w["From (Ma)"]) == [0, 2000] and agegroups.assign(np.array([2600.0]), w)[0] == "2000–3000 Ma"
    c = agegroups.propose(age, "custom", custom="0, 100, 1000")
    assert list(agegroups.assign(age, c)) == ["0–100 Ma", "0–100 Ma", "100–1000 Ma", "100–1000 Ma", "100–1000 Ma",
                                              "Outside the groups", "No age"]
    q = agegroups.propose(age, "count", n_groups=3)
    assert len(q) == 3
    bad = pd.DataFrame([["A", 10, 5, "#123456"], ["A", 20, 30, "red"]], columns=agegroups.COLUMNS)
    cl, problems = agegroups.clean(bad)
    assert len(cl) == 1 and cl.Colour[0].startswith("#") and any("younger" in p for p in problems)


def _script():
    return '''
import streamlit as st, sys
sys.path.insert(0, %r)
from igneosuite import store, telemetry
import v2_fake_db
store._rpc = v2_fake_db.DB
store.enabled = lambda: True
telemetry.enabled = lambda: False
from igneosuite.ui import render
render()
''' % ROOT


def _data(with_age=True):
    from make_demo import demo
    from igneosuite.io import clean_table, guess_columns
    raw = demo(); i, v = guess_columns(raw); X, ids, rep = clean_table(raw, i, v)
    age = raw["Age (Ma)"].astype(float).values if with_age else np.full(len(raw), np.nan)
    meta = pd.DataFrame({"latitude": raw.Latitude.astype(float).clip(-90, 90).values,
                         "longitude": raw.Longitude.astype(float).values, "age_ma": age,
                         "latitude_original": raw.Latitude.astype(str).values,
                         "longitude_original": raw.Longitude.astype(str).values,
                         "reference": [None] * len(raw), "comment": [None] * len(raw)})
    return dict(raw=raw, X=X, ids=ids, report=rep, id_col=i, value_cols=v, meta=meta,
                meta_cols={"latitude": "Latitude", "longitude": "Longitude", "age_ma": "Age (Ma)" if with_age else None})


def _app(tmp_path, db, module=None):
    sys.modules["v2_fake_db"] = types.SimpleNamespace(DB=db)
    script = tmp_path / "app_v2.py"; script.write_text(_script())
    at = AppTest.from_file(str(script), default_timeout=300)
    if module is None:
        del at.query_params["module"]          # conftest starts in "fill"; here we want the choice page
    else:
        at.query_params["module"] = module
    return at


def test_module_choice_page(tmp_path):
    at = _app(tmp_path, FakeDB()).run()
    assert not at.exception, at.exception
    assert any("What would you like to do?" in h.value for h in at.header)
    at.button(key="mod_explore").click().run()
    assert at.session_state["module"] == "explore" and at.query_params["module"] == ["explore"] or \
        at.query_params["module"] == "explore"
    assert at.sidebar.radio[0].options[:3] == ["1 · Load data", "2 · Age groups", "3 · Plots and parameters"]
    assert any(r.label == "Which data do you want to explore?" for r in at.radio)


def test_explore_age_groups_save_and_reopen(tmp_path):
    db = FakeDB()
    at = _app(tmp_path, db, "explore").run()
    for k, v in _data().items():
        at.session_state[k] = v
    at.radio(key="ex_src").set_value("upload").run()
    assert not at.exception, at.exception
    # step 1: same map and location question as the gap-filling module
    assert any(s.value == "Sample locations" for s in at.subheader)
    assert any(r.label == "Are the sample locations correct?" for r in at.radio)
    at.text_input(key="t_load").set_value("Explore demo")
    next(b for b in at.button if b.label == "Save step 1").click().run()
    pid = at.session_state["project"]["id"]
    assert len(db.samples[pid]) == len(at.session_state["X"])
    at.button(key="ex_next1").click().run()
    assert at.session_state["step"] == "2 · Age groups"
    # step 2: statistics, default ICS periods, map coloured by group
    assert not at.exception, at.exception
    assert any(m.label == "Oldest" for m in at.metric)
    t0 = at.session_state["age_table"]
    assert len(t0) >= 1 and set(t0.columns) == set(agegroups.COLUMNS)
    at.selectbox(key="age_method").set_value("custom").run()
    at.text_input(key="age_custom").set_value("0, 500, 1000, 5000").run()
    at.button(key="age_make").click().run()
    assert list(at.session_state["age_table"].Group) == ["0–500 Ma", "500–1000 Ma", "1000–5000 Ma"]
    at.button(key="save_age_groups").click().run()
    assert not at.exception, at.exception
    assert "age_groups" in db.steps[pid]
    groups = [r.get("age_group") for r in db.samples[pid]]
    age = at.session_state["meta"].age_ma.values
    exp = agegroups.assign(age, at.session_state["age_table"])
    assert groups == [None if g == "No age" else g for g in exp]
    at.button(key="age_next").click().run()
    assert at.session_state["step"] == "3 · Plots and parameters"
    # reopen from the link in a new session: module and groups come back
    at2 = _app(tmp_path, db, None)
    at2.query_params["project"] = pid; at2.query_params["key"] = at.session_state["project"]["key"]
    at2.run()
    assert not at2.exception, at2.exception
    assert at2.session_state["module"] == "explore" and at2.session_state["step"] == "2 · Age groups"
    assert list(at2.session_state["age_table"].Group) == ["0–500 Ma", "500–1000 Ma", "1000–5000 Ma"]


def test_explore_without_age_skips_step2(tmp_path):
    at = _app(tmp_path, FakeDB(), "explore").run()
    for k, v in _data(with_age=False).items():
        at.session_state[k] = v
    at.radio(key="ex_src").set_value("upload").run()
    assert any("no ages" in i.value for i in at.info)
    at.button(key="ex_next1").click().run()
    assert at.session_state["step"] == "3 · Plots and parameters"
    assert not at.exception
