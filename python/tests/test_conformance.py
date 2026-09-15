"""Conformance-suite tests — certify the reference writer/reader both ways.

* The committed golden corpus passes the runner (reader stays correct).
* A freshly generated corpus passes the runner (the writer stays a conforming
  producer). This regenerates into a tmp dir, so it never touches the committed
  frozen vectors.
"""

import importlib.util
import os

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
    assert runner.run(str(out)) == 0, "freshly written corpus failed conformance"
