"""Conformance-suite tests — certify the reference writer/reader both ways.

* The committed golden corpus passes the runner (reader stays correct).
* A freshly generated corpus passes the runner (the writer stays a conforming
  producer). This regenerates into a tmp dir, so it never touches the committed
  frozen vectors.
* Every archive of the negative corpus is rejected with exactly its expected
  finding codes (spec Appendix B).
* The legacy corpus (``conformance/legacy``: archives stamped
  ``qvf_version: 2``) is held to the same rule: the validators reject it today.
"""

import glob
import importlib.util
import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
_CONF = os.path.normpath(os.path.join(HERE, "..", "..", "conformance"))
_CORPUS = os.path.join(_CONF, "corpus")


def _load(mod_name, filename):
    path = os.path.join(_CONF, filename)
    if not os.path.exists(path):
        pytest.skip(f"{filename} not present (standalone checkout)")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_corpus_passes():
    runner = _load("run_conformance", "run_conformance.py")
    assert runner.run(_CORPUS) == 0, "committed golden corpus failed conformance"


def test_regenerated_corpus_passes(tmp_path):
    gen = _load("generate_corpus", "generate_corpus.py")
    runner = _load("run_conformance", "run_conformance.py")
    # Regenerate into a temp corpus dir (leave the committed vectors untouched).
    out = tmp_path / "corpus"
    out.mkdir()
    gen.CORPUS = str(out)
    gen.build()
    # The generator writes legacy/ beside the corpus directory it was given,
    # and the runner picks it up there.
    assert (tmp_path / "legacy").is_dir()
    assert runner.run(str(out)) == 0, "freshly written corpus failed conformance"


# --- negative (must-fail) corpus ---------------------------------------------

_NEGATIVE = os.path.join(_CONF, "negative")
# Codes only a JSON Schema engine can produce. The C++ reference validator has
# none, so exact code-set comparisons leave them out on both sides.
_SCHEMA_ENGINE_CODES = {"E_SCHEMA", "E_PAYLOAD_SCHEMA", "W_SCHEMA_SKIPPED"}


def _negative_expectations(directory):
    out = []
    for ef in sorted(glob.glob(os.path.join(directory, "*.expected.json"))):
        with open(ef, encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out


def _require_negative():
    if not os.path.isdir(_NEGATIVE):
        pytest.skip("negative corpus not present (standalone checkout)")


def test_negative_corpus():
    """Every must-fail archive is rejected with its expected finding code."""
    _require_negative()
    runner = _load("run_conformance", "run_conformance.py")
    assert runner.run_negative(_NEGATIVE) == 0, "negative corpus failed"


def test_negative_corpus_codes_are_exact():
    """Each archive isolates one rule: apart from schema-engine codes the
    validator reports exactly the expected codes. The C++ test
    (qvf_negative_corpus) asserts the same sets, so both reference validators
    agree code for code on the whole negative corpus. An archive that expects
    only a schema-engine code (a payload definition, spec § 5) must therefore
    raise nothing else."""
    _require_negative()
    runner = _load("run_conformance", "run_conformance.py")
    for exp in _negative_expectations(_NEGATIVE):
        report = runner.validate_qvf(
            os.path.join(_NEGATIVE, exp["archive"]),
            limits=runner.Limits.from_dict(exp.get("limits")))
        got = {f["code"] for f in report["findings"]} - _SCHEMA_ENGINE_CODES
        want = {w["code"] for w in exp["expect"]} - _SCHEMA_ENGINE_CODES
        assert got == want, (exp["archive"], report["findings"])


def test_negative_payload_archives_need_the_schema_engine(monkeypatch):
    """The payload-definition archives fail with E_PAYLOAD_SCHEMA when
    jsonschema is available, and are otherwise clean without it, which is
    what the C++ validator (no schema engine) sees."""
    _require_negative()
    pytest.importorskip("jsonschema")
    runner = _load("run_conformance", "run_conformance.py")
    names = [e["archive"] for e in _negative_expectations(_NEGATIVE)
             if {w["code"] for w in e["expect"]} == {"E_PAYLOAD_SCHEMA"}]
    assert len(names) >= 2, names
    for name in names:
        report = runner.validate_qvf(os.path.join(_NEGATIVE, name))
        assert not report["ok"], name
        assert {f["code"] for f in report["findings"]} == {"E_PAYLOAD_SCHEMA"}, \
            (name, report["findings"])
    reader = sys.modules[runner.validate_qvf.__module__]
    monkeypatch.setattr(reader, "_load_schema_validator", lambda: None)
    monkeypatch.setattr(reader, "_load_payload_validator", lambda _d: None)
    for name in names:
        report = runner.validate_qvf(os.path.join(_NEGATIVE, name))
        # A semantic payload check may still raise E_PAYLOAD_SCHEMA without
        # the engine (spectrum lengths, spec § 5.4); nothing else may.
        assert not [f for f in report["findings"] if f["severity"] == "error"
                    and f["code"] != "E_PAYLOAD_SCHEMA"], (name, report["findings"])
        assert runner.run_negative_one(
            os.path.join(_NEGATIVE, name),
            {"archive": name,
             "expect": [{"code": "E_PAYLOAD_SCHEMA", "severity": "error"}]}) == []


def test_negative_corpus_regenerates(tmp_path):
    """The generator reproduces the committed expectations, and its fresh
    archives fail the same way (guards generator / corpus drift)."""
    _require_negative()
    gen = _load("generate_negative",
                os.path.join("negative", "generate_negative.py"))
    runner = _load("run_conformance", "run_conformance.py")
    gen.build(str(tmp_path))
    assert _negative_expectations(str(tmp_path)) == \
        _negative_expectations(_NEGATIVE)
    assert runner.run_negative(str(tmp_path)) == 0
    for name in os.listdir(_NEGATIVE):
        if name.endswith(".qvf"):
            size = os.path.getsize(os.path.join(_NEGATIVE, name))
            assert size < 100 * 1024, name


def test_negative_base_archive_is_valid(tmp_path):
    """The archive every negative case mutates is itself clean."""
    _require_negative()
    gen = _load("generate_negative",
                os.path.join("negative", "generate_negative.py"))
    runner = _load("run_conformance", "run_conformance.py")
    path = tmp_path / "base.qvf"
    path.write_bytes(gen.base_archive().to_bytes())
    report = runner.validate_qvf(str(path))
    assert report["ok"] and not report["warnings"], report["findings"]


# --- legacy corpus (qvf_version 2) --------------------------------------------

_LEGACY = os.path.join(_CONF, "legacy")


def _require_legacy():
    if not os.path.isdir(_LEGACY):
        pytest.skip("legacy corpus not present (standalone checkout)")


def test_legacy_corpus():
    """The runner treats legacy/ like negative/: every archive is rejected
    with the code its expected.json names (today E_VERSION)."""
    _require_legacy()
    runner = _load("run_conformance", "run_conformance.py")
    assert runner.run_negative(_LEGACY, "legacy") == 0, "legacy corpus failed"


def test_legacy_corpus_codes_are_exact():
    _require_legacy()
    runner = _load("run_conformance", "run_conformance.py")
    expectations = _negative_expectations(_LEGACY)
    assert expectations
    for exp in expectations:
        report = runner.validate_qvf(
            os.path.join(_LEGACY, exp["archive"]),
            limits=runner.Limits.from_dict(exp.get("limits")))
        got = {f["code"] for f in report["findings"]} - _SCHEMA_ENGINE_CODES
        want = {w["code"] for w in exp["expect"]} - _SCHEMA_ENGINE_CODES
        assert got == want, (exp["archive"], report["findings"])
        # The withdrawn version 2 is read as 1: valid, with a warning.
        assert want == {"W_VERSION_WITHDRAWN"}, exp["archive"]
        assert report["ok"], exp["archive"]


def test_runner_options_select_the_corpora(capsys):
    """negative=False runs the positive corpus only (legacy/ too is skipped);
    legacy=False drops just legacy/."""
    _require_legacy()
    runner = _load("run_conformance", "run_conformance.py")
    assert runner.run(_CORPUS, negative=False) == 0
    out = capsys.readouterr().out
    assert "negative conformance" not in out and "legacy conformance" not in out
    assert runner.run(_CORPUS, legacy=False) == 0
    out = capsys.readouterr().out
    assert "negative conformance" in out and "legacy conformance" not in out
    assert runner.run(_CORPUS) == 0
    out = capsys.readouterr().out
    assert "negative conformance" in out and "legacy conformance" in out
