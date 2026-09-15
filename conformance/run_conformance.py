#!/usr/bin/env python3
"""QVF conformance runner — certify a consumer against the golden corpus.

For every ``*.expected.json`` in the corpus it: (1) validates the archive
(schema + semantic integrity, incl. sha256), (2) confirms the set of section
kinds, and (3) decodes the members named by each check and compares to the
expected value. Any mismatch is a conformance failure.

This is the reference (Python) runner; the corpus + the ``expected.json`` check
format are language-agnostic, so a C++/Rust/… consumer can implement the same
loop to prove it reads QVF correctly.

Usage:  python run_conformance.py [corpus_dir]      # exits non-zero on failure
"""

from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "python")))
from qvf_reader import QvfReader, validate_qvf  # noqa: E402


def _navigate(obj, pointer):
    """Walk a nested object/array by a list of keys/indices."""
    cur = obj
    for step in pointer:
        cur = cur[step]
    return cur


def _member_of(reader: QvfReader, section_id: str, role: str):
    for s in reader.sections:
        if s.get("id") == section_id:
            m = s.get("members", {}).get(role)
            if m is None:
                raise KeyError(f"section {section_id!r} has no member {role!r}")
            return m
    raise KeyError(f"section id {section_id!r} not found")


def _equal(got, expected, tol) -> bool:
    if tol is not None:
        return abs(float(got) - float(expected)) <= float(tol)
    return got == expected


def run_one(archive_path: str, expected: dict) -> list[str]:
    """Return a list of failure strings for one archive (empty = pass)."""
    fails: list[str] = []

    report = validate_qvf(archive_path)
    if not report["ok"]:
        return [f"validation failed: {e}" for e in report["errors"]] or \
               ["validation failed"]

    with QvfReader(archive_path) as reader:
        # Section-kind set.
        got_kinds = sorted({s["kind"] for s in reader.sections})
        want_kinds = sorted(expected.get("kinds", got_kinds))
        if got_kinds != want_kinds:
            fails.append(f"kinds mismatch: got {got_kinds}, want {want_kinds}")
        # Source program.
        want_prog = expected.get("source_program")
        if want_prog is not None:
            got_prog = reader.manifest.get("source", {}).get("program")
            if got_prog != want_prog:
                fails.append(f"source.program: got {got_prog!r}, "
                             f"want {want_prog!r}")

        for chk in expected.get("checks", []):
            tol = chk.get("tol")
            want = chk.get("equals")
            try:
                if "manifest_pointer" in chk:
                    got = _navigate(reader.manifest, chk["manifest_pointer"])
                else:
                    member = _member_of(reader, chk["section"], chk["member"])
                    if "json_pointer" in chk:
                        got = _navigate(reader.read_json(member),
                                        chk["json_pointer"])
                    elif "binary_index" in chk:
                        arr = reader.read_array(member)
                        got = arr[tuple(chk["binary_index"])]
                    elif chk.get("decode") == "utf8":
                        # Opaque text member (citations.references,
                        # run.record input/log): decode the raw bytes.
                        text = reader.read_member(member).decode("utf-8")
                        if "contains" in chk:
                            if chk["contains"] not in text:
                                fails.append(
                                    f"check failed ({chk['section']}"
                                    f"/{chk['member']}): text does not "
                                    f"contain {chk['contains']!r}")
                            continue
                        got = text
                    else:
                        fails.append(f"malformed check (no pointer): {chk}")
                        continue
                if not _equal(got, want, tol):
                    fails.append(
                        f"check failed ({chk.get('section', 'manifest')}"
                        f"/{chk.get('member', '')}): got {got!r}, want {want!r}"
                        + (f" (tol {tol})" if tol else ""))
            except Exception as exc:  # noqa: BLE001 — report, don't crash
                fails.append(f"check errored {chk}: {exc}")

    return fails


def run(corpus_dir: str) -> int:
    expected_files = sorted(glob.glob(os.path.join(corpus_dir, "*.expected.json")))
    if not expected_files:
        print(f"no *.expected.json found in {corpus_dir}", file=sys.stderr)
        return 2

    total = 0
    failed = 0
    for ef in expected_files:
        with open(ef, encoding="utf-8") as fh:
            expected = json.load(fh)
        archive = os.path.join(corpus_dir, expected["archive"])
        total += 1
        if not os.path.exists(archive):
            print(f"FAIL {expected['archive']}: archive missing")
            failed += 1
            continue
        fails = run_one(archive, expected)
        if fails:
            failed += 1
            print(f"FAIL {expected['archive']}")
            for f in fails:
                print(f"     - {f}")
        else:
            print(f"PASS {expected['archive']}  "
                  f"({len(expected.get('checks', []))} checks)")

    print(f"\nconformance: {total - failed}/{total} archives passed")
    return 1 if failed else 0


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "corpus")
    raise SystemExit(run(d))
