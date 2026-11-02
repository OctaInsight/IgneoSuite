import streamlit as st
st.set_page_config(page_title="IgneoSuite", page_icon="🪨", layout="wide")
from igneosuite.ui import render  # noqa: E402

render(user=None)
