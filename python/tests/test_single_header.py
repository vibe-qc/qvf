"""Drift guard: the committed cpp/qvf_single.hpp must match the amalgamator.

If a source header or qvf.cpp changes, the single-header amalgamation must be
regenerated (`python qvf-writer/scripts/amalgamate.py`). This test fails loudly
if they diverge, so the drop-in header never ships stale.
"""

import importlib.util
import os

import pytest

HERE = os.path.dirname(__file__)
_SCRIPT = os.path.normpath(os.path.join(HERE, "..", "..", "scripts", "amalgamate.py"))
_OUT = os.path.normpath(os.path.join(HERE, "..", "..", "cpp", "qvf_single.hpp"))


def _load_amalgamate():
    spec = importlib.util.spec_from_file_location("amalgamate", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_single_header_is_current():
    if not os.path.exists(_SCRIPT) or not os.path.exists(_OUT):
        pytest.skip("amalgamate.py / qvf_single.hpp not present (standalone checkout)")
    amalgamate = _load_amalgamate()
    expected = amalgamate.build()
    with open(_OUT, encoding="utf-8") as fh:
        current = fh.read()
    assert current == expected, (
        "cpp/qvf_single.hpp is out of date — run "
        "`python qvf-writer/scripts/amalgamate.py` to regenerate it."
    )
