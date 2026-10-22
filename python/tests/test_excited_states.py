"""The ``excited_states`` kind, natural transition orbitals and
``volume.transition_density`` (spec § 5.2, § 5.3, § 5.4, § 5.12; P08).

Covers the writer (round trips and refusals), the payload definitions, the
validator rules that JSON Schema cannot express (state indices, ``n_states``,
the excited-state references, orbital rows, a spectrum's ``states_ref`` and a
transition density's ``excited_states_ref``), and the internal consistency of
the conformance archive ``tddft.qvf``.
"""

import hashlib
import json
import math
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
_CORPUS = os.path.normpath(os.path.join(HERE, "..", "..", "conformance", "corpus"))
_HARTREE_EV = 27.211386245988

WATER = [{"symbol": "O", "position": [0.0, 0.0, 0.1173], "atomic_number": 8},
         {"symbol": "H", "position": [0.0, 0.7572, -0.4692], "atomic_number": 1},
         {"symbol": "H", "position": [0.0, -0.7572, -0.4692], "atomic_number": 1}]
SHELLS = [{"center": 0, "l": 0, "exponents": [1.0], "coefficients": [1.0]},
          {"center": 1, "l": 0, "exponents": [1.0], "coefficients": [1.0]}]


def _codes(report):
    return {f["code"] for f in report["findings"]} - _SCHEMA_CODES


def _where(report, code):
    return sorted(f["where"] for f in report["findings"] if f["code"] == code)


def _ev(value):
    return {"value": value, "units": "ev"}


# --- writer ---------------------------------------------------------------------

def _writer():
    w = QvfWriter(program="t", version="1", calculation="water tddft")
    w.add_structure(WATER)
    w.add_wavefunction_gto(SHELLS, mo_coefficients=np.eye(2), occupations=[2, 0])
    for role, rows in (("hole", np.eye(2)[:1]), ("particle", np.eye(2)[1:])):
        w.add_wavefunction_gto(SHELLS, mo_coefficients=rows, occupations=[1.0],
                               orbital_kind="nto", state_ref="es", state_index=1,
                               nto_role=role, section_id=f"nto_{role}")
    w.add_volume("volume.transition_density", np.zeros((2, 2, 2)), [0, 0, 0],
                 np.eye(3), excited_states_ref="es", state_index=1,
                 section_id="tden")
    return w


STATES = [{"index": 1, "excitation_energy": 7.4, "total_energy": -75.0,
           "multiplicity": 1, "symmetry": "B1", "oscillator_strength": 0.05,
           "rotatory_strength_cgs": 0.0, "transition_dipole": [0.5, 0, 0],
           "transition_magnetic_dipole": [0, 0.2, 0],
           "contributions": [{"from_mo": 0, "to_mo": 1, "weight": 0.99}],
           "nto_ref": "nto_hole", "density_ref": "tden", "x_note": "kept"},
          {"index": 2, "excitation_energy": _ev(9.2)}]


def test_writer_round_trip(tmp_path):
    w = _writer()
    w.add_excited_states(STATES, meta={"method": "tddft", "n_states": 2,
                                       "units": {"oscillator_strength": "dimensionless"}},
                         wavefunction_ref="wf", section_id="es")
    w.add_spectrum("spectra.uvvis", payload={
        "frequencies": [7.4, 9.2], "intensities": [0.05, 0.0],
        "peaks": [{"x": 7.4, "assignment": {"state_index": 1}}],
        "states_ref": "es"})
    path = str(tmp_path / "es.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["errors"]
    with QvfReader(path) as r:
        sections = {s["id"]: s for s in r.sections}
        assert sections["es"]["wavefunction_ref"] == "wf"
        assert sections["tden"]["kind"] == "volume.transition_density"
        assert sections["tden"]["excited_states_ref"] == "es"
        assert sections["tden"]["state_index"] == 1
        payload = r.read_json(sections["es"]["members"]["states"])
        s1 = payload["states"][0]
        assert s1["excitation_energy"] == {"value": 7.4, "units": "ev"}
        assert s1["total_energy"] == {"value": -75.0, "units": "hartree"}
        assert s1["x_note"] == "kept"
        assert payload["states"][1]["excitation_energy"] == _ev(9.2)
        assert payload["meta"]["n_states"] == 2
        hole = r.read_json(sections["nto_hole"]["members"]["mo_metadata"])
        assert hole["orbital_kind"] == "nto"
        assert hole["state_ref"] == "es" and hole["state_index"] == 1
        assert hole["nto_role"] == "hole"
        assert hole["occupation_semantics"] == "transition_weight"
        wf = r.read_json(sections["wf"]["members"]["mo_metadata"])
        assert "occupation_semantics" not in wf and "nto_role" not in wf


@pytest.mark.parametrize("states, kwargs, match", [
    ([{"index": 1, "excitation_energy": 7.4}, {"index": 1, "excitation_energy": 8.0}],
     {}, "unique and ascending"),
    ([{"index": 2, "excitation_energy": 7.4}, {"index": 1, "excitation_energy": 8.0}],
     {}, "unique and ascending"),
    ([{"index": 0, "excitation_energy": 7.4}], {}, ">= 1"),
    ([{"index": True, "excitation_energy": 7.4}], {}, "integer"),
    ([{"index": 1}], {}, "needs index and excitation_energy"),
    ([{"index": 1, "excitation_energy": 7.4, "energy_ev": 7.4}], {}, "unknown field"),
    ([{"index": 1, "excitation_energy": {"value": 7.4, "units": "eV"}}], {},
     "not a QVF unit name"),
    ([{"index": 1, "excitation_energy": 7.4, "oscillator_strength": -0.1}], {}, ">= 0"),
    ([{"index": 1, "excitation_energy": 7.4, "transition_dipole": [1, 2]}], {},
     "three numbers"),
    ([{"index": 1, "excitation_energy": 7.4, "nto_ref": "structure"}], {},
     "wavefunction.gto"),
    ([{"index": 1, "excitation_energy": 7.4, "density_ref": "wf"}], {},
     "volume.transition_density or volume.difference"),
    ([{"index": 1, "excitation_energy": 7.4,
       "contributions": [{"from_mo": 0, "to_mo": 2, "weight": 1.0}]}],
     {"wavefunction_ref": "wf"}, "orbital rows"),
    ([{"index": 1, "excitation_energy": 7.4,
       "contributions": [{"from_mo": 0, "to_mo": 1, "spin": "up", "weight": 1.0}]}],
     {}, "'alpha' or 'beta'"),
    ([{"index": 1, "excitation_energy": 7.4,
       "contributions": [{"from_mo": 0, "to_mo": 1}]}], {}, "weight"),
    ([{"index": 1, "excitation_energy": 7.4}], {"wavefunction_ref": "structure"},
     "wavefunction.gto"),
    ([{"index": 1, "excitation_energy": 7.4}], {"meta": {"n_states": 2}},
     "n_states"),
    ([{"index": 1, "excitation_energy": 7.4}],
     {"meta": {"units": {"oscillator_strength": "ev"}}}, "dimensionless"),
])
def test_writer_refusals(states, kwargs, match):
    w = _writer()
    with pytest.raises(ValueError, match=match):
        w.add_excited_states(states, section_id="bad", **kwargs)
    assert "bad" not in {s["id"] for s in w.build_manifest()["sections"]}


def test_writer_refuses_misplaced_fields():
    w = _writer()
    with pytest.raises(ValueError, match="volume.transition_density only"):
        w.add_volume("volume.density", np.zeros((2, 2, 2)), [0, 0, 0], np.eye(3),
                     excited_states_ref="es")
    with pytest.raises(ValueError, match="needs excited_states_ref"):
        w.add_volume("volume.transition_density", np.zeros((2, 2, 2)), [0, 0, 0],
                     np.eye(3), state_index=1)
    with pytest.raises(ValueError, match="nto_role"):
        w.add_wavefunction_gto(SHELLS, mo_coefficients=np.eye(2), nto_role="hole",
                               section_id="x")
    with pytest.raises(ValueError, match="needs state_ref"):
        w.add_wavefunction_gto(SHELLS, mo_coefficients=np.eye(2), orbital_kind="nto",
                               state_index=1, section_id="y")
    with pytest.raises(ValueError, match="states_ref"):
        w.add_spectrum("spectra.uvvis", payload={"frequencies": [1.0],
                                                  "intensities": [1.0],
                                                  "states_ref": "wf"})


# --- payload definitions ------------------------------------------------------

def _payload_errors(defname, doc):
    pytest.importorskip("jsonschema")
    v = qvf_reader._load_payload_validator(defname)
    assert v is not None
    return [e.message for e in v.iter_errors(doc)]


@pytest.mark.parametrize("doc, ok", [
    ({"states": [{"index": 1, "excitation_energy": _ev(7.4)}]}, True),
    ({"states": [], "meta": {"method": "cis", "n_states": 0, "tda": True,
                             "spin_flip": False, "reference_state": "S0"}}, True),
    ({"states": [{"index": 1, "excitation_energy": _ev(7.4), "x_vendor": 1}],
      "x_extra": {}}, True),
    ({"states": [{"index": 0, "excitation_energy": _ev(7.4)}]}, False),
    ({"states": [{"index": 1}]}, False),
    ({"states": [{"index": 1, "excitation_energy": _ev(7.4), "energy_ev": 7.4}]}, False),
    ({"states": [{"index": 1, "excitation_energy": _ev(7.4),
                  "contributions": [{"from_mo": 0, "to_mo": 1}]}]}, False),
    ({"states": [{"index": 1, "excitation_energy": _ev(7.4),
                  "contributions": [{"from_mo": 0, "to_mo": 1, "weight": 1,
                                     "spin": "gamma"}]}]}, False),
    ({"states": [{"index": 1, "excitation_energy": _ev(7.4),
                  "oscillator_strength": -1}]}, False),
    ({"states": [], "meta": {"units": {"oscillator_strength": "ev"}}}, False),
    ({"states": [], "meta": {"units": {"excitation_energy": "electronvolt"}}}, False),
    ({"states": [], "meta": {"basis": "sto-3g"}}, False),
    ({"meta": {}}, False),
])
def test_excited_states_payload_definition(doc, ok):
    assert (not _payload_errors("ExcitedStatesPayload", doc)) == ok


def test_mo_metadata_nto_fields():
    base = {"n_mo": 1, "spin": "restricted", "orbital_kind": "nto",
            "energies": [0.0], "occupations": [0.9],
            "occupation_semantics": "transition_weight", "state_ref": "es"}
    assert not _payload_errors("MoMetadataPayload",
                               dict(base, state_index=1, nto_role="particle"))
    assert _payload_errors("MoMetadataPayload", dict(base, state_index=0))
    assert _payload_errors("MoMetadataPayload", dict(base, nto_role="electron"))


# --- validator: raw archives the writer would refuse ----------------------------

def _json_bytes(obj):
    return json.dumps(obj).encode("utf-8")


def _member(path, data, fmt="json", dtype=None, shape=None):
    m = {"path": path, "format": fmt, "sha256": hashlib.sha256(data).hexdigest()}
    if dtype is not None:
        m["dtype"], m["shape"] = dtype, shape
    return m


class _Raw:
    """A manifest plus member files, written as a ZIP with the manifest last:
    water, a wavefunction "wf" (2 rows, or 2 alpha and 3 beta rows) and an
    excited_states section "es"."""

    def __init__(self, payload, *, unrestricted=False, **es_fields):
        self.manifest = {"qvf_version": 1,
                         "source": {"program": "t", "version": "1",
                                    "calculation": "excited states"},
                         "sections": []}
        self.files = {}
        self.section("structure", "structure", {"structure": self.json(
            "structure/structure.json",
            {"atoms": WATER, "pbc": [False] * 3, "lattice_vectors": None})})
        basis = {"structure_ref": "structure", "pure": True, "n_ao": 2,
                 "shells": SHELLS}
        if unrestricted:
            mo = {"n_ao": 2, "spin": "unrestricted",
                  "alpha": {"energies": [0, 0], "occupations": [1, 0]},
                  "beta": {"energies": [0, 0, 0], "occupations": [1, 0, 0]}}
            coeffs = {"mo_coefficients_alpha": self.binary("wf/ca.bin", (2, 2)),
                      "mo_coefficients_beta": self.binary("wf/cb.bin", (3, 2))}
        else:
            mo = {"n_mo": 2, "n_ao": 2, "spin": "restricted",
                  "energies": [-0.5, 0.5], "occupations": [2, 0]}
            coeffs = {"mo_coefficients": self.binary("wf/c.bin", (2, 2))}
        self.section("wf", "wavefunction.gto",
                     {"basis": self.json("wf/basis.json", basis),
                      "mo_metadata": self.json("wf/mo.json", mo), **coeffs})
        self.section("es", "excited_states",
                     {"states": self.json("es/states.json", payload)}, **es_fields)

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

    def transition_density(self, **fields):
        grid = {"origin": [0, 0, 0], "voxel_vectors": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "shape": [2, 2, 2]}
        return self.section("td", "volume.transition_density",
                            {"grid": self.json("td/grid.json", grid),
                             "data": self.binary("td/data.bin", (2, 2, 2))}, **fields)

    def uvvis(self, payload):
        return self.section("uv", "spectra.uvvis",
                            {"spectrum": self.json("uv/s.json", payload)})

    def validate(self, tmp_path, name="a.qvf"):
        path = str(tmp_path / name)
        with zipfile.ZipFile(path, "w") as zf:
            for p, data in self.files.items():
                zf.writestr(p, data)
            zf.writestr(zipfile.ZipInfo("manifest.json"), _json_bytes(self.manifest),
                        compress_type=zipfile.ZIP_STORED)
        return validate_qvf(path)


def _state(index, **more):
    return {"index": index, "excitation_energy": _ev(7.0 + index), **more}


def _contrib(to, **more):
    return [{"from_mo": 0, "to_mo": to, "weight": 1.0, **more}]


@pytest.mark.parametrize("payload, fields, unrestricted, want, where", [
    ({"states": [_state(1, contributions=_contrib(1)), _state(2)],
      "meta": {"n_states": 2}}, {"wavefunction_ref": "wf"}, False, set(), None),
    ({"states": [_state(1), _state(2), _state(2)]}, {}, False,
     {"E_MEMBER_MALFORMED"}, "/sections/2/members/states"),
    ({"states": [_state(2), _state(1)]}, {}, False, {"E_MEMBER_MALFORMED"}, None),
    ({"states": [_state(1)], "meta": {"n_states": 3}}, {}, False,
     {"E_MEMBER_MALFORMED"}, None),
    ({"states": [_state(1)]}, {"wavefunction_ref": "structure"}, False,
     {"E_REF_UNRESOLVED"}, "/sections/2/wavefunction_ref"),
    ({"states": [_state(1)]}, {"wavefunction_ref": "nowhere"}, False,
     {"E_REF_UNRESOLVED"}, None),
    ({"states": [_state(1, nto_ref="wf")]}, {}, False, set(), None),
    ({"states": [_state(1, nto_ref="structure")]}, {}, False,
     {"E_REF_UNRESOLVED"}, "/sections/2/members/states"),
    ({"states": [_state(1, density_ref="wf")]}, {}, False, {"E_REF_UNRESOLVED"}, None),
    ({"states": [_state(1, contributions=_contrib(2))]}, {"wavefunction_ref": "wf"},
     False, {"E_MEMBER_MALFORMED"}, None),
    ({"states": [_state(1, contributions=_contrib(2))]}, {}, False, set(), None),
    ({"states": [_state(1, contributions=_contrib(2, spin="beta"))]},
     {"wavefunction_ref": "wf"}, True, set(), None),
    ({"states": [_state(1, contributions=_contrib(2, spin="alpha"))]},
     {"wavefunction_ref": "wf"}, True, {"E_MEMBER_MALFORMED"}, None),
    ({"states": [_state(1, contributions=_contrib(2))]},
     {"wavefunction_ref": "wf"}, True, {"E_MEMBER_MALFORMED"}, None),
])
def test_excited_states_rules(tmp_path, payload, fields, unrestricted, want, where):
    report = _Raw(payload, unrestricted=unrestricted, **fields).validate(tmp_path)
    assert _codes(report) == want, report["findings"]
    if where:
        assert where in _where(report, next(iter(want)))


def test_unknown_meta_unit_is_a_warning(tmp_path):
    report = _Raw({"states": [_state(1)],
                   "meta": {"units": {"excitation_energy": "electronvolt"}}}
                  ).validate(tmp_path)
    assert _codes(report) == {"W_UNIT_UNKNOWN"}


TWO = {"states": [_state(1, density_ref="td"), _state(2)]}


@pytest.mark.parametrize("fields, want, where", [
    ({"excited_states_ref": "es", "state_index": 2}, set(), None),
    ({"excited_states_ref": "es", "state_index": 5}, {"E_REF_UNRESOLVED"},
     "/sections/3/state_index"),
    ({"excited_states_ref": "wf"}, {"E_REF_UNRESOLVED"}, "/sections/3/excited_states_ref"),
])
def test_transition_density_rules(tmp_path, fields, want, where):
    report = _Raw(TWO).transition_density(**fields).validate(tmp_path)
    assert _codes(report) == want, report["findings"]
    if where:
        assert _where(report, "E_REF_UNRESOLVED") == [where]


@pytest.mark.parametrize("state_index, ref, want", [
    (2, "es", set()),
    (7, "es", {"E_REF_UNRESOLVED"}),
    (1, "wf", {"E_REF_UNRESOLVED"}),
])
def test_spectrum_states_ref(tmp_path, state_index, ref, want):
    raw = _Raw(TWO).transition_density().uvvis(
        {"frequencies": [8.0, 9.0], "intensities": [0.1, 0.0],
         "peaks": [{"x": 8.0, "assignment": {"state_index": state_index}}],
         "states_ref": ref})
    report = raw.validate(tmp_path)
    assert _codes(report) == want, report["findings"]
    if want:
        assert _where(report, "E_REF_UNRESOLVED") == ["/sections/4/members/spectrum"]


def test_state_index_needs_excited_states_ref(tmp_path):
    pytest.importorskip("jsonschema")
    report = _Raw(TWO).transition_density(state_index=1).validate(tmp_path)
    assert any(f["code"] == "E_SCHEMA" for f in report["findings"])


# --- the conformance archive ------------------------------------------------------

def test_tddft_corpus_is_internally_consistent():
    path = os.path.join(_CORPUS, "tddft.qvf")
    if not os.path.exists(path):
        pytest.skip("conformance corpus not present (standalone checkout)")
    with QvfReader(path) as r:
        by_id = {s["id"]: s for s in r.sections}
        states = r.read_json(by_id["excited_states"]["members"]["states"])["states"]
        spectrum = r.read_json(by_id["spectra_uvvis"]["members"]["spectrum"])
        wf_rows = by_id["wf"]["members"]["mo_coefficients"]["shape"][0]
        hole = r.read_json(by_id["nto_s1_hole"]["members"]["mo_metadata"])
        particle = r.read_json(by_id["nto_s1_particle"]["members"]["mo_metadata"])
    # The spectrum is the stick spectrum of the table.
    assert spectrum["states_ref"] == "excited_states"
    assert spectrum["frequencies"] == [s["excitation_energy"]["value"] for s in states]
    assert spectrum["intensities"] == [s["oscillator_strength"] for s in states]
    assert [p["assignment"]["state_index"] for p in spectrum["peaks"]] == \
        [s["index"] for s in states]
    for s in states:
        de = s["excitation_energy"]["value"] / _HARTREE_EV
        mu2 = sum(x * x for x in s["transition_dipole"])
        assert math.isclose(s["oscillator_strength"], 2.0 / 3.0 * de * mu2,
                            rel_tol=1e-12, abs_tol=1e-15)
        for c in s.get("contributions", []):
            assert 0 <= c["from_mo"] < wf_rows and 0 <= c["to_mo"] < wf_rows
    # The NTO pair and the transition density point back at state 1.
    assert states[0]["nto_ref"] == "nto_s1_hole"
    assert (hole["nto_role"], particle["nto_role"]) == ("hole", "particle")
    assert hole["occupations"] == particle["occupations"]
    assert math.isclose(sum(hole["occupations"]), 1.0)
    for meta in (hole, particle):
        assert (meta["state_ref"], meta["state_index"]) == ("excited_states", 1)
    tden = by_id[states[0]["density_ref"]]
    assert (tden["excited_states_ref"], tden["state_index"]) == ("excited_states", 1)
