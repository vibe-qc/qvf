"""Container rules (spec § 2.2, § 2.3, § 4.2): member ``size``, archives
updated in place (the last ``manifest.json`` wins, superseded copies are
orphans), and the root ``byte_order``.
"""

import hashlib
import json
import os
import sys
import warnings
import zipfile

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

from qvf_reader import QvfReader, validate_qvf  # noqa: E402
from qvf_writer import QvfWriter  # noqa: E402

_CORPUS = os.path.join(REPO, "conformance", "corpus")
WATER = {
    "atoms": [{"symbol": "O", "position": [0.0, 0.0, 0.1173], "atomic_number": 8},
              {"symbol": "H", "position": [0.0, 0.7572, -0.4692],
               "atomic_number": 1}],
    "pbc": [False, False, False],
    "lattice_vectors": None,
}
_SDATA = json.dumps(WATER).encode()


def _manifest(sections=None, **extra):
    if sections is None:
        sections = [{"id": "structure", "kind": "structure",
                     "members": {"structure": {
                         "path": "structure/structure.json", "format": "json",
                         "sha256": hashlib.sha256(_SDATA).hexdigest()}}}]
    return {"qvf_version": 1,
            "source": {"program": "t", "version": "1", "calculation": "c"},
            "sections": sections, **extra}


def _zip(path, entries):
    """``entries``: ``(name, bytes)``; ``manifest.json`` is STOREd."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")          # duplicate names are the point
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in entries:
                method = (zipfile.ZIP_STORED if name == "manifest.json"
                          else zipfile.ZIP_DEFLATED)
                zf.writestr(zipfile.ZipInfo(name), data, compress_type=method)
    return str(path)


def _archive(tmp_path, manifest, name="a.qvf"):
    return _zip(tmp_path / name, [("structure/structure.json", _SDATA),
                                  ("manifest.json", json.dumps(manifest).encode())])


def _codes(report):
    return sorted(f["code"] for f in report["findings"]
                  if f["code"] != "W_SCHEMA_SKIPPED")


# --- writers ---------------------------------------------------------------

def _writer():
    w = QvfWriter(program="t", version="1", calculation="sizes")
    w.add_structure([{"symbol": "O", "position": [0, 0, 0], "atomic_number": 8},
                     {"symbol": "H", "position": [0, 0, 0.96], "atomic_number": 1}],
                    bonds=[{"i": 0, "j": 1, "order": 1.0}])
    w.add_volume("volume.density", np.ones((2, 2, 2), dtype=np.float32),
                 [0, 0, 0], np.eye(3) * 0.5)
    w.add_citations("@misc{x, title={Ångström}}\n")
    w.add_run_record(program="democode", input_text="in\n", log_text="log\n",
                     attachments={"geom": b"\x00\x01"},
                     files={"input": {"filename": "a.inp"}})
    w.add_vendor_section("x_test.thing", json_members={"meta": {"a": 1}},
                         binary_members={"data": (np.arange(3), "int32")})
    return w


def test_writer_declares_size_on_every_member_and_byte_order(tmp_path):
    path = _writer().write(str(tmp_path / "w.qvf"))
    report = validate_qvf(path)
    assert report["ok"] and not report["warnings"], report["findings"]
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["byte_order"] == "little"
        n = 0
        for section in manifest["sections"]:
            for role, member in section["members"].items():
                n += 1
                assert member["size"] == zf.getinfo(member["path"]).file_size, \
                    (section["id"], role)
    # structure + bonds, grid + data, references, input + log + attachment +
    # files, vendor meta + data
    assert n == 11


# --- member size --------------------------------------------------------------

@pytest.mark.parametrize("delta", [1, -1, 1000])
def test_size_mismatch_is_e_binary_size(tmp_path, delta):
    m = _manifest()
    m["sections"][0]["members"]["structure"]["size"] = len(_SDATA) + delta
    report = validate_qvf(_archive(tmp_path, m))
    assert not report["ok"]
    assert _codes(report) == ["E_BINARY_SIZE"]
    finding = next(f for f in report["findings"] if f["code"] == "E_BINARY_SIZE")
    assert finding["where"] == "/sections/0/members/structure"


def test_matching_size_is_clean(tmp_path):
    m = _manifest()
    m["sections"][0]["members"]["structure"]["size"] = len(_SDATA)
    report = validate_qvf(_archive(tmp_path, m))
    assert report["ok"] and _codes(report) == [], report["findings"]


@pytest.mark.parametrize("bad", [-1, 1.5, "12", True, None])
def test_malformed_size(tmp_path, bad):
    m = _manifest()
    m["sections"][0]["members"]["structure"]["size"] = bad
    report = validate_qvf(_archive(tmp_path, m))
    codes = set(_codes(report))
    assert "E_MEMBER_MALFORMED" in codes
    assert codes <= {"E_MEMBER_MALFORMED", "E_SCHEMA"}, report["findings"]


def test_reader_refuses_a_member_whose_size_disagrees(tmp_path):
    m = _manifest()
    member = m["sections"][0]["members"]["structure"]
    member["size"] = len(_SDATA)
    with QvfReader(_archive(tmp_path, m, "ok.qvf")) as r:
        assert r.read_json(r.sections[0]["members"]["structure"]) == WATER
    member["size"] = len(_SDATA) + 1
    with QvfReader(_archive(tmp_path, m, "bad.qvf")) as r:
        with pytest.raises(ValueError, match="E_BINARY_SIZE"):
            r.read_member(r.sections[0]["members"]["structure"])


def test_frozen_corpus_without_size_still_validates():
    """``size`` is optional: archives written before it existed stay valid."""
    path = os.path.join(_CORPUS, "structure_water.qvf")
    if not os.path.exists(path):
        pytest.skip("corpus not present (standalone checkout)")
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert all("size" not in m for s in manifest["sections"]
               for m in s["members"].values())
    assert "byte_order" not in manifest
    assert validate_qvf(path)["ok"]


# --- updating in place ------------------------------------------------------------

def _updated(tmp_path, n_old_manifests=1):
    old = _manifest(provenance={"run_status": "pending"})
    new = _manifest(provenance={"run_status": "converged"})
    entries = [("structure/structure.json", _SDATA)]
    for _ in range(n_old_manifests):
        entries.append(("manifest.json", json.dumps(old).encode()))
    entries += [("stale.json", b"{}"), ("manifest.json", json.dumps(new).encode())]
    return _zip(tmp_path / "updated.qvf", entries)


@pytest.mark.parametrize("n_old", [1, 2])
def test_superseded_manifests_are_orphans(tmp_path, n_old):
    path = _updated(tmp_path, n_old)
    report = validate_qvf(path)
    assert report["ok"], report["findings"]
    assert _codes(report) == ["W_ORPHAN_MEMBER"] * (n_old + 1)
    wheres = sorted(f["where"] for f in report["findings"]
                    if f["code"] == "W_ORPHAN_MEMBER")
    assert wheres == ["entry:manifest.json"] * n_old + ["entry:stale.json"]
    with QvfReader(path) as r:
        assert r.manifest["provenance"]["run_status"] == "converged"


def test_other_duplicates_stay_errors(tmp_path):
    path = _zip(tmp_path / "dup.qvf",
                [("structure/structure.json", b"{}"),
                 ("structure/structure.json", _SDATA),
                 ("manifest.json", json.dumps(_manifest()).encode()),
                 ("manifest.json", json.dumps(_manifest()).encode())])
    report = validate_qvf(path)
    assert _codes(report) == ["E_ZIP_DUPLICATE_ENTRY", "W_ORPHAN_MEMBER"]
    with pytest.raises(ValueError, match="E_ZIP_DUPLICATE_ENTRY"):
        QvfReader(path)


def test_appending_to_a_writer_archive_with_zipfile(tmp_path):
    """The § 2.3 procedure with a stock ZIP library: mode "a" appends after
    the existing entries and rewrites the central directory."""
    w = _writer()
    path = w.write(str(tmp_path / "base.qvf"))
    manifest = w.build_manifest()
    note = json.dumps({"note": "added later"}).encode()
    manifest["sections"].append({"id": "x_note", "kind": "x_test.note",
                                 "members": {"note": {
                                     "path": "x_note/note.json", "format": "json",
                                     "sha256": hashlib.sha256(note).hexdigest(),
                                     "size": len(note)}}})
    manifest["metadata"] = {"modified_utc": "2026-10-08T12:00:00Z"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "a") as zf:
            zf.writestr("x_note/note.json", note)
            zf.writestr(zipfile.ZipInfo("manifest.json"),
                        json.dumps(manifest).encode(),
                        compress_type=zipfile.ZIP_STORED)
    report = validate_qvf(path)
    assert report["ok"], report["findings"]
    assert _codes(report) == ["W_ORPHAN_MEMBER"]
    with QvfReader(path) as r:
        assert r.read_json(r.sections[-1]["members"]["note"]) == {"note": "added later"}


def test_updated_in_place_corpus_archive():
    """The corpus archive, checked independently of its generator."""
    path = os.path.join(_CORPUS, "updated_in_place.qvf")
    if not os.path.exists(path):
        pytest.skip("corpus not present (standalone checkout)")
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        assert names.count("manifest.json") == 2 and names[-1] == "manifest.json"
        first = json.loads(zf.open(infos[names.index("manifest.json")]).read())
        last = json.loads(zf.read("manifest.json"))
        assert all(i.compress_type == zipfile.ZIP_STORED for i in infos
                   if i.filename == "manifest.json")
    assert first["provenance"]["run_status"] == "pending"
    assert last["provenance"]["run_status"] == "converged"
    assert last["metadata"]["uuid"] == first["metadata"]["uuid"]
    assert "modified_utc" in last["metadata"]
    assert "modified_utc" not in first["metadata"]
    # The new manifest reuses entries written before the update.
    first_paths = {m["path"] for s in first["sections"] for m in s["members"].values()}
    last_paths = {m["path"] for s in last["sections"] for m in s["members"].values()}
    assert {"structure/structure.json", "job_spec/spec.json",
            "run/input.txt"} <= first_paths & last_paths
    assert first_paths - last_paths == {"run/files.json"}
    report = validate_qvf(path)
    assert report["ok"] and _codes(report) == ["W_ORPHAN_MEMBER"] * 2
    assert sorted(f["where"] for f in report["findings"]
                  if f["code"] == "W_ORPHAN_MEMBER") == \
        ["entry:manifest.json", "entry:run/files.json"]


def test_size_declared_corpus_archive():
    path = os.path.join(_CORPUS, "size_declared.qvf")
    if not os.path.exists(path):
        pytest.skip("corpus not present (standalone checkout)")
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        members = [m for s in manifest["sections"] for m in s["members"].values()]
        assert len(members) == 10      # JSON, binary and opaque members
        for m in members:
            assert m["size"] == zf.getinfo(m["path"]).file_size, m["path"]
    assert manifest["byte_order"] == "little"
    assert validate_qvf(path)["ok"]


# --- byte_order ------------------------------------------------------------------

def test_byte_order_little_is_valid_and_others_are_refused(tmp_path):
    pytest.importorskip("jsonschema")
    ok = validate_qvf(_archive(tmp_path, _manifest(byte_order="little"), "le.qvf"))
    assert ok["ok"] and _codes(ok) == []
    for value in ("big", "Little", 1):
        path = _archive(tmp_path, _manifest(byte_order=value), "be.qvf")
        report = validate_qvf(path)
        assert _codes(report) == ["E_SCHEMA"], (value, report["findings"])
        with pytest.raises(ValueError, match="E_SCHEMA"):
            QvfReader(path)


def test_reader_accepts_archives_without_byte_order(tmp_path):
    with QvfReader(_archive(tmp_path, _manifest())) as r:
        assert "byte_order" not in r.manifest
