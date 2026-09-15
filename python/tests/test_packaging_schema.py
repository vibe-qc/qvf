"""Drift guard: the packaged schema copy must match the canonical spec copy.

`qvf-writer` (the pip package) bundles `python/qvf_manifest.schema.json` so an
installed wheel can do full JSON-Schema validation. That copy must stay identical
to `spec/qvf_manifest.schema.json` (itself byte-identical to vibe-qc's canonical
schema). If this fails, refresh it:  cp spec/qvf_manifest.schema.json
python/qvf_manifest.schema.json and commit the refreshed copy. The archive
builder checks both committed copies and fails on drift.
"""

import os

import pytest

HERE = os.path.dirname(__file__)
_PY_COPY = os.path.normpath(os.path.join(HERE, "..", "qvf_manifest.schema.json"))
_SPEC = os.path.normpath(os.path.join(HERE, "..", "..", "spec",
                                      "qvf_manifest.schema.json"))


def test_packaged_schema_matches_spec():
    if not (os.path.exists(_PY_COPY) and os.path.exists(_SPEC)):
        pytest.skip("schema copies not present (standalone checkout)")
    with open(_PY_COPY, "rb") as a, open(_SPEC, "rb") as b:
        assert a.read() == b.read(), (
            "python/qvf_manifest.schema.json is out of date — "
            "cp spec/qvf_manifest.schema.json python/qvf_manifest.schema.json"
        )


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE"])
def test_packaged_license_matches_root(name):
    from pathlib import Path

    package = Path(__file__).resolve().parents[1]
    assert (package / name).read_bytes() == (package.parent / name).read_bytes()
