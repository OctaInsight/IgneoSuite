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
