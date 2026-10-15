#!/usr/bin/env python3
"""QVF conformance runner — certify a consumer against the golden corpus.

Positive corpus: for every ``*.expected.json`` in the corpus it (1) validates
the archive (schema + semantic integrity, incl. sha256), (2) confirms the set of
section kinds, and (3) decodes the members named by each check and compares to
the expected value. Any mismatch is a conformance failure.

Negative corpus (``negative/`` beside the corpus directory, or ``--negative
DIR``): every archive must be rejected by the validator with at least the
finding codes its ``expected.json`` names (spec Appendix B) — or, for a
warning-only archive, validate ``ok`` while reporting the warning. An archive
that names ``limits`` is validated with those caps. A validator that could not
run the JSON Schema check (``W_SCHEMA_SKIPPED``) cannot report the schema-only
codes, so those expectations are dropped for it.

Legacy corpus (``legacy/`` beside the corpus directory, or ``--legacy DIR``):
archives the format no longer produces but that exist in the wild, such as
those stamped ``qvf_version: 2``. They use the negative format and the
negative rules: the ``expected.json`` names the findings a validator reports,
today the warning ``W_VERSION_WITHDRAWN`` alone, so the archive is valid. It
is run and reported separately from ``negative/``.

This is the reference (Python) runner; the corpus + the ``expected.json`` check
format are language-agnostic, so a C++/Rust/… consumer can implement the same
loop to prove it reads QVF correctly.

Usage:  python run_conformance.py [corpus_dir] [--negative DIR | --no-negative]
                                  [--legacy DIR | --no-legacy]
        (exits non-zero on any failure; --no-negative also skips legacy/)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Optional

import numpy as np  # noqa: F401  (numpy decodes binary members via QvfReader)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "python")))
from qvf_reader import Limits, QvfReader, validate_qvf  # noqa: E402


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


# Codes only a JSON Schema engine can report (spec Appendix B).
_SCHEMA_ONLY_CODES = frozenset({"E_SCHEMA", "E_PAYLOAD_SCHEMA"})


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


# Codes only a JSON Schema engine can report (spec Appendix B).
_SCHEMA_ONLY_CODES = frozenset({"E_SCHEMA", "E_PAYLOAD_SCHEMA"})


def run_negative_one(archive_path: str, expected: dict) -> list[str]:
    """Failure strings for one negative archive (empty = rejected as expected).

    An expectation with a schema-only code applies only when the validator ran
    the JSON Schema check; one that could not (it reports W_SCHEMA_SKIPPED) is
    held to the remaining expectations alone.
    """
    try:
        limits = Limits.from_dict(expected.get("limits"))
    except TypeError as exc:
        return [f"bad limits in expected.json: {exc}"]
    report = validate_qvf(archive_path, limits=limits)
    got = {(f["code"], f["severity"]) for f in report["findings"]}
    expect = expected["expect"]
    if ("W_SCHEMA_SKIPPED", "warning") in got:
        # Without a schema engine the schema-only codes cannot appear; the
        # archive must then be otherwise clean.
        expect = [w for w in expect if w["code"] not in _SCHEMA_ONLY_CODES]
    fails = []
    for want in expect:
        if (want["code"], want["severity"]) not in got:
            fails.append(f"expected {want['severity']} {want['code']}, got "
                         f"{sorted(code for code, _ in got)}")
    expects_error = any(w["severity"] == "error" for w in expect)
    # Semantic payload checks (a spectrum's array lengths, spec § 5.4) report
    # E_PAYLOAD_SCHEMA even without a schema engine; judge the verdict on the
    # codes this validator is held to.
    other_errors = [f for f in report["findings"] if f["severity"] == "error"
                    and not (("W_SCHEMA_SKIPPED", "warning") in got
                             and f["code"] in _SCHEMA_ONLY_CODES)]
    if expects_error and not other_errors:
        fails.append("validator accepted a must-fail archive")
    if not expects_error and other_errors:
        fails.append(f"archive must validate ok here; errors: "
                     f"{[f['code'] for f in other_errors]}")
    return fails


def run_negative(negative_dir: str, label: str = "negative") -> int:
    """Run a corpus in the negative format (``negative/``, or ``legacy/``
    with ``label="legacy"``); 0 when every archive is judged as its
    expected.json says: invalid with the expected codes, or, for an archive
    that expects only warnings, valid with them."""
    expected_files = sorted(glob.glob(os.path.join(negative_dir,
                                                   "*.expected.json")))
    if not expected_files:
        print(f"no *.expected.json found in {negative_dir}", file=sys.stderr)
        return 2
    failed = 0
    for ef in expected_files:
        with open(ef, encoding="utf-8") as fh:
            expected = json.load(fh)
        archive = os.path.join(negative_dir, expected["archive"])
        if not os.path.exists(archive):
            fails = ["archive missing"]
        else:
            fails = run_negative_one(archive, expected)
        codes = ", ".join(w["code"] for w in expected["expect"])
        if fails:
            failed += 1
            print(f"FAIL {expected['archive']}")
            for f in fails:
                print(f"     - {f}")
        else:
            print(f"PASS {expected['archive']}  ({codes})")
    verdict = "rejected" if label == "negative" else "judged"
    print(f"\n{label} conformance: {len(expected_files) - failed}/"
          f"{len(expected_files)} archives {verdict} as expected")
    return 1 if failed else 0


def _sibling(corpus_dir: str, name: str) -> Optional[str]:
    """``name/`` beside ``corpus_dir``, when it holds expected.json files."""
    cand = os.path.join(os.path.dirname(os.path.abspath(corpus_dir)), name)
    if glob.glob(os.path.join(cand, "*.expected.json")):
        return cand
    return None


def run(corpus_dir: str, negative_dir: Optional[str] = None, *,
        negative: bool = True, legacy_dir: Optional[str] = None,
        legacy: Optional[bool] = None) -> int:
    """Run the positive corpus, then the negative one (``negative_dir``, else a
    ``negative/`` sibling of ``corpus_dir`` when present; ``negative=False``
    skips it), then the legacy one (``legacy_dir``, else a ``legacy/`` sibling;
    ``legacy`` defaults to ``negative``, so ``negative=False`` skips both).
    Returns 0 on success."""
    rc = _run_positive(corpus_dir)
    if negative:
        neg = negative_dir or _sibling(corpus_dir, "negative")
        if neg:
            print()
            rc_neg = run_negative(neg)
            rc = rc or rc_neg
    if negative if legacy is None else legacy:
        leg = legacy_dir or _sibling(corpus_dir, "legacy")
        if leg:
            print()
            rc_leg = run_negative(leg, "legacy")
            rc = rc or rc_leg
    return rc


def _run_positive(corpus_dir: str) -> int:
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


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corpus_dir", nargs="?", default=os.path.join(HERE, "corpus"))
    ap.add_argument("--negative", metavar="DIR",
                    help="negative corpus directory (default: a negative/ "
                         "sibling of corpus_dir, when present)")
    ap.add_argument("--no-negative", action="store_true",
                    help="run the positive corpus only (skips legacy/ too)")
    ap.add_argument("--legacy", metavar="DIR",
                    help="legacy corpus directory (default: a legacy/ "
                         "sibling of corpus_dir, when present)")
    ap.add_argument("--no-legacy", action="store_true",
                    help="skip the legacy corpus")
    args = ap.parse_args(argv)
    return run(args.corpus_dir, args.negative, negative=not args.no_negative,
               legacy_dir=args.legacy,
               legacy=False if args.no_legacy else (True if args.legacy
                                                    else None))


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
