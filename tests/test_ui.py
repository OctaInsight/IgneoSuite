"""Headless run through every page with Streamlit's AppTest."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
from streamlit.testing.v1 import AppTest
from make_demo import demo
from igneosuite.io import clean_table, guess_columns


def test_pages():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=300).run()
    assert not at.exception
    import numpy as np, pandas as pd
    raw = demo(); i, v = guess_columns(raw); X, ids, rep = clean_table(raw, i, v)
    at.session_state["raw"] = raw
    at.session_state["meta"] = pd.DataFrame({"latitude": raw.Latitude.astype(float).clip(-90, 90).values,
                                             "longitude": raw.Longitude.astype(float).values,
                                             "age_ma": raw["Age (Ma)"].astype(float).values,
                                             "latitude_original": raw.Latitude.astype(str).values,
                                             "longitude_original": raw.Longitude.astype(str).values})
    at.session_state["meta_cols"] = {"latitude": "Latitude", "longitude": "Longitude", "age_ma": "Age (Ma)"}
    at.session_state["X"], at.session_state["ids"], at.session_state["report"] = X, ids, rep
    at.session_state["id_col"], at.session_state["value_cols"] = i, v
    for step in ["2 · Missing values", "3 · Test methods"]:
        at.sidebar.radio[0].set_value(step).run(); assert not at.exception, step
    at.multiselect[0].set_value(["Median", "KNN"]); at.number_input[0].set_value(1)
    at.button(key="run_scat").click().run(); assert not at.exception
    import time
    for _ in range(60):                      # the test runs in a background thread
        time.sleep(1); at.run()
        if "val_scat" in at.session_state:
            break
    assert not at.exception and "val_scat" in at.session_state and at.session_state["recommended"] == "KNN"
    assert not at.button(key="run_block").disabled
    at.button(key="run_block").click().run(); assert not at.exception
    for _ in range(60):
        time.sleep(1); at.run()
        if "val_block" in at.session_state:
            break
    assert "val_block" in at.session_state and not at.session_state["val_block"].empty
    assert any("ready to go to" in s.value for s in at.success)
    at.sidebar.radio[0].set_value("4 · Fill and export").run(); assert not at.exception
    at.button[0].click().run(); assert not at.exception and "est" in at.session_state
    at.sidebar.radio[0].set_value("5 · Clusters").run(); assert not at.exception
    at.button[1].click().run(); assert not at.exception and "clu" in at.session_state
    at.sidebar.radio[0].set_value("6 · Submit to database").run(); assert not at.exception
    at.sidebar.radio[0].set_value("About").run(); assert not at.exception
