"""IgneoSuite 2 opens with a choice of module. The version-1 tests start straight in the gap-filling module."""
from streamlit.testing.v1 import AppTest

_from_file = AppTest.from_file.__func__


def _from_file_fill(cls, *args, **kwargs):
    at = _from_file(cls, *args, **kwargs)
    at.query_params["module"] = "fill"
    return at


AppTest.from_file = classmethod(_from_file_fill)
