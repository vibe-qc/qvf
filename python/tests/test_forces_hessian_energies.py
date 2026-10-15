"""The root ``energies`` block and the ``forces`` and ``hessian`` kinds
(spec § 3.6, § 5.10, § 5.11; P05, P06, P07).

Covers the writer (round trips and refusals), the schema definitions, and the
validator rules that JSON Schema cannot express: gradient and Hessian shapes
against the atom count of the section's structure, the references
``meta.structure_ref`` and ``vibrations.hessian_ref``, and the agreement of
``energies`` with ``provenance.scf_energy`` and ``thermochemistry.zpve_eh``
(``E_ROOT_INCONSISTENT``).
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

_SCHEMA_CODES = {"E_SCHEMA", "E_PAYLOAD_SCHEMA", "W_SCHEMA_SKIPPED"}

WATER = [{"symbol": "O", "position": [0.0, 0.0, 0.1173], "atomic_number": 8},
         {"symbol": "H", "position": [0.0, 0.7572, -0.4692], "atomic_number": 1},
         {"symbol": "H", "position": [0.0, -0.7572, -0.4692], "atomic_number": 1}]
UNITS = {"energy": "hartree", "length": "bohr"}


def _hartree(value):
    return {"value": value, "units": "hartree"}


def _codes(report):
    return {f["code"] for f in report["findings"]} - _SCHEMA_CODES


def _where(report, code):
    return sorted(f["where"] for f in report["findings"] if f["code"] == code)


# --- raw archives, so the validator sees what the writer would refuse ----------

def _json_bytes(obj):
    return json.dumps(obj).encode("utf-8")


def _member(path, data, fmt="json", dtype=None, shape=None):
    m = {"path": path, "format": fmt, "sha256": hashlib.sha256(data).hexdigest()}
    if dtype is not None:
        m["dtype"], m["shape"] = dtype, shape
    return m


class _Raw:
    """A manifest plus member files, written as a ZIP with the manifest last."""

    def __init__(self):
        self.manifest = {"qvf_version": 1,
                         "source": {"program": "t", "version": "1",
                                    "calculation": "derivatives"},
                         "sections": []}
        self.files = {}

    def structure(self, sid="structure", atoms=WATER):
        data = _json_bytes({"atoms": atoms, "pbc": [False] * 3,
                            "lattice_vectors": None})
        path = f"{sid}/structure.json"
        self.files[path] = data
        self.manifest["sections"].append(
            {"id": sid, "kind": "structure",
             "members": {"structure": _member(path, data)}})
        return self

    def binary(self, path, shape):
        data = np.zeros(shape, dtype="<f8").tobytes()
        self.files[path] = data
        return _member(path, data, "binary", "float64", list(shape))

    def json(self, path, obj):
        data = _json_bytes(obj)
        self.files[path] = data
        return _member(path, data)

    def section(self, sid, kind, members, **fields):
        self.manifest["sections"].append({"id": sid, "kind": kind, **fields,
                                          "members": members})
        return self

    def forces(self, n_rows=3, *, meta=None, stress=None, sid="forces", **fields):
        members = {"gradient": self.binary(f"{sid}/gradient.bin", (n_rows, 3))}
        if stress is not None:
            members["stress"] = self.binary(f"{sid}/stress.bin", stress)
        if meta is not None:
            members["meta"] = self.json(f"{sid}/meta.json", meta)
        return self.section(sid, "forces", members, **fields)

    def hessian(self, shape=(9, 9), *, meta=None, sid="hessian", **fields):
        members = {"matrix": self.binary(f"{sid}/matrix.bin", shape)}
        if meta is not None:
            members["meta"] = self.json(f"{sid}/meta.json", meta)
        return self.section(sid, "hessian", members, **fields)

    def validate(self, tmp_path, name="a.qvf"):
        path = str(tmp_path / name)
        with zipfile.ZipFile(path, "w") as zf:
            for p, data in self.files.items():
                zf.writestr(p, data)
            zf.writestr(zipfile.ZipInfo("manifest.json"), _json_bytes(self.manifest),
                        compress_type=zipfile.ZIP_STORED)
        return validate_qvf(path)


# --- writer -------------------------------------------------------------------

def _writer():
    w = QvfWriter(program="t", version="1", calculation="water")
    w.add_structure(WATER)
    return w


def test_writer_round_trip(tmp_path):
    rng = np.random.default_rng(3)
    grad = rng.standard_normal((3, 3))
    stress = rng.standard_normal((3, 3))
    stress = (stress + stress.T) / 2
    hess = rng.standard_normal((9, 9))
    hess = (hess + hess.T) / 2
    w = _writer()
    w.set_provenance(method="RHF", scf_energy=_hartree(-74.96))
    w.set_thermochemistry(zpve_eh=0.0213)
    w.add_forces(grad, stress=stress,
                 meta={"structure_ref": "structure", "method": "rhf",
                       "convention": "gradient", "units": UNITS})
    w.add_hessian(hess, meta={"structure_ref": "structure", "mass_weighted": False,
                              "projected": False,
                              "atom_masses_amu": [15.999, 1.008, 1.008],
                              "units": UNITS})
    w.add_vibrations({"frequencies": [1650.0, 3800.0, 3900.0]},
                     np.zeros((3, 3, 3)), hessian_ref="hessian")
    w.set_energies(-74.96, method="rhf",
                   components={"nuclear_repulsion": 9.17, "electronic": -84.13,
                               "zpve": 0.0213, "x_madeup": 0.5},
                   by_method=[{"method": "rhf", "total": -74.96},
                              {"method": "mp2", "total": {"value": -2040.5,
                                                          "units": "ev"},
                               "components": {"correlation": -0.04}}],
                   units_note="hartree unless stated")
    path = str(tmp_path / "derivatives.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["errors"]

    with QvfReader(path) as r:
        m = r.manifest
        by_id = {s["id"]: s for s in r.sections}
        np.testing.assert_array_equal(r.read_array(by_id["forces"]["members"]["gradient"]), grad)
        np.testing.assert_array_equal(r.read_array(by_id["forces"]["members"]["stress"]), stress)
        np.testing.assert_array_equal(r.read_array(by_id["hessian"]["members"]["matrix"]), hess)
        assert r.read_json(by_id["hessian"]["members"]["meta"])["atom_masses_amu"][0] == 15.999
    assert by_id["forces"]["members"]["gradient"]["shape"] == [3, 3]
    assert by_id["hessian"]["members"]["matrix"]["shape"] == [9, 9]
    assert by_id["vibrations"]["hessian_ref"] == "hessian"
    assert m["energies"] == {
        "total": _hartree(-74.96), "method": "rhf",
        "components": {"nuclear_repulsion": _hartree(9.17),
                       "electronic": _hartree(-84.13), "zpve": _hartree(0.0213),
                       "x_madeup": _hartree(0.5)},
        "by_method": [{"method": "rhf", "total": _hartree(-74.96)},
                      {"method": "mp2", "total": {"value": -2040.5, "units": "ev"},
                       "components": {"correlation": _hartree(-0.04)}}],
        "units_note": "hartree unless stated"}


def test_writer_omits_optional_members(tmp_path):
    w = _writer()
    w.add_forces([[0.0, 0.0, 0.01], [0.0, 0.01, -0.005], [0.0, -0.01, -0.005]])
    w.add_hessian(np.eye(9))
    w.set_energies(-74.96)
    manifest = w.build_manifest()
    by_id = {s["id"]: s for s in manifest["sections"]}
    assert set(by_id["forces"]["members"]) == {"gradient"}
    assert set(by_id["hessian"]["members"]) == {"matrix"}
    assert manifest["energies"] == {"total": _hartree(-74.96)}
    path = str(tmp_path / "minimal.qvf")
    w.write(path)
    assert validate_qvf(path)["ok"]


@pytest.mark.parametrize("call, match", [
    (lambda w: w.add_forces(np.zeros(9)), r"\[n_atoms, 3\]"),
    (lambda w: w.add_forces(np.zeros((3, 2))), r"\[n_atoms, 3\]"),
    (lambda w: w.add_forces(np.zeros((3, 3)) + 1j), "real numbers"),
    (lambda w: w.add_forces(np.zeros((3, 3)), stress=np.zeros((2, 2))), r"\[3, 3\]"),
    (lambda w: w.add_forces(np.zeros((3, 3)), meta=[("method", "rhf")]), "mapping"),
    (lambda w: w.add_hessian(np.zeros((9, 6))), "square"),
    (lambda w: w.add_hessian(np.zeros((8, 8))), "divisible by 3"),
    (lambda w: w.add_hessian(np.zeros((9, 9)) + 1j), "real numbers"),
    (lambda w: w.add_hessian(np.zeros((9, 9)), meta={"atom_masses_amu": [1, 2]}),
     "3 atoms"),
    (lambda w: w.add_hessian(np.zeros((9, 9)), meta={"mass_weighted": True}),
     "atom_masses_amu"),
    (lambda w: w.add_vibrations({"frequencies": [1.0]}, np.zeros((1, 3, 3)),
                                hessian_ref="structure"), "hessian"),
])
def test_writer_refuses_before_writing(call, match):
    w = _writer()
    before = json.loads(json.dumps(w.build_manifest()))
    with pytest.raises(ValueError, match=match):
        call(w)
    assert w.build_manifest() == before
    # Nothing was registered: the default ids and paths are still free.
    w.add_forces(np.zeros((3, 3)))
    w.add_hessian(np.zeros((9, 9)))


@pytest.mark.parametrize("kwargs, match", [
    ({"total_eh": True}, "number"),
    ({"total_eh": float("nan")}, "finite"),
    ({"total_eh": {"value": -1.0}}, "value, units"),
    ({"total_eh": -1.0, "units": ""}, "units"),
    ({"total_eh": -1.0, "method": ""}, "method"),
    ({"total_eh": -1.0, "components": {"kinetic": 1.0}}, "unknown energy component"),
    ({"total_eh": -1.0, "by_method": [{"total": -1.0}]}, "method"),
    ({"total_eh": -1.0, "by_method": [{"method": "rhf"}]}, "total is required"),
    ({"total_eh": -1.0, "by_method": [{"method": "rhf", "total": -1.0, "e": 1}]},
     "unknown keys"),
])
def test_set_energies_refuses(kwargs, match):
    w = _writer()
    with pytest.raises(ValueError, match=match):
        w.set_energies(**kwargs)
    assert "energies" not in w.build_manifest()


# --- schema -------------------------------------------------------------------

def _schema_errors(manifest):
    jsonschema = pytest.importorskip("jsonschema")
    with open(qvf_reader._SCHEMA_PATH, encoding="utf-8") as fh:
        validator = jsonschema.Draft202012Validator(json.load(fh))
    return list(validator.iter_errors(manifest))


def _payload_errors(defname, payload):
    pytest.importorskip("jsonschema")
    return list(qvf_reader._load_payload_validator(defname).iter_errors(payload))


@pytest.mark.parametrize("energies", [
    {"total": _hartree(-1.0), "kinetic": _hartree(1.0)},          # unknown key
    {"method": "rhf"},                                            # no total
    {"total": -1.0},                                              # bare number
    {"total": _hartree(-1.0), "components": {"kinetic": _hartree(1.0)}},
    {"total": _hartree(-1.0), "components": {"zpve": 0.02}},
    {"total": _hartree(-1.0), "by_method": [{"method": "rhf"}]},
    {"total": _hartree(-1.0), "by_method": [{"total": _hartree(-1.0)}]},
    {"total": _hartree(-1.0), "by_method": [{"method": "rhf", "total": _hartree(-1.0),
                                             "note": "x"}]},
    {"total": _hartree(-1.0), "method": ""},
])
def test_schema_rejects_malformed_energies(energies):
    w = _writer()
    manifest = json.loads(json.dumps(w.build_manifest()))
    manifest["energies"] = energies
    assert _schema_errors(manifest)


def test_schema_accepts_vendor_keys_in_energies():
    w = _writer()
    manifest = json.loads(json.dumps(w.build_manifest()))
    manifest["energies"] = {
        "total": _hartree(-1.0), "x_code": {"anything": True},
        "components": {"x_extra": _hartree(0.1)},
        "by_method": [{"method": "rhf", "total": _hartree(-1.0), "x_note": "n"}]}
    assert not _schema_errors(manifest)


@pytest.mark.parametrize("defname, payload, ok", [
    ("ForcesMetaPayload", {}, True),
    ("ForcesMetaPayload", {"structure_ref": "s", "method": "rks",
                           "convention": "gradient", "units": UNITS,
                           "x_note": 1}, True),
    ("ForcesMetaPayload", {"convention": "force"}, False),
    ("ForcesMetaPayload", {"units": {"energy": "ev", "length": "bohr"}}, False),
    ("ForcesMetaPayload", {"units": {"energy": "hartree", "time": "fs"}}, False),
    ("ForcesMetaPayload", {"atom_masses_amu": [1.0]}, False),
    ("HessianMetaPayload", {"mass_weighted": True, "atom_masses_amu": [1.0]}, True),
    ("HessianMetaPayload", {"mass_weighted": False}, True),
    ("HessianMetaPayload", {"mass_weighted": True}, False),
    ("HessianMetaPayload", {"atom_masses_amu": [1.0, 0.0]}, False),
    ("HessianMetaPayload", {"projected": "yes"}, False),
    ("HessianMetaPayload", {"method": "rhf"}, False),
])
def test_meta_payload_definitions(defname, payload, ok):
    assert (not _payload_errors(defname, payload)) is ok


@pytest.mark.parametrize("kind, role, shape, dtype", [
    ("forces", "gradient", [3, 2], "float64"),
    ("forces", "gradient", [9], "float64"),
    ("forces", "gradient", [3, 3], "float32"),
    ("forces", "stress", [3, 2], "float64"),
    ("hessian", "matrix", [81], "float64"),
    ("hessian", "matrix", [9, 9, 1], "float64"),
])
def test_schema_member_shapes(kind, role, shape, dtype):
    w = _writer()
    if kind == "forces":
        w.add_forces(np.zeros((3, 3)), stress=np.zeros((3, 3)))
    else:
        w.add_hessian(np.zeros((9, 9)))
    manifest = json.loads(json.dumps(w.build_manifest()))
    assert not _schema_errors(manifest)
    member = manifest["sections"][1]["members"][role]
    member["shape"], member["dtype"] = shape, dtype
    assert _schema_errors(manifest)


# --- validator: shapes and references -----------------------------------------

def test_valid_raw_archive_is_clean(tmp_path):
    raw = (_Raw().structure()
           .forces(3, meta={"structure_ref": "structure"}, stress=(3, 3))
           .hessian((9, 9), meta={"atom_masses_amu": [16.0, 1.0, 1.0]}))
    raw.section("vibrations", "vibrations",
                {"metadata": raw.json("vib/metadata.json", {"frequencies": [1.0]}),
                 "displacements": raw.binary("vib/displacements.bin", (1, 3, 3))},
                hessian_ref="hessian")
    report = raw.validate(tmp_path)
    assert report["ok"] and not _codes(report), report["errors"]


def test_gradient_rows_must_match_the_named_structure(tmp_path):
    report = (_Raw().structure()
              .forces(2, meta={"structure_ref": "structure"}).validate(tmp_path))
    assert _codes(report) == {"E_MEMBER_MALFORMED"}
    assert _where(report, "E_MEMBER_MALFORMED") == ["/sections/1/members/gradient"]


def test_the_only_structure_is_used_when_nothing_is_named(tmp_path):
    report = _Raw().structure().forces(4).validate(tmp_path)
    assert _codes(report) == {"E_MEMBER_MALFORMED"}


def test_no_check_when_the_structure_is_ambiguous(tmp_path):
    raw = _Raw().structure().structure("dimer", WATER[:2]).forces(4)
    assert not _codes(raw.validate(tmp_path))


def test_section_structure_ref_takes_precedence(tmp_path):
    def raw(n_rows):
        return (_Raw().structure().structure("dimer", WATER[:2])
                .forces(n_rows, meta={"structure_ref": "structure"},
                        structure_ref="dimer"))
    assert not _codes(raw(2).validate(tmp_path, "two.qvf"))
    assert _codes(raw(3).validate(tmp_path, "three.qvf")) == {"E_MEMBER_MALFORMED"}


@pytest.mark.parametrize("build, role", [
    (lambda r: r.forces(3, stress=(3, 2)), "stress"),
    (lambda r: r.hessian((9, 6)), "matrix"),
    (lambda r: r.hessian((8, 8)), "matrix"),
    (lambda r: r.hessian((6, 6)), "matrix"),                       # 2 atoms, not 3
    (lambda r: r.hessian((9, 9), meta={"atom_masses_amu": [16.0, 1.0]}), "meta"),
])
def test_member_shape_findings(tmp_path, build, role):
    report = build(_Raw().structure()).validate(tmp_path)
    assert _codes(report) == {"E_MEMBER_MALFORMED"}, report["findings"]
    assert _where(report, "E_MEMBER_MALFORMED") == [f"/sections/1/members/{role}"]


def test_gradient_shape_is_checked_without_a_schema_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(qvf_reader, "_load_schema_validator", lambda: None)
    monkeypatch.setattr(qvf_reader, "_load_payload_validator", lambda name: None)
    report = _Raw().structure().forces(3).validate(tmp_path, "ok.qvf")
    assert report["ok"]
    raw = _Raw().structure()
    raw.section("forces", "forces",
                {"gradient": raw.binary("forces/gradient.bin", (3, 2))})
    assert _codes(raw.validate(tmp_path, "bad.qvf")) == {"E_MEMBER_MALFORMED"}


@pytest.mark.parametrize("kind", ["forces", "hessian"])
def test_meta_structure_ref_must_name_a_structure(tmp_path, kind):
    raw = _Raw().structure().hessian((9, 9), sid="h0")
    if kind == "forces":
        raw.forces(3, meta={"structure_ref": "h0"})
    else:
        raw.hessian((9, 9), meta={"structure_ref": "missing"})
    report = raw.validate(tmp_path)
    assert _codes(report) == {"E_REF_UNRESOLVED"}
    assert _where(report, "E_REF_UNRESOLVED") == ["/sections/2/members/meta"]


@pytest.mark.parametrize("ref", ["structure", "nowhere", 7])
def test_hessian_ref_must_name_a_hessian(tmp_path, ref):
    raw = _Raw().structure()
    raw.section("vibrations", "vibrations",
                {"metadata": raw.json("vib/metadata.json", {"frequencies": [1.0]}),
                 "displacements": raw.binary("vib/displacements.bin", (1, 3, 3))},
                hessian_ref=ref)
    report = raw.validate(tmp_path)
    assert _codes(report) == {"E_REF_UNRESOLVED"}
    assert _where(report, "E_REF_UNRESOLVED") == ["/sections/1/hessian_ref"]


# --- validator: root energies -------------------------------------------------

def _energies_report(tmp_path, energies, provenance=None, thermochemistry=None):
    raw = _Raw().structure()
    raw.manifest["energies"] = energies
    if provenance is not None:
        raw.manifest["provenance"] = provenance
    if thermochemistry is not None:
        raw.manifest["thermochemistry"] = thermochemistry
    return raw.validate(tmp_path)


RHF = {"method": "rhf", "scf_energy": _hartree(-74.9659011)}


@pytest.mark.parametrize("energies, provenance, where", [
    # total, stated for the provenance method, disagrees
    ({"total": _hartree(-74.96), "method": "rhf"}, RHF, ["/energies/total"]),
    # method names match case-insensitively
    ({"total": _hartree(-74.96), "method": "RHF"}, RHF, ["/energies/total"]),
    # a by_method entry for the provenance method disagrees
    ({"total": _hartree(-75.0), "method": "mp2",
      "by_method": [{"method": "mp2", "total": _hartree(-75.0)},
                    {"method": "Rhf", "total": _hartree(-74.95)}]},
     RHF, ["/energies/by_method/1/total"]),
    # both disagree
    ({"total": _hartree(-74.0), "method": "rhf",
      "by_method": [{"method": "rhf", "total": _hartree(-74.0)}]},
     RHF, ["/energies/by_method/0/total", "/energies/total"]),
    # units are converted before comparing
    ({"total": {"value": -74.9659011 * 27.211386245988 + 1e-4, "units": "ev"},
      "method": "rhf"}, RHF, ["/energies/total"]),
])
def test_energies_disagreeing_with_provenance(tmp_path, energies, provenance, where):
    report = _energies_report(tmp_path, energies, provenance)
    assert _codes(report) == {"E_ROOT_INCONSISTENT"}
    assert _where(report, "E_ROOT_INCONSISTENT") == where


@pytest.mark.parametrize("energies, provenance", [
    # agreement within 1e-8 hartree
    ({"total": _hartree(-74.9659011 + 5e-9), "method": "rhf"}, RHF),
    # the same energy in eV
    ({"total": {"value": -74.9659011 * 27.211386245988, "units": "ev"},
      "method": "rhf"}, RHF),
    # total of another method is not compared
    ({"total": _hartree(-75.2), "method": "mp2",
      "by_method": [{"method": "rhf", "total": _hartree(-74.9659011)}]}, RHF),
    # total without a method is not compared
    ({"total": _hartree(-75.2)}, RHF),
    # no provenance method or energy: nothing to compare with
    ({"total": _hartree(-75.2), "method": "rhf"}, {"scf_energy": _hartree(-74.0)}),
    ({"total": _hartree(-75.2), "method": "rhf"}, {"method": "rhf"}),
])
def test_energies_consistent_or_not_comparable(tmp_path, energies, provenance):
    report = _energies_report(tmp_path, energies, provenance)
    assert report["ok"] and not _codes(report), report["findings"]


def test_zpve_must_agree_with_thermochemistry(tmp_path):
    energies = {"total": _hartree(-74.94), "components": {"zpve": _hartree(0.0213)}}
    good = _energies_report(tmp_path, energies, thermochemistry={"zpve_eh": 0.0213})
    assert not _codes(good)
    bad = _energies_report(tmp_path, energies, thermochemistry={"zpve_eh": 0.0214})
    assert _codes(bad) == {"E_ROOT_INCONSISTENT"}
    assert _where(bad, "E_ROOT_INCONSISTENT") == ["/energies/components/zpve"]


def test_unrecognised_units_are_not_compared():
    manifest = {"provenance": {"method": "rhf",
                               "scf_energy": {"value": -74.0, "units": "furlong"}},
                "energies": {"total": _hartree(-75.0), "method": "rhf"}}
    assert qvf_reader._root_consistency_errors(manifest) == []
    manifest["provenance"]["scf_energy"]["units"] = "kj_per_mol"
    manifest["energies"]["total"] = {"value": -74.0 / 2625.4996394799,
                                     "units": "hartree"}
    assert qvf_reader._root_consistency_errors(manifest) == []
    manifest["energies"]["total"]["value"] = -0.03
    assert len(qvf_reader._root_consistency_errors(manifest)) == 1
    # Unit strings match case-insensitively: 'EV' is eV, 'Eh' is hartree.
    manifest["provenance"]["scf_energy"] = {"value": -27.211386245988, "units": "EV"}
    manifest["energies"]["total"] = {"value": -1.0, "units": "Eh"}
    assert qvf_reader._root_consistency_errors(manifest) == []


def test_malformed_root_blocks_do_not_crash():
    for manifest in ({"energies": []}, {"energies": {"by_method": "x"}},
                     {"energies": {"by_method": [1, {"method": 2}]},
                      "provenance": {"method": "rhf", "scf_energy": _hartree(1.0)}},
                     {"energies": {"components": [], "total": True},
                      "thermochemistry": {"zpve_eh": 0.1}},
                     {"energies": {"method": "rhf", "total": _hartree(1.0)},
                      "provenance": []}):
        assert qvf_reader._root_consistency_errors(manifest) == []
