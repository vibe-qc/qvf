"""The Doxygen input filter of the API reference (scripts/doxygen_filter.py).

It turns the public headers' plain comments into documentation comments for
Doxygen. These tests pin that it never changes a line count or the code of a
line, only comment markers and comment text, and that it keeps the file's
leading comment and closing-brace comments as they are.
"""

import glob
import importlib.util
import os
import re

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCRIPT = os.path.join(ROOT, "scripts", "doxygen_filter.py")
_HEADERS = sorted(glob.glob(os.path.join(ROOT, "cpp", "include", "qvf", "**", "*.h*"),
                            recursive=True))


def _filter():
    if not os.path.exists(_SCRIPT):
        pytest.skip("scripts/doxygen_filter.py not present (standalone checkout)")
    spec = importlib.util.spec_from_file_location("doxygen_filter", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _code(lines):
    """The code of each line, without comments (block comments may span
    lines; the headers keep comment markers out of string literals)."""
    out, in_block = [], False
    for line in lines:
        code, rest = "", line
        while rest:
            if in_block:
                end = rest.find("*/")
                if end < 0:
                    break
                rest, in_block = rest[end + 2:], False
                continue
            m = re.search(r"//|/\*", rest)
            if not m:
                code += rest
                break
            code += rest[:m.start()]
            if m.group() == "//":
                break
            rest, in_block = rest[m.end():], True
        out.append(code.rstrip())
    return out


@pytest.mark.parametrize("path", _HEADERS, ids=lambda p: os.path.relpath(p, ROOT))
def test_filter_changes_only_comments(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    out = _filter().filter_lines(lines)
    assert len(out) == len(lines)
    assert _code(out) == _code(lines)


def test_filter_examples():
    f = _filter().filter_lines
    src = ["// qvf/x.hpp — header.", "// License: Apache-2.0.", "#ifndef X", "",
           "namespace qvf {", "// Opens custom.<name> roles.", "int open();",
           "int n;  // count", "// --- readers ---", "", "}  // namespace qvf",
           "/* --- structure ----", " * symbols: <n> names.", " */", "int add(int);",
           "typedef struct w w; /* opaque */"]
    assert f(src) == [
        "// qvf/x.hpp — header.", "// License: Apache-2.0.", "#ifndef X", "",
        "namespace qvf {", "/// Opens custom.\\<name\\> roles.", "int open();",
        "int n;  ///< count", "// --- readers ---", "", "}  // namespace qvf",
        "/** structure:", " * symbols: \\<n\\> names.", " */", "int add(int);",
        "typedef struct w w; /**< opaque */"]
