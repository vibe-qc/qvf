"""Payload definitions of the periodic kinds and the run-record ``files`` index,
and the spin axis on band and DOS projections (spec § 5.6, § 5.8).

* Every ``(kind, role)`` row of ``_PAYLOAD_DEFS`` names a ``$defs`` entry, and
  ``validate_qvf`` checks that member against it (``E_PAYLOAD_SCHEMA``).
* The ``bands`` cross-check: ``projections`` and ``occupations`` agree with
  ``eigenvalues`` on ``[n_spin, n_k, n_bands]`` (``E_MEMBER_MALFORMED``).
* The writers accept the rank-4 / rank-3 projection shapes and ``occupations``,
  and refuse shapes that disagree.
"""

import hashlib
import json
import os
import sys
import zipfile

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

import qvf_reader  # noqa: E402
from qvf_reader import QvfReader, validate_qvf  # noqa: E402
from qvf_writer import QvfWriter  # noqa: E402

_SCHEMA = os.path.join(HERE, "..", "qvf_manifest.schema.json")

_WATER = [{"symbol": "O", "position": [0, 0, 0.117], "atomic_number": 8},
          {"symbol": "H", "position": [0, 0.757, -0.469], "atomic_number": 1}]

_WP12_ROWS = {
    ("bands", "kpath"): "KpathPayload",
    ("dos.coop", "meta"): "DosMetaPayload",
    ("dos.cohp", "meta"): "DosMetaPayload",
    ("fermi_surface", "mesh"): "FermiMeshPayload",
    ("phonon_bands", "qpath"): "QpathPayload",
    ("phonon_dos", "meta"): "PhononMetaPayload",
    ("equation_of_state", "fit"): "EosFitPayload",
    ("run.record", "files"): "RunRecordFilesPayload",
}


def _codes(report):
    return {f["code"] for f in report["findings"]}


def test_payload_rows_name_existing_definitions():
    with open(_SCHEMA, encoding="utf-8") as fh:
        defs = json.load(fh)["$defs"]
    for key, defname in _WP12_ROWS.items():
        assert qvf_reader._PAYLOAD_DEFS.get(key) == defname, key
    for defname in qvf_reader._PAYLOAD_DEFS.values():
        assert defname in defs, defname


# --- each payload definition is enforced by validate_qvf ----------------------

def _with(kind, payload):
    """A valid archive plus one section of ``kind`` whose JSON payload is
    ``payload``; returns (writer, role)."""
    w = QvfWriter(program="t", version="1")
    w.add_structure(_WATER)
    zeros = np.zeros(3)
    if kind == "bands":
        w.add_bands(payload, np.zeros((1, 2, 2)))
        return w, "kpath"
    if kind in ("dos.coop", "dos.cohp"):
        w.add_dos_coop_cohp(kind, zeros, np.zeros((1, 3)), np.zeros(1), payload)
        return w, "meta"
    if kind == "fermi_surface":
        w.add_fermi_surface(payload, np.zeros((2, 2, 2, 1)))
        return w, "mesh"
    if kind == "phonon_bands":
        w.add_phonon_bands(payload, np.zeros((2, 6)))
        return w, "qpath"
    if kind == "phonon_dos":
        w.add_phonon_dos(payload, zeros, zeros)
        return w, "meta"
    if kind == "equation_of_state":
        w.add_equation_of_state([90, 100, 110], [-5.1, -5.2, -5.15], payload)
        return w, "fit"
    if kind == "run.record":
        w.add_run_record(program="t", input_text="x", log_text="y",
                         files=payload)
        return w, "files"
    raise AssertionError(kind)


_GOOD = {
    "bands": {"n_spin": 1, "n_kpoints": 2, "n_bands": 2, "fermi": 0.0,
              "kpoints": [[0, 0, 0], [0.5, 0, 0]], "labels": ["G", "X"],
              "segments": [{"start": 0, "end": 1, "label_start": "G",
                            "label_end": "X"}],
              "channels": [{"atom": 0, "l": 1, "label": "O-2p"}, "H-s"]},
    "dos.coop": {"method": "coop", "n_spin": 1, "pairs": [[0, 1]],
                 "pair_labels": ["O1-H2"]},
    "dos.cohp": {"pairs": [{"i": 0, "j": 1, "distance_ang": 0.96}],
                 "smearing": 0.1, "smearing_type": "gaussian"},
    "fermi_surface": {"shape": [2, 2, 2], "nk1": 2, "nk2": 2, "nk3": 2,
                      "shift": [0.25, 0.25, 0.25], "symmetry_expanded": False,
                      "lattice_vectors": [[3, 0, 0], [0, 3, 0], [0, 0, 3]]},
    "phonon_bands": {"n_atoms": 2, "n_modes": 6, "has_eigenvectors": False,
                     "segments": [{"label_start": "G", "label_end": "X",
                                   "n_points": 2}]},
    "phonon_dos": {"n_atoms": 2, "n_modes": 6, "smearing": 5.0,
                   "channels": [{"atom": 0, "label": "O"}]},
    "equation_of_state": {"model": "vinet", "V0": 100.0, "E0": -5.2,
                          "B0": 74.0, "B0_prime": 4.0, "residual_rms": 1e-3,
                          "n_points": 3},
    "run.record": {"input": {"filename": "in.inp", "media_type": "text/plain"},
                   "log": {"truncated": True}},
}

_BAD = {
    "bands": {"n_spin": 3},
    "dos.coop": {"n_spin": "one"},
    "dos.cohp": {"pairs": [[0]]},
    "fermi_surface": {"shape": [2, 2]},
    "phonon_bands": {"fermi": 0.0},
    "phonon_dos": {"channels": [{"atom": 0}]},
    "equation_of_state": {"model": "spline"},
    "run.record": {"log": {"filename": "out.log", "size": 3}},
}


@pytest.mark.parametrize("kind", sorted(_GOOD))
def test_typed_payload_validates(tmp_path, kind):
    pytest.importorskip("jsonschema")
    w, _ = _with(kind, _GOOD[kind])
    path = str(tmp_path / "good.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["errors"]


@pytest.mark.parametrize("kind", sorted(_BAD))
def test_malformed_payload_is_a_payload_schema_error(tmp_path, kind):
    pytest.importorskip("jsonschema")
    w, role = _with(kind, _BAD[kind])
    path = str(tmp_path / "bad.qvf")
    w.write(path)
    report = validate_qvf(path)
    errors = [f for f in report["findings"] if f["severity"] == "error"]
    assert errors and {f["code"] for f in errors} == {"E_PAYLOAD_SCHEMA"}, errors
    assert {f["where"] for f in errors} == {f"/sections/1/members/{role}"}


def test_strict_payloads_accept_vendor_keys(tmp_path):
    pytest.importorskip("jsonschema")
    w = QvfWriter(program="t", version="1")
    w.add_structure(_WATER)
    w.add_equation_of_state([90, 100, 110], [-5.1, -5.2, -5.15],
                            {"model": "polynomial", "x_demo": {"order": 3}})
    w.add_bands({"x_demo": True, "segments": [{"n_points": 2, "x_demo": 1}]},
                np.zeros((1, 2, 2)))
    path = str(tmp_path / "x.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["errors"]


# --- bands spin-axis cross-check (both validators; this is the Python one) ----

def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _bands_archive(path, eig_shape, proj_shape=None, occ_shape=None):
    def member(name, shape):
        data = np.zeros(shape, dtype="<f8").tobytes()
        return data, {"path": name, "format": "binary", "dtype": "float64",
                      "shape": list(shape), "sha256": _sha(data)}

    structure = json.dumps({"atoms": _WATER}).encode()
    kpath = json.dumps({}).encode()
    files = {"s.json": structure, "b/kpath.json": kpath}
    members = {"kpath": {"path": "b/kpath.json", "format": "json",
                         "sha256": _sha(kpath)}}
    for role, shape in (("eigenvalues", eig_shape), ("projections", proj_shape),
                        ("occupations", occ_shape)):
        if shape is not None:
            data, spec = member(f"b/{role}.bin", shape)
            files[f"b/{role}.bin"] = data
            members[role] = spec
    manifest = {"qvf_version": 1,
                "source": {"program": "t", "version": "1", "calculation": "c"},
                "sections": [
                    {"id": "s", "kind": "structure", "members": {
                        "structure": {"path": "s.json", "format": "json",
                                      "sha256": _sha(structure)}}},
                    {"id": "b", "kind": "bands", "members": members}]}
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        zf.writestr("manifest.json", json.dumps(manifest))
    return path


@pytest.mark.parametrize("eig, proj, occ", [
    ((2, 3, 4), (2, 3, 4, 5), (2, 3, 4)),     # rank-4 + occupations
    ((1, 3, 4), (3, 4, 5), None),             # legacy rank 3
    ((2, 3, 4), None, (2, 3, 4)),             # occupations only
])
def test_bands_shapes_that_agree(tmp_path, eig, proj, occ):
    report = validate_qvf(_bands_archive(str(tmp_path / "b.qvf"), eig, proj, occ))
    assert report["ok"], report["errors"]


@pytest.mark.parametrize("eig, proj, occ, role", [
    ((1, 3, 4), (2, 3, 4, 5), None, "projections"),   # n_spin
    ((2, 3, 4), (2, 6, 4, 5), None, "projections"),   # n_k
    ((2, 3, 4), (2, 3, 1, 5), None, "projections"),   # n_bands
    ((1, 3, 4), (3, 5, 5), None, "projections"),      # rank 3: n_bands
    ((2, 3, 4), None, (1, 3, 4), "occupations"),      # n_spin
])
def test_bands_shapes_that_disagree(tmp_path, eig, proj, occ, role):
    report = validate_qvf(_bands_archive(str(tmp_path / "b.qvf"), eig, proj, occ))
    errors = [f for f in report["findings"] if f["severity"] == "error"]
    assert [(f["code"], f["where"]) for f in errors] == [
        ("E_MEMBER_MALFORMED", f"/sections/1/members/{role}")], errors


def test_schema_bounds_projection_ranks(tmp_path):
    pytest.importorskip("jsonschema")
    # Rank 5 is neither form; the semantic check leaves it to the schema.
    report = validate_qvf(_bands_archive(str(tmp_path / "b.qvf"), (1, 2, 2),
                                         (1, 2, 2, 1, 1)))
    assert "E_SCHEMA" in _codes(report)
    assert "E_MEMBER_MALFORMED" not in _codes(report)


# --- writers -------------------------------------------------------------------

def test_writer_spin_axis_roundtrip(tmp_path):
    eig = np.arange(24, dtype=np.float64).reshape(2, 3, 4)
    proj = np.random.default_rng(0).random((2, 3, 4, 5))
    occ = (eig < 10).astype(np.float64)
    pdos = np.random.default_rng(1).random((2, 3, 7))
    w = QvfWriter(program="t", version="1")
    w.add_structure(_WATER)
    w.add_bands({"n_spin": 2, "n_kpoints": 3, "n_bands": 4}, eig,
                projections=proj, occupations=occ)
    w.add_bands({"n_spin": 1}, eig[:1], projections=proj[0],
                section_id="legacy")
    w.add_dos_projected(np.linspace(-1, 1, 7), pdos,
                        [{"l": 0, "label": "s"}, {"l": 1, "label": "p"},
                         {"l": 2, "label": "d"}], n_spin=2)
    path = str(tmp_path / "spin.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["errors"]
    with QvfReader(path) as r:
        bands = {s["id"]: s for s in r.sections}
        np.testing.assert_array_equal(
            r.read_array(bands["bands"]["members"]["projections"]), proj)
        np.testing.assert_array_equal(
            r.read_array(bands["bands"]["members"]["occupations"]), occ)
        assert bands["legacy"]["members"]["projections"]["shape"] == [3, 4, 5]
        assert "occupations" not in bands["legacy"]["members"]
        assert bands["dos_projected"]["members"]["projections"]["shape"] == [2, 3, 7]


@pytest.mark.parametrize("kwargs", [
    {"projections": np.zeros((1, 3, 4, 2))},     # n_spin differs
    {"projections": np.zeros((2, 3, 5, 2))},     # n_bands differs
    {"projections": np.zeros((3, 3, 2))},        # rank 3: n_bands differs
    {"projections": np.zeros((2, 3))},           # rank 2
    {"occupations": np.zeros((2, 3, 5))},
])
def test_writer_refuses_bands_shapes_that_disagree(kwargs):
    w = QvfWriter(program="t", version="1")
    with pytest.raises(ValueError):
        w.add_bands({}, np.zeros((2, 3, 4)), **kwargs)


def test_writer_refuses_dos_projection_shapes():
    w = QvfWriter(program="t", version="1")
    with pytest.raises(ValueError):          # spin axis differs from n_spin
        w.add_dos_projected([0, 1], np.zeros((2, 1, 2)), [{"label": "s"}])
    with pytest.raises(ValueError):          # rank 1
        w.add_dos_projected([0, 1], np.zeros(2), [{"label": "s"}])
