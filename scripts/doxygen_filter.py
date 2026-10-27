#!/usr/bin/env python3
"""Doxygen INPUT_FILTER for the QVF public headers (Apache-2.0).

The headers document their declarations with ordinary comments: ``//`` blocks
in the C++ headers and ``/* ... */`` blocks in the C headers. Doxygen reads
only its own comment markers, so this filter prints the header with each
comment block that directly precedes a declaration turned into a
documentation comment (``///`` or ``/** ... */``), and with each trailing
comment after a member turned into a member comment (``///<`` or
``/**< ... */``). It never adds or removes a line, so Doxygen's line numbers
match the source. The headers themselves stay unchanged.

Left alone: the file's leading comment, blocks followed by a blank line,
a preprocessor line, a closing brace or an access specifier, and trailing
comments after a closing brace or a preprocessor line.

Usage (as Doxygen calls it)::

    python3 scripts/doxygen_filter.py cpp/include/qvf/reader.hpp
"""

from __future__ import annotations

import re
import sys

_LINE = re.compile(r"^(\s*)//(?!/)\s?(.*)$")
_DIVIDER = re.compile(r"^-{2,}\s*(.*?)\s*-*\s*$")
_BLOCK_START = re.compile(r"^(\s*)/\*(?![*!])\s?(.*)$")
_TRAIL_LINE = re.compile(r"^(?P<code>[^\"'/]*[;,{]\s*)//(?!/)\s?(?P<text>.*)$")
_TRAIL_BLOCK = re.compile(r"^(?P<code>[^\"'/]*[;,{]\s*)/\*(?![*!<])\s?(?P<text>.*\*/)\s*$")
_PLACEHOLDER = re.compile(r"<(/?[A-Za-z_][\w.:-]*)>")
_NOT_A_DECLARATION = re.compile(r"^\s*(#|}|$|//|/\*|\*|public:|private:|protected:)")


def _documents(next_line: str | None) -> bool:
    return next_line is not None and not _NOT_A_DECLARATION.match(next_line)


def _undivide(text: str) -> str:
    """Documentation text of a comment line: ``--- structure ----`` (a section
    divider) becomes ``structure:``, and an angle-bracket placeholder such as
    ``custom.<name>`` or ``vector<double>`` is escaped so Doxygen does not read
    it as an HTML tag."""
    m = _DIVIDER.match(text)
    text = f"{m.group(1)}:" if m and m.group(1) else text
    return _PLACEHOLDER.sub(r"\\<\1\\>", text)


def filter_lines(lines: list[str]) -> list[str]:
    out = list(lines)
    n = len(lines)
    i = 0
    # The file's leading comment (name, license, overview) is not a
    # declaration's documentation.
    while i < n and (lines[i].lstrip().startswith(("//", "/*", "*")) or not lines[i].strip()):
        if lines[i].lstrip().startswith("/*"):
            while i < n and "*/" not in lines[i]:
                i += 1
        i += 1
    while i < n:
        line = lines[i]
        m = _LINE.match(line)
        if m:
            j = i
            while j < n and _LINE.match(lines[j]):
                j += 1
            if _documents(lines[j] if j < n else None):
                for k in range(i, j):
                    indent, text = _LINE.match(lines[k]).groups()
                    out[k] = f"{indent}/// {_undivide(text)}".rstrip()
            i = j
            continue
        m = _BLOCK_START.match(line)
        if m:
            j = i
            while j < n and "*/" not in lines[j]:
                j += 1
            if j < n and lines[j].rstrip().endswith("*/") and \
                    _documents(lines[j + 1] if j + 1 < n else None):
                indent, text = m.groups()
                out[i] = f"{indent}/** {_undivide(text)}".rstrip()
                for k in range(i + 1, j + 1):
                    out[k] = _PLACEHOLDER.sub(r"\\<\1\\>", lines[k])
            i = j + 1
            continue
        if not _NOT_A_DECLARATION.match(line):
            t = _TRAIL_LINE.match(line)
            if t:
                out[i] = f"{t.group('code')}///< {_undivide(t.group('text'))}".rstrip()
            else:
                t = _TRAIL_BLOCK.match(line)
                if t:
                    out[i] = f"{t.group('code')}/**< {_undivide(t.group('text'))}"
        i += 1
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: doxygen_filter.py HEADER", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    sys.stdout.write("\n".join(filter_lines(lines)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
