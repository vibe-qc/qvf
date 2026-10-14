"""Payload definitions for spectra and analysis members (spec § 5.4, § 5.7).

``$defs/SpectrumPayload``, ``NmrSpectrumPayload``, ``EprSpectrumPayload``,
``BondsPayload``, ``BondOrdersPayload``, ``ScfHistoryPayload``,
``QtaimPayload`` and ``SymmetryPayload`` are loaded by section kind and member
role through ``qvf_reader._PAYLOAD_DEFS``. These tests pin the table to the
schema, prove each definition accepts what the reference writers emit and
rejects a malformed value, and cover the one rule JSON Schema cannot express:
a 1-D spectrum's arrays share one length.
"""

import hashlib
import json
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

import qvf_reader  # noqa: E402
from qvf_reader import _PAYLOAD_DEFS, validate_qvf  # noqa: E402
from qvf_writer import QvfWriter  # noqa: E402

SCHEMA = os.path.normpath(os.path.join(HERE, "..", "qvf_manifest.schema.json"))

WATER = {
    "atoms": [{"symbol": "O", "position": [0.0, 0.0, 0.1173], "atomic_number": 8},
              {"symbol": "H", "position": [0.0, 0.7572, -0.4692],
               "atomic_number": 1}],
    "pbc": [False, False, False],
    "lattice_vectors": None,
}

ONE_D = ("spectra.ir", "spectra.raman", "spectra.uvvis", "spectra.ecd",
         "spectra.vcd", "spectra.generic")


def _archive(tmp_path, kind, role, payload, name="a.qvf"):
    """A water structure plus one section whose ``role`` member is ``payload``.

    Built byte by byte so that payloads the reference writer refuses can be
    tested too. ``kind == "structure"`` adds ``role`` to the structure section.
    """
    sdata = json.dumps(WATER).encode()
    pdata = json.dumps(payload).encode()

    def member(path, data):
        return {"path": path, "format": "json",
                "sha256": hashlib.sha256(data).hexdigest()}

    struct = {"id": "structure", "kind": "structure",
              "members": {"structure": member("structure/structure.json", sdata)}}
    files = {"structure/structure.json": sdata, f"payload/{role}.json": pdata}
    sections = [struct]
    if kind == "structure":
        struct["members"][role] = member(f"payload/{role}.json", pdata)
    else:
        sections.append({"id": "s", "kind": kind,
                         "members": {role: member(f"payload/{role}.json", pdata)}})
    manifest = {"qvf_version": 1,
                "source": {"program": "t", "version": "1", "calculation": "c"},
                "sections": sections}
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for n, d in files.items():
            zf.writestr(n, d)
        zf.writestr("manifest.json", json.dumps(manifest))
    return str(path)


def _payload_errors(report):
    return [f for f in report["findings"] if f["code"] == "E_PAYLOAD_SCHEMA"]


# --- the table ---------------------------------------------------------------

def test_payload_table_names_existing_definitions():
    with open(SCHEMA, encoding="utf-8") as fh:
        defs = json.load(fh)["$defs"]
    for (kind, role), defname in _PAYLOAD_DEFS.items():
        assert defname in defs, (kind, role, defname)
        assert kind in qvf_reader._CANONICAL_KINDS, kind


def test_payload_table_covers_spectra_and_analysis():
    want = {**{(k, "spectrum"): "SpectrumPayload" for k in ONE_D},
            ("spectra.nmr", "spectrum"): "NmrSpectrumPayload",
            ("spectra.epr", "spectrum"): "EprSpectrumPayload",
            ("bonds", "bonds"): "BondsPayload",
            ("structure", "bonds"): "BondsPayload",
            ("bond_orders", "bond_orders"): "BondOrdersPayload",
            ("scf_history", "iterations"): "ScfHistoryPayload",
            ("topology.qtaim", "critical_points"): "QtaimPayload",
            ("structure.symmetry", "data"): "SymmetryPayload"}
    for key, defname in want.items():
        assert _PAYLOAD_DEFS.get(key) == defname, key


# --- each definition: a valid and a malformed payload ------------------------

GOOD = [
    ("spectra.ir", "spectrum", {
        "frequencies": [1595.0, 3657.0], "intensities": [67.0, 4.0],
        "x": [1595.0, 3657.0], "x_units": "cm-1", "y_units": "km_per_mol",
        "peaks": [{"x": 1595.0, "y": 67.0, "width": 10.0, "label": "bend",
                   "assignment": {"mode_index": 0}}],
        "broadening": {"type": "lorentzian", "fwhm": 10.0, "units": "cm-1"},
        "temperature_k": 298.15, "producer_note": "open root"}),
    ("spectra.raman", "spectrum", {
        "frequencies": [1595.0], "intensities": [1.2],
        "raman": {"laser_nm": 532.0, "depolarization_ratios": [0.75]}}),
    ("spectra.uvvis", "spectrum", {
        "frequencies": [7.4], "intensities": [0.05],
        "uvvis": {"x_axis": "energy_ev"},
        "peaks": [{"x": 7.4, "assignment": {"state_index": 1}}]}),
    ("spectra.nmr", "spectrum", {
        "isotope": "1H", "reference": "TMS", "solvent": "chloroform",
        "chemical_shifts": [{"atom_index": 1, "symbol": "H",
                             "isotropic_shift_ppm": 4.6, "anisotropy_ppm": 9.0,
                             "asymmetry": 0.3}],
        "shielding_tensors": [{"atom_index": 1, "isotropic_ppm": 27.2,
                               "tensor": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}],
        "j_couplings": [{"i": 0, "j": 1, "value_hz": 7.2,
                         "isotope_i": "1H", "isotope_j": "1H"}]}),
    ("spectra.epr", "spectrum", {
        "g_tensor": {"matrix": [[2.0, 0, 0], [0, 2.0, 0], [0, 0, 2.01]],
                     "isotropic": 2.0033, "principal": [2.0, 2.0, 2.01]},
        "hyperfine": [{"atom_index": 0, "symbol": "N", "isotope": "14N",
                       "a_iso_mhz": 45.2,
                       "a_tensor_mhz": [[40, 0, 0], [0, 40, 0], [0, 0, 55]],
                       "a_principal_mhz": [40, 40, 55]}],
        "zero_field_splitting": {"d_mhz": 1200.0, "e_mhz": 30.0,
                                 "tensor_mhz": [[-400, 0, 0], [0, -400, 0],
                                                [0, 0, 800]]}}),
    ("bonds", "bonds", {"pairs": [{"i": 0, "j": 1, "order": 1.0},
                                  {"i": 0, "j": 1, "x_image": [0, 0, 1]}],
                        "x_note": "extension keys are allowed"}),
    ("structure", "bonds", {"pairs": [{"i": 0, "j": 1}]}),
    ("bond_orders", "bond_orders", {
        "method": "mayer",
        "pairs": [{"i": 0, "j": 1, "order": -0.02, "distance_ang": 0.96,
                   "symbol_i": "O", "symbol_j": "H"}]}),
    ("scf_history", "iterations", {
        "iterations": [{"iter": 1, "energy_eh": -75.0},
                       {"iter": 2, "energy_eh": -75.9, "delta_e": -0.9,
                        "diis_error": 1e-4, "rms_density_change": 1e-5}],
        "converged": True}),
    ("topology.qtaim", "critical_points", {
        "points": [{"type": "ncp", "position": [0, 0, 0.1173], "atoms": [0]},
                   {"type": "bcp", "position": [0, 0.5, -0.3], "rho": 0.36,
                    "laplacian": -2.4, "ellipticity": 0.02,
                    "atom_pair": [0, 1]}],
        "bond_paths": [{"atoms": [0, 1],
                        "path": [[0, 0, 0.1173], [0, 0.7572, -0.4692]]}],
        "units": {"position": "bohr"}}),
    ("structure.symmetry", "data", {
        "spacegroup_number": 221, "international": "Pm-3m", "hall": "-P 4 2 3",
        "point_group": "Oh", "hermann_mauguin": "m-3m",
        "space_group_number": 221, "space_group_symbol": "Pm-3m",
        "operations": [{"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                        "translation": [0, 0, 0]}],
        "wyckoffs": ["a", "b"], "equivalent_atoms": [0, 1], "symprec": 1e-5,
        "kind": "structure.symmetry", "version": "1.0"}),
]

BAD = [
    ("spectra.ir", "spectrum", {"frequencies": [1.0]}),            # no intensities
    ("spectra.ecd", "spectrum", {"frequencies": ["a"], "intensities": [1]}),
    ("spectra.vcd", "spectrum", {"frequencies": [1.0], "intensities": [1.0],
                                 "broadening": {"type": "voigt"}}),
    ("spectra.generic", "spectrum", {"frequencies": [1.0], "intensities": [1.0],
                                     "peaks": [{"y": 1.0}]}),   # peak without x
    ("spectra.uvvis", "spectrum", {"frequencies": [1.0], "intensities": [1.0],
                                   "uvvis": {"x_axis": "frequency_thz"}}),
    ("spectra.raman", "spectrum", {"frequencies": [1.0], "intensities": [1.0],
                                   "raman": {"laser_nm": 0}}),
    ("spectra.nmr", "spectrum", {"chemical_shifts": [{"atom_index": 1}]}),
    ("spectra.epr", "spectrum", {"g_tensor": {"principal": [2.0, 2.0]}}),
    ("bonds", "bonds", {"pairs": [{"i": 0, "j": 1, "type": "single"}]}),
    ("structure", "bonds", {"pairs": [{"i": -1, "j": 1}]}),
    ("bond_orders", "bond_orders", {"pairs": [{"i": 0, "j": 1, "order": 1}]}),
    ("scf_history", "iterations", {"iterations": [{"iter": 1}]}),
    ("topology.qtaim", "critical_points", {
        "points": [{"type": "bcp", "position": [0, 0]}]}),
    ("structure.symmetry", "data", {"spacegroup_number": 231}),
    ("structure.symmetry", "data", {"space_group_number": 0}),
]


@pytest.mark.parametrize("kind,role,payload", GOOD,
                         ids=[f"{k}:{r}" for k, r, _ in GOOD])
def test_valid_payload_passes(tmp_path, kind, role, payload):
    pytest.importorskip("jsonschema")
    report = validate_qvf(_archive(tmp_path, kind, role, payload))
    assert report["ok"], report["findings"]


@pytest.mark.parametrize("kind,role,payload", BAD,
                         ids=[f"{k}:{r}:{i}" for i, (k, r, _) in enumerate(BAD)])
def test_malformed_payload_fails(tmp_path, kind, role, payload):
    pytest.importorskip("jsonschema")
    report = validate_qvf(_archive(tmp_path, kind, role, payload))
    assert not report["ok"]
    errors = _payload_errors(report)
    assert errors, report["findings"]
    index = 0 if kind == "structure" else 1
    assert errors[0]["where"] == f"/sections/{index}/members/{role}"


# --- the equal-length rule (no JSON Schema needed) ---------------------------

@pytest.mark.parametrize("kind", ONE_D)
@pytest.mark.parametrize("payload", [
    {"frequencies": [1.0, 2.0, 3.0], "intensities": [1.0, 2.0]},
    {"frequencies": [1.0, 2.0], "intensities": [1.0, 2.0], "x": [1.0]},
])
def test_spectrum_lengths_must_match(tmp_path, monkeypatch, kind, payload):
    monkeypatch.setattr(qvf_reader, "_load_schema_validator", lambda: None)
    monkeypatch.setattr(qvf_reader, "_load_payload_validator", lambda name: None)
    report = validate_qvf(_archive(tmp_path, kind, "spectrum", payload))
    assert not report["ok"]
    errors = _payload_errors(report)
    assert len(errors) == 1, report["findings"]
    assert errors[0]["where"] == "/sections/1/members/spectrum"
    assert "same length" in errors[0]["message"]


def test_nmr_and_epr_have_no_length_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(qvf_reader, "_load_payload_validator", lambda name: None)
    report = validate_qvf(_archive(
        tmp_path, "spectra.nmr", "spectrum",
        {"frequencies": [1.0, 2.0], "intensities": [1.0]}))
    assert not _payload_errors(report)


# --- reference writers -------------------------------------------------------

def test_writer_rejects_mismatched_spectrum():
    w = QvfWriter("t", "1")
    with pytest.raises(ValueError, match="same length"):
        w.add_spectrum("spectra.ir", frequencies=[1.0, 2.0], intensities=[1.0])
    with pytest.raises(ValueError, match="same length"):
        w.add_spectrum("spectra.uvvis", payload={
            "frequencies": [1.0], "intensities": [1.0], "x": [1.0, 2.0]})
    with pytest.raises(ValueError, match="frequencies and intensities"):
        w.add_spectrum("spectra.generic", payload={"intensities": [1.0]})


def test_writer_spectrum_conveniences(tmp_path):
    w = QvfWriter("t", "1")
    w.add_structure(WATER["atoms"])
    w.add_spectrum("spectra.ir", frequencies=[1595.0], intensities=[67.0],
                   x_units="cm-1", y_units="km_per_mol",
                   peaks=[{"x": 1595.0, "y": 67.0}],
                   broadening={"type": "gaussian", "fwhm": 8.0})
    with pytest.raises(ValueError, match="1-D spectra"):
        w.add_spectrum("spectra.nmr", payload={"isotope": "1H"}, x_units="ppm")
    with pytest.raises(ValueError, match="both"):
        w.add_spectrum("spectra.raman", payload={
            "frequencies": [1.0], "intensities": [1.0], "x_units": "cm-1"},
            x_units="cm-1")
    path = str(tmp_path / "s.qvf")
    w.write(path)
    assert validate_qvf(path)["ok"]
    with qvf_reader.QvfReader(path) as r:
        sec = next(s for s in r.sections if s["kind"] == "spectra.ir")
        doc = r.read_json(sec["members"]["spectrum"])
    assert doc["x_units"] == "cm-1" and doc["y_units"] == "km_per_mol"
    assert doc["peaks"] == [{"x": 1595.0, "y": 67.0}]
    assert doc["broadening"] == {"type": "gaussian", "fwhm": 8.0}


def test_writer_qtaim_units(tmp_path):
    cps = {"points": [{"type": "bcp", "position": [0, 0.5, -0.3]}]}
    w = QvfWriter("t", "1")
    w.add_structure(WATER["atoms"])
    w.add_topology_qtaim(cps, units={"position": "bohr"})
    with pytest.raises(ValueError, match="both"):
        w.add_topology_qtaim({**cps, "units": {"position": "bohr"}},
                             units={"position": "bohr"}, section_id="q2")
    path = str(tmp_path / "q.qvf")
    w.write(path)
    assert validate_qvf(path)["ok"]
    with qvf_reader.QvfReader(path) as r:
        sec = next(s for s in r.sections if s["kind"] == "topology.qtaim")
        doc = r.read_json(sec["members"]["critical_points"])
    assert doc["units"] == {"position": "bohr"}
    assert "units" not in cps   # the caller's mapping is not modified
