"""Emails sent from the app through Gmail (SMTP with an app password).

Streamlit secrets:

    [email]
    user = "octainsight@gmail.com"
    app_password = "abcd efgh ijkl mnop"   # Google account → Security → App passwords
    from_name = "Octa Insight"
"""
from __future__ import annotations
import html
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import streamlit as st


def enabled() -> bool:
    try:
        c = st.secrets["email"]
        return bool(c.get("user") and c.get("app_password"))
    except Exception:
        return False


def send(to: str, subject: str, paragraphs: list[str], button: tuple[str, str] | None = None,
         after: list[str] | None = None):
    """Send a plain + HTML email. `button` = (label, url)."""
    c = st.secrets["email"]
    sender, name = c["user"], c.get("from_name", "Octa Insight")
    host, port = c.get("host", "smtp.gmail.com"), int(c.get("port", 465))
    after = after or []
    text = "\n\n".join(paragraphs + ([f"{button[0]}: {button[1]}"] if button else []) + after)
    text += "\n\n— Octa Insight"
    p = lambda s: f"<p style='margin:0 0 14px 0'>{s}</p>"  # noqa: E731
    btn = ""
    if button:
        btn = (f"<p style='margin:20px 0'><a href='{html.escape(button[1], quote=True)}' "
               "style='background:#2a78d6;color:#ffffff;text-decoration:none;padding:10px 18px;border-radius:6px;"
               f"font-weight:600'>{html.escape(button[0])}</a></p>"
               f"<p style='font-size:12px;color:#6b6a66;margin:0 0 14px 0'>Or copy this link: "
               f"{html.escape(button[1])}</p>")
    body = ("<div style='font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#0b0b0b;max-width:560px'>"
            + "".join(p(s) for s in paragraphs) + btn + "".join(p(s) for s in after)
            + "<p style='color:#52514e;margin-top:24px'>— Octa Insight</p></div>")
    msg = EmailMessage()
    msg["From"] = formataddr((name, sender))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=25) as s:
            s.login(sender, c["app_password"].replace(" ", ""))
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=25) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(sender, c["app_password"].replace(" ", ""))
            s.send_message(msg)
