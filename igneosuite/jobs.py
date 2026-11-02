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


@st.cache_resource
def _registry() -> dict:
    return {}


def get(key: str) -> dict | None:
    return _registry().get(key)


def start(key: str, fn, *args, **kwargs) -> dict:
    """Run fn(*args, progress=..., **kwargs) in a thread. fn's return value becomes job['result']."""
    job = dict(status="running", progress=0.0, text="Starting", started=time.time(), finished=None,
               result=None, error=None, cancel=False)

    def progress(p, text=""):
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
