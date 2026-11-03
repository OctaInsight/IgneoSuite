"""Long calculations in background threads.

A Streamlit script run stops whenever the user clicks something, so long tests run in a thread
that outlives the page. The page only reads the job's progress. The job is linked to the browser
session: refreshing or closing the page starts a new session and the result is lost.
"""
from __future__ import annotations
import threading
import time
import traceback
import streamlit as st


class Cancelled(Exception):
    pass


class Busy(RuntimeError):
    pass


MAX_RUNNING = 2          # tests running at the same time on this server (all users together)
ORPHAN_SECONDS = 20 * 60  # a test nobody has looked at for this long (page closed or refreshed) is stopped


@st.cache_resource
def _registry() -> dict:
    return {}


def get(key: str) -> dict | None:
    j = _registry().get(key)
    if j is not None:
        j["seen"] = time.time()          # the page that owns the test is still open
    return j


def n_running() -> int:
    return sum(j["status"] == "running" for j in list(_registry().values()))


def start(key: str, fn, *args, **kwargs) -> dict:
    """Run fn(*args, progress=..., **kwargs) in a thread. fn's return value becomes job['result']."""
    reg = _registry()
    for k, j in list(reg.items()):      # forget finished tests whose page was closed
        if j["status"] != "running" and time.time() - j.get("seen", 0) > ORPHAN_SECONDS:
            reg.pop(k, None)
    if n_running() >= MAX_RUNNING:
        raise Busy("The server is already running other tests. Please try again in a few minutes.")
    job = dict(status="running", progress=0.0, text="Starting", started=time.time(), finished=None,
               result=None, error=None, cancel=False, seen=time.time())

    def progress(p, text=""):
        if time.time() - job["seen"] > ORPHAN_SECONDS:
            job["cancel"] = True          # nobody is waiting for this result any more
        if job["cancel"]:
            raise Cancelled()
        job["progress"] = float(min(max(p, 0.0), 1.0))
        job["text"] = text

    def target():
        try:
            job["result"] = fn(*args, progress=progress, **kwargs)
            job["status"] = "done" if not job["cancel"] else "cancelled"
        except Cancelled:
            job["status"] = "cancelled"
        except Exception as e:  # pragma: no cover
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"
            job["trace"] = traceback.format_exc()
        job["finished"] = time.time()

    _registry()[key] = job
    threading.Thread(target=target, daemon=True, name=f"igneosuite-{key}").start()
    return job


def pop(key: str) -> dict | None:
    return _registry().pop(key, None)


def cancel(key: str):
    j = get(key)
    if j:
        j["cancel"] = True
