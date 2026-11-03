import streamlit as st
st.set_page_config(page_title="IgneoSuite", page_icon="🪨", layout="wide")
from octa_auth import App, require_login, client  # noqa: E402
from igneosuite.ui import render, APP_META  # noqa: E402

APP = App(id="igneosuite", name="IgneoSuite", family="science", url="https://igneosuite.streamlit.app/",
          tagline=APP_META["tagline"], icon="🪨")

# Octa accounts (one login for all Octa Insight apps) are switched on by the [octa_users] section of the
# Streamlit secrets. Without it IgneoSuite runs openly, as before. With it, login is required unless
# [octa_users] login_required = false (then people can still log in from the sidebar).
accounts = bool(client._section("octa_users")) and client.enabled()
if accounts:
    required = str(client.setting("login_required", "true")).lower() not in ("false", "0", "no")
    user = require_login(APP, required=required)
    render(user=user, app=APP)
else:
    render(user=None)
