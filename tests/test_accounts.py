"""IgneoSuite with Octa accounts (in-memory user database)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

import pytest  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import fake_octa_db  # noqa: E402

SECRETS = {"octa_users": {"url": "https://example.supabase.co", "key": "sb_publishable_x",
                          "server_key": "test-server-key", "portal_url": "https://portal.example/"},
           "email": {"user": "a@b.c", "app_password": "x"}}


@pytest.fixture
def db():
    fake_octa_db.DB.__init__()
    return fake_octa_db.install()


def _at(qp=None, extra=None):
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=120)
    for k, v in SECRETS.items():
        at.secrets[k] = {**v, **(extra or {}).get(k, {})}
    for k, v in (qp or {}).items():
        at.query_params[k] = v
    return at.run()


def test_dedicated_login_then_app(db):
    db.add_user("ann@x.org", "ann", "Secret-123", first_name="Ann")
    at = _at()
    assert not at.exception
    assert any("IgneoSuite" in m.value for m in at.markdown)
    assert not at.sidebar.radio          # the app itself is not shown yet
    at.text_input[0].input("ann@x.org")
    at.text_input[1].input("Secret-123")
    next(b for b in at.button if b.label == "Log in").click().run()
    assert not at.exception, at.exception
    assert at.sidebar.radio              # steps are visible: inside the app
    labels = [b.label for b in at.sidebar.button]
    assert "Log out" in labels
    assert any(("igneosuite", "login") == (u[1], u[2]) for u in db.usage)


def test_register_in_igneosuite_is_science_profile(db):
    at = _at({"register": "1"})
    vals = {"First name *": "Bo", "Family name *": "Li", "Email *": "bo@x.org", "Username *": "boli",
            "Password *": "Secret-123", "Repeat password *": "Secret-123",
            "Affiliation (university, institute or company) *": "UiT", "Research field": "petrology"}
    for t in at.text_input:
        if t.label in vals:
            t.input(vals[t.label])
    next(b for b in at.button if b.label == "Create account").click().run()
    assert not at.exception, at.exception
    u = next(iter(db.users.values()))
    assert u["profiles"]["science"]["research_field"] == "petrology"
    assert at.sidebar.radio


def test_optional_login(db):
    at = _at(extra={"octa_users": {"login_required": "false"}})
    assert at.sidebar.radio
    assert "Log in" in [b.label for b in at.sidebar.button]


def test_step1_lists_my_and_shared_projects(db, monkeypatch):
    from igneosuite import store
    monkeypatch.setattr(store, "enabled", lambda: True)
    monkeypatch.setattr(store, "my_projects", lambda tok: [dict(id="a1", title="My basalts", n_samples=120,
                                                                last_step="fill", updated_at="2026-11-03T20:00")])
    monkeypatch.setattr(store, "shared_with_me", lambda tok: [dict(id="b2", title="Nour granites", n_samples=40,
                                                                   role="view", owner="Nour Abu-Alam",
                                                                   updated_at="2026-11-03T19:00")])
    uid = db.add_user("ann@x.org", "ann", "Secret-123", first_name="Ann")
    at = _at({"session": db._new_session(uid)})
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "My projects" in text and "Shared with me" in text
    assert "My basalts" in text and "Nour granites" in text and "view only" in text
    assert not any(t.label == "Project code" for t in at.text_input)


def test_share_emails(monkeypatch):
    import octa_auth.mail as m
    from igneosuite import ui
    sent = []
    monkeypatch.setattr(m, "enabled", lambda: True)
    monkeypatch.setattr(m, "send", lambda to, subject, paragraphs, button=None, after=None: sent.append((to, subject, button)))
    ui.S._share_msg = None
    ui._share_emails({"ok": True, "by": "Olga Owner", "project": "Share test", "added": [
        {"email": "v@x.org", "status": "user", "name": "Vera"},
        {"email": "new@x.org", "status": "invited"},
        {"person": "nonsense", "status": "unknown"}]}, "view")
    assert sent[0][0] == "v@x.org" and "shared" in sent[0][1]
    assert sent[1][0] == "new@x.org" and sent[1][2][1].endswith("?register=1")
    kind, msg = ui.S._share_msg
    assert kind == "warning" and "nonsense" in msg and "2 emails sent" in msg


def _loaded(at):
    import pandas as pd
    from make_demo import demo
    from igneosuite.io import clean_table, guess_columns
    raw = demo(); i, v = guess_columns(raw); X, ids, rep = clean_table(raw, i, v)
    at.session_state["raw"] = raw
    at.session_state["meta"] = pd.DataFrame({"latitude": raw.Latitude.astype(float).clip(-90, 90).values,
                                             "longitude": raw.Longitude.astype(float).values,
                                             "age_ma": raw["Age (Ma)"].astype(float).values})
    at.session_state["X"], at.session_state["ids"], at.session_state["report"] = X, ids, rep
    at.session_state["id_col"], at.session_state["value_cols"] = i, v


def _fake_store(monkeypatch, role):
    from igneosuite import store
    calls = {}
    monkeypatch.setattr(store, "enabled", lambda: True)
    monkeypatch.setattr(store, "my_role", lambda tok, pid: role)
    monkeypatch.setattr(store, "find_users", lambda tok, q: [dict(username="vera", name="Vera V", affiliation="UiT")])
    monkeypatch.setattr(store, "shares", lambda tok, pid: [dict(email="ed@x.org", role="edit", name="Ed", username="ed",
                                                                 registered=True)])
    def share(tok, pid, people, r):
        calls["share"] = (people, r)
        return {"ok": True, "by": "Ann", "project": "P", "added": [{"email": "v@x.org", "status": "user"}]}
    monkeypatch.setattr(store, "share", share)
    monkeypatch.setattr(store, "unshare", lambda tok, pid, e: calls.setdefault("unshare", e))
    return calls


def test_owner_shares_from_step7(db, monkeypatch):
    calls = _fake_store(monkeypatch, "owner")
    uid = db.add_user("ann@x.org", "ann", "Secret-123", first_name="Ann")
    at = _at({"session": db._new_session(uid)})
    _loaded(at)
    at.session_state["project"] = {"id": "p1", "key": "x" * 32}
    at.session_state["project_meta"] = {"title": "P"}
    at.sidebar.radio[0].set_value("7 · Save & share").run()
    assert not at.exception, at.exception
    assert any("Share this project" in h.value for h in at.subheader)
    at.text_input(key="share_q").input("vera")
    at.button(key="share_search").click().run()
    at.multiselect(key="share_pick").select("vera")
    at.text_area(key="share_emails").input("new@x.org")
    at.radio(key="share_role").set_value("edit")
    at.button(key="share_go").click().run()
    assert not at.exception, at.exception
    assert calls["share"] == (["vera", "new@x.org"], "edit")
    assert any("Shared with 1 person" in s.value for s in at.success)
    at.button(key="unshare_ed@x.org").click().run()
    assert calls["unshare"] == "ed@x.org"


def test_viewer_cannot_save(db, monkeypatch):
    _fake_store(monkeypatch, "view")
    uid = db.add_user("ann@x.org", "ann", "Secret-123", first_name="Ann")
    at = _at({"session": db._new_session(uid)})
    _loaded(at)
    at.session_state["project"] = {"id": "p1", "key": "session:abc", "role": "view", "owner": "Nour"}
    at.sidebar.radio[0].set_value("7 · Save & share").run()
    assert not at.exception, at.exception
    assert any("shared with you" in i.value for i in at.info)
    assert not any(b.label == "Save everything" for b in at.button)
