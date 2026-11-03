"""Calls to the Octa user database (Supabase project Octa_projects, functions octa_user_*).

Only the publishable key is used. Passwords are checked inside the database; tokens are stored there as hashes.
Settings come from Streamlit secrets, section [octa_users] (falls back to [supabase] for url and key):

    [octa_users]
    url = "https://uxqeukvmnfvpgsxktgvo.supabase.co"
    key = "sb_publishable_..."
    server_key = "..."          # lets this app request password-reset links
    portal_url = "https://..."  # the common Octa suite page
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request

import streamlit as st


class OctaError(RuntimeError):
    pass


def _section(name):
    try:
        return st.secrets[name]
    except Exception:
        return {}


def setting(name, default=None):
    v = _section("octa_users").get(name)
    if v is None and name in ("url", "key"):
        v = _section("supabase").get(name)
    return v if v not in (None, "") else default


def enabled() -> bool:
    return bool(setting("url") and setting("key"))


def rpc(fn: str, timeout: int = 20, **args):
    url, key = setting("url"), setting("key")
    if not (url and key):
        raise OctaError("The Octa user database is not set up for this installation.")
    req = urllib.request.Request(f"{url.rstrip('/')}/rest/v1/rpc/{fn}", data=json.dumps(args).encode(), method="POST",
                                 headers={"apikey": key, "Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise OctaError(f"The user database answered with an error ({e.code}). {detail}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise OctaError(f"The user database could not be reached ({getattr(e, 'reason', e)}). Please try again.") from None
    return json.loads(body) if body else None


# thin wrappers -------------------------------------------------------------------------------------------
def login(login_name, password, app):
    return rpc("octa_user_login", p_login=login_name, p_password=password, p_app=app)


def register(fields: dict):
    return rpc("octa_user_register", p=fields)


def session(token, app):
    return rpc("octa_user_session", p_token=token, p_app=app)


def logout(token, app):
    return rpc("octa_user_logout", p_token=token, p_app=app)


def catalogue(token):
    return rpc("octa_user_catalogue", p_token=token)


def request_access(token, app):
    return rpc("octa_user_request_access", p_token=token, p_app=app)


def update_profile(token, fields: dict):
    return rpc("octa_user_update_profile", p_token=token, p=fields)


def change_password(token, old, new):
    return rpc("octa_user_change_password", p_token=token, p_old=old, p_new=new)


def reset_request(email, app):
    return rpc("octa_user_reset_request", p_server_key=setting("server_key", ""), p_email=email, p_app=app)


def reset_check(token):
    return rpc("octa_user_reset_check", p_token=token)


def reset_complete(token, password, username):
    return rpc("octa_user_reset_complete", p_token=token, p_new_password=password, p_new_username=username or "")


def admin(token, **payload):
    return rpc("octa_user_admin", p_token=token, p=payload)
