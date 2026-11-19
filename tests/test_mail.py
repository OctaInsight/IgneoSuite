"""Resend email sending in octa_auth.mail, with the HTTP call replaced (python -m pytest tests)."""
import os
import sys

import pytest

import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# A private copy of octa_auth/mail.py: other test helpers replace mail.send in the shared module, and this file must
# test the real function without changing what those tests use.
_spec = importlib.util.spec_from_file_location("octa_mail_under_test", os.path.join(ROOT, "octa_auth", "mail.py"))
mail = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mail)


class Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


@pytest.fixture
def secrets(monkeypatch):
    box = {}
    monkeypatch.setattr(mail, "_cfg", lambda: dict(box))
    return box


def test_resend_is_used_and_preferred(secrets, monkeypatch):
    secrets.update(resend_api_key="re_test", from_email="accounts@example.org", from_name="Octa Insight",
                   reply_to="help@example.org", user="x@gmail.com", app_password="p")
    seen = {}

    def post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return Resp(200, {"id": "msg_123"})

    monkeypatch.setattr(mail.requests, "post", post)
    assert mail.provider() == "resend"
    mid = mail.send("student@example.org", "Hi", ["Dear <b>you</b>,"], button=("Open", "https://x.org/?reset=abc"))
    assert mid == "msg_123"
    assert seen["url"] == mail.RESEND_URL
    assert seen["json"]["from"] == "Octa Insight <accounts@example.org>"
    assert seen["json"]["to"] == ["student@example.org"] and seen["json"]["reply_to"] == "help@example.org"
    assert "https://x.org/?reset=abc" in seen["json"]["text"] and "Choose" not in seen["json"]["text"]
    assert "href='https://x.org/?reset=abc'" in seen["json"]["html"]
    assert seen["headers"]["Authorization"] == "Bearer re_test" and seen["headers"]["Idempotency-Key"]


@pytest.mark.parametrize("code,words", [(401, "API key"), (403, "verified"), (422, "from_email"),
                                        (429, "daily Resend sending limit"), (500, "500")])
def test_resend_errors_are_readable(secrets, monkeypatch, code, words):
    secrets.update(resend_api_key="re_secret_value", from_email="a@example.org")
    monkeypatch.setattr(mail.requests, "post", lambda *a, **k: Resp(code, {"message": "x"}))
    with pytest.raises(mail.MailError) as e:
        mail.send("s@example.org", "Hi", ["x"])
    assert words in str(e.value) and "re_secret_value" not in str(e.value)


def test_unreachable_and_not_set_up(secrets, monkeypatch):
    secrets.update(resend_api_key="re_x", from_email="a@example.org")

    def boom(*a, **k):
        raise mail.requests.ConnectionError("down")

    monkeypatch.setattr(mail.requests, "post", boom)
    with pytest.raises(mail.MailError, match="Could not reach Resend"):
        mail.send("s@example.org", "Hi", ["x"])
    secrets.clear()
    assert mail.provider() is None and not mail.enabled()
    with pytest.raises(mail.MailError, match="not set up"):
        mail.send("s@example.org", "Hi", ["x"])


def test_gmail_only_as_fallback(secrets):
    secrets.update(user="x@gmail.com", app_password="p")
    assert mail.provider() == "gmail"
    secrets.update(resend_api_key="re_x")          # a key without a sender address is not enough
    assert mail.provider() == "gmail"


class FakeSecrets(dict):
    """Stands in for st.secrets: a mapping of sections and top-level values."""


@pytest.fixture
def raw_secrets(monkeypatch):
    box = FakeSecrets()
    monkeypatch.setattr(mail.st, "secrets", box)
    return box


def test_names_are_forgiving(raw_secrets):
    raw_secrets["email"] = {"RESEND_API_KEY": "re_x", "From_Email": " accounts@example.org "}
    assert mail.provider() == "resend" and mail.sender()["from_email"] == "accounts@example.org"
    raw_secrets.clear()
    raw_secrets.update(RESEND_API_KEY="re_x", RESEND_FROM_EMAIL="m@example.org")      # matchmaking style
    assert mail.provider() == "resend"


def test_diagnose_names_what_is_missing(raw_secrets):
    raw_secrets.update(octa_users={"url": "u"})
    assert "no [email] section" in mail.diagnose() and "octa_users" in mail.diagnose()
    raw_secrets["email"] = {"resend_api_key": "re_secret", "from_name": "Octa"}
    d = mail.diagnose()
    assert "missing from_email" in d and "resend_api_key" in d and "re_secret" not in d
    raw_secrets["email"]["from_email"] = "a@example.org"
    assert mail.diagnose() == "Resend is set up."
