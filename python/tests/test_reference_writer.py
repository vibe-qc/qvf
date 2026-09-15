"""Tests for the standalone QVF reference writer + reader.

These use only pytest + numpy. Two cross-checks run opportunistically when the
optional dependency is importable:

* ``jsonschema`` — full structural schema validation of the manifest.
* ``vibeqc`` — validates the produced archive with vibe-qc's own
  ``validate_qvf`` (the reference producer/consumer), proving the standalone
  writer is contract-compatible with the canonical implementation.
"""

import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

from qvf_writer import QvfWriter, primitive_norm  # noqa: E402
from qvf_reader import QvfReader, validate_qvf  # noqa: E402


def _full_writer() -> QvfWriter:
    """A writer exercising every canonical section kind + root metadata."""
    w = QvfWriter(program="test-code", version="9.9", calculation="everything")
    origin = [-2.0, -2.0, -2.0]
    vox = [[0.2, 0, 0], [0, 0.2, 0], [0, 0, 0.2]]
    dens = np.abs(np.random.default_rng(1).standard_normal((8, 8, 8))).astype(np.float32)

    w.add_structure(
        [{"symbol": "O", "position": [0, 0, 0.117], "atomic_number": 8,
          "atom_name": "O", "residue_name": "HOH", "residue_seq": 1,
          "chain_id": "A", "b_factor": 11.25},
         {"symbol": "H", "position": [0, 0.757, -0.469], "atomic_number": 1},
         {"symbol": "H", "position": [0, -0.757, -0.469], "atomic_number": 1}],
        bonds=[{"i": 0, "j": 1, "order": 1.0}],
        biomolecule={
            "chains": ["A"],
            "residues": [{"name": "HOH", "seq": 1, "chain": "A",
                          "atom_indices": [0, 1, 2]}],
            "secondary_structure": [{"type": "coil", "chain": "A",
                                     "start_seq": 1, "end_seq": 1}],
            "b_factors": [11.25, 14.0, 13.5],
        },
    )
    w.add_bonds([{"i": 0, "j": 2, "order": 1.0}])
    w.add_bond_orders("mayer", [{"i": 0, "j": 1, "order": 0.98, "distance_ang": 0.96}])
    a = w.add_density(dens, origin, vox, label="rho")
    b = w.add_orbital(dens, origin, vox, label="homo", component="real")
    w.add_volume("volume.spin", dens, origin, vox)
    w.add_volume("volume.elf", dens, origin, vox)
    w.add_volume("volume.potential", dens.astype(np.float64), origin, vox, dtype="float64")
    w.add_volume("volume.rdg", dens, origin, vox)
    w.add_volume("volume.generic", dens, origin, vox, label="custom")
    w.add_volume("volume.difference", dens, origin, vox, operand_a=a, operand_b=b,
                 description="rho - homo")
    w.add_basis_ao({"atom_index": 0, "atom_symbol": "O", "shell_index": 0,
                    "primitive_index": 0, "angular_momentum": [0, 0],
                    "shell_type": "s", "exponent": 130.7, "coefficient": 0.15,
                    "is_primitive": False, "is_contracted": True, "ao_index": 0},
                   dens, origin, vox)

    shells = [{"center": 0, "l": 0, "exponents": [1.0, 0.5],
               "coefficients": [0.6, 0.4]},
              {"center": 0, "l": 1, "exponents": [1.0], "coefficients": [1.0]}]
    C = np.random.default_rng(2).standard_normal((4, 4))
    w.add_wavefunction_gto(shells, mo_coefficients=C, energies=[-1, -0.5, 0.5, 1],
                           occupations=[2, 2, 0, 0])

    w.add_atom_properties(mulliken_charge=[-0.7, 0.35, 0.35],
                          spin_population=[0.0, 0.0, 0.0])
    coords = np.random.default_rng(3).standard_normal((5, 3, 3))
    tid = w.add_trajectory({"symbols": ["O", "H", "H"],
                            "energies": [-74.9, -74.95, -74.96, -74.962, -74.963]},
                           coords)
    w.add_reaction_waypoints(tid, {"waypoints": [{"frame_index": 0, "label": "R",
                                                  "kind": "reactant"}]})
    w.add_reaction_path({"symbols": ["O", "H", "H"],
                         "waypoints": [{"frame_index": 0, "label": "R",
                                        "kind": "reactant"}]}, coords)
    w.add_scan_surface({"axis_a_label": "r1", "axis_b_label": "r2"},
                       [0.0, 1.0], [0.0, 1.0], np.zeros((2, 2)))
    disp = np.random.default_rng(4).standard_normal((3, 3, 3))
    w.add_vibrations({"symbols": ["O", "H", "H"], "frequencies": [1595, 3657, 3756]},
                     disp)
    for kind in ("spectra.ir", "spectra.raman", "spectra.uvvis", "spectra.ecd",
                 "spectra.vcd", "spectra.generic"):
        w.add_spectrum(kind, frequencies=[100.0, 200.0], intensities=[1.0, 2.0])
    w.add_spectrum("spectra.nmr", payload={"isotope": "1H", "reference": "TMS",
                   "chemical_shifts": [{"atom_index": 1, "symbol": "H",
                                        "isotropic_shift_ppm": 4.6}]})
    w.add_spectrum("spectra.epr", payload={
        "g_tensor": {"principal": [2.0023, 2.0021, 2.0089], "isotropic": 2.0044},
        "hyperfine": [{"atom_index": 0, "symbol": "N", "a_iso_mhz": 45.2}],
        "zero_field_splitting": {"d_mhz": 1200.0, "e_mhz": 30.0}})
    eig = np.random.default_rng(5).standard_normal((1, 10, 4))
    w.add_bands({"n_spin": 1, "n_kpoints": 10, "n_bands": 4,
                 "segments": [{"label_start": "G", "label_end": "X",
                               "k_start": [0, 0, 0], "k_end": [0.5, 0, 0],
                               "n_points": 10}]}, eig)
    w.add_dos_total([-2, -1, 0, 1, 2], [0.1, 0.5, 1.0, 0.5, 0.1], smearing=0.05,
                    fermi_energy_ev=0.0, n_electrons=10.0)
    w.add_dos_projected([-2, -1, 0, 1, 2], np.zeros((2, 5)),
                        channels=[{"atom_index": 0, "symbol": "O", "l": 0,
                                   "label": "O-2s"},
                                  {"atom_index": 0, "symbol": "O", "l": 1,
                                   "label": "O-2p"}])
    w.add_dos_coop_cohp("dos.coop", [-1, 0, 1], np.zeros((1, 3)), np.zeros((1, 3)),
                        {"pairs": [[0, 1]]})
    w.add_dos_coop_cohp("dos.cohp", [-1, 0, 1], np.zeros((1, 3)), np.zeros((1, 3)),
                        {"pairs": [[0, 1]]})
    w.add_structure_symmetry({"space_group": "C2v", "point_group": "C2v"})
    w.add_scf_history([{"iter": 1, "energy_eh": -74.9, "delta_e": 1.0,
                        "diis_error": 0.1}])
    w.add_citations("@article{x2026, title={T}, author={A}, year={2026}}")
    w.add_run_record(program="test-code", program_version="9.9",
                     command="test-code water.inp", exit_status=0,
                     started_utc="2026-07-24T12:00:00Z",
                     finished_utc="2026-07-24T12:00:41Z", sequence=0,
                     input_text="! RHF STO-3G\n* xyz 0 1\nO 0 0 0\n*\n",
                     log_text="SCF CONVERGED\nFINAL ENERGY -74.96\n",
                     files={"input": {"filename": "water.inp"},
                            "log": {"filename": "water.out"},
                            "attachment.geom": {"filename": "water.xyz"}},
                     attachments={"geom": b"1\nwater\nO 0 0 0\n"})
    fs = np.random.default_rng(6).standard_normal((4, 4, 4, 2))
    w.add_fermi_surface({"nk1": 4, "nk2": 4, "nk3": 4, "n_spin": 1,
                         "fermi_energy_ev": 0.0, "band_indices": [3, 4],
                         "lattice_vectors": [[4.2, 0, 0], [0, 4.2, 0], [0, 0, 4.2]]},
                        fs)
    w.add_phonon_bands({"n_atoms": 2, "n_modes": 6, "has_eigenvectors": False,
                        "segments": [{"label_start": "G", "label_end": "X",
                                      "k_start": [0, 0, 0], "k_end": [0.5, 0, 0],
                                      "n_points": 10}]},
                       np.abs(np.random.default_rng(7).standard_normal((10, 6))))
    w.add_phonon_dos({"n_atoms": 2, "n_modes": 6}, [0, 100, 200],
                     [0.1, 1.0, 0.1])
    w.add_equation_of_state([90, 100, 110], [-5.1, -5.2, -5.15],
                            {"model": "birch_murnaghan", "V0": 100.0, "E0": -5.2,
                             "B0": 74.0, "B0_prime": 4.0, "energy_unit": "eV",
                             "volume_unit": "angstrom^3", "pressure_unit": "GPa"})
    w.add_topology_qtaim({"points": [{"type": "bcp", "position": [0.7, 0, 0],
                                      "rho": 0.26, "laplacian": -0.54,
                                      "atom_pair": [0, 1]}]})
    w.set_extensions({"x_orca": {"version": "1.0", "critical": True}})
    w.add_vendor_section("x_orca.epr",
                         json_members={"epr": {"g_tensor": [[2.0, 0, 0], [0, 2.0, 0],
                                                            [0, 0, 2.0]]}},
                         critical=True)
    w.set_thermochemistry(zpve_eh=0.021, gibbs_free_energy_eh=-74.94,
                          temperature_k=298.15, pressure_atm=1.0)
    w.set_constraints(frozen_atoms=[0])
    w.set_viewer_defaults({"auto_open": [a]})
    return w


def test_all_kinds_validate(tmp_path):
    w = _full_writer()
    path = str(tmp_path / "full.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["errors"]
    # Every canonical kind + one vendor section present.
    kinds = {s["kind"] for s in w.build_manifest()["sections"]}
    assert "wavefunction.gto" in kinds
    assert "x_orca.epr" in kinds
    assert len(w.build_manifest()["sections"]) >= 35


def test_roundtrip_binary_values(tmp_path):
    w = QvfWriter(program="t", version="1")
    coords = np.arange(30, dtype=np.float64).reshape(5, 2, 3)
    w.add_structure([{"symbol": "H", "position": [0, 0, 0], "atomic_number": 1},
                     {"symbol": "H", "position": [0, 0, 0.74], "atomic_number": 1}])
    w.add_trajectory({"symbols": ["H", "H"]}, coords)
    path = str(tmp_path / "t.qvf")
    w.write(path)
    with QvfReader(path) as r:
        traj = next(s for s in r.sections if s["kind"] == "trajectory")
        got = r.read_array(traj["members"]["coords"])
        np.testing.assert_array_equal(got, coords)


def test_wavefunction_primitive_norm_division(tmp_path):
    # A libint-normalized coefficient of 1.0 on an s primitive (alpha=1) must be
    # divided by primitive_norm(1, 0) on the way out.
    shells = [{"center": 0, "l": 0, "exponents": [1.0], "coefficients": [1.0]}]
    w = QvfWriter(program="t", version="1")
    w.add_structure([{"symbol": "H", "position": [0, 0, 0], "atomic_number": 1}])
    w.add_wavefunction_gto(shells, mo_coefficients=np.eye(1),
                           coeffs_are_libint_normalized=True)
    path = str(tmp_path / "wf.qvf")
    w.write(path)
    with QvfReader(path) as r:
        wf = next(s for s in r.sections if s["kind"] == "wavefunction.gto")
        basis = r.read_json(wf["members"]["basis"])
        expected = 1.0 / primitive_norm(1.0, 0)
        assert abs(basis["shells"][0]["coefficients"][0] - expected) < 1e-12


class TestPeriodicReactionPathLattice:
    """`reaction.path` carries an optional `lattice` member under qvf_version 1.

    Governance ruling 2026-07-10: a periodic reaction path is signalled by the
    presence of `lattice`, never by a manifest version bump.
    """

    @staticmethod
    def _writer():
        w = QvfWriter(program="t", version="1", calculation="neb")
        w.add_structure([{"symbol": "H", "position": [0, 0, 0], "atomic_number": 1}])
        return w, np.zeros((5, 1, 3))

    def test_fixed_cell_lattice_round_trips(self, tmp_path):
        w, coords = self._writer()
        lat = np.eye(3) * 5.0
        w.add_reaction_path({"symbols": ["H"]}, coords, lattice=lat)
        path = str(tmp_path / "rp.qvf")
        w.write(path)
        assert validate_qvf(path)["ok"]
        # Archive stays v1 — the lattice member, not a version bump, marks it periodic.
        with QvfReader(path) as r:
            assert r.manifest["qvf_version"] == 1
            sec = next(s for s in r.sections if s["kind"] == "reaction.path")
            assert "lattice" in sec["members"]
            np.testing.assert_allclose(r.read_array(sec["members"]["lattice"]), lat)

    def test_per_frame_lattice_round_trips(self, tmp_path):
        w, coords = self._writer()
        lat = np.stack([np.eye(3) * (1.0 + i) for i in range(5)])
        w.add_reaction_path({"symbols": ["H"]}, coords, lattice=lat)
        path = str(tmp_path / "rp2.qvf")
        w.write(path)
        assert validate_qvf(path)["ok"]

    def test_molecular_path_has_no_lattice(self, tmp_path):
        w, coords = self._writer()
        w.add_reaction_path({"symbols": ["H"]}, coords)
        path = str(tmp_path / "rp3.qvf")
        w.write(path)
        assert validate_qvf(path)["ok"]
        with QvfReader(path) as r:
            sec = next(s for s in r.sections if s["kind"] == "reaction.path")
            assert "lattice" not in sec["members"]

    def test_bad_lattice_shape_rejected(self):
        w, coords = self._writer()
        with pytest.raises(ValueError):
            w.add_reaction_path({}, coords, lattice=np.zeros((2, 2)))

    def test_per_frame_lattice_frame_count_must_match(self):
        w, coords = self._writer()
        with pytest.raises(ValueError):
            w.add_reaction_path({}, coords, lattice=np.zeros((3, 3, 3)))


def test_duplicate_id_rejected():
    w = QvfWriter(program="t", version="1")
    w.add_structure([{"symbol": "H", "position": [0, 0, 0], "atomic_number": 1}],
                    section_id="s")
    with pytest.raises(ValueError):
        w.add_bonds([{"i": 0, "j": 0, "order": 1.0}], section_id="s")


def test_bad_dtype_rejected():
    w = QvfWriter(program="t", version="1")
    with pytest.raises(ValueError):
        w.add_volume("volume.density", np.zeros((2, 2, 2)), [0, 0, 0],
                     [[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype="float16")


def test_manifest_schema_conformance(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    import json
    schema_path = os.path.join(HERE, "..", "..", "spec", "qvf_manifest.schema.json")
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    validator = jsonschema.Draft202012Validator(schema)
    manifest = _full_writer().build_manifest()
    errs = sorted(validator.iter_errors(manifest), key=lambda e: list(e.path))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs[:20])


def test_vibeqc_validate_qvf_accepts_our_archive(tmp_path):
    try:
        import vibeqc.output.formats.qvf as vibeqc_qvf
    except ImportError as exc:
        pytest.skip(f"vibeqc not importable ({exc}); cross-check deferred to M6")
    path = str(tmp_path / "full.qvf")
    _full_writer().write(path)
    report = vibeqc_qvf.validate_qvf(path)
    # vibe-qc's validate_qvf returns a report dict; accept either {"valid": ...}
    # or {"ok": ...} conventions.
    ok = report.get("valid", report.get("ok"))
    assert ok, report


def test_bundled_schema_matches_canonical():
    """Guard: the bundled schema copy is byte-identical to vibe-qc's canonical
    schema when the repo is available (skipped in a standalone checkout)."""
    canonical = os.path.join(HERE, "..", "..", "..", "python", "vibeqc", "output",
                             "formats", "qvf_manifest.schema.json")
    if not os.path.exists(canonical):
        pytest.skip("canonical schema not present (standalone checkout)")
    bundled = os.path.join(HERE, "..", "..", "spec", "qvf_manifest.schema.json")
    with open(canonical, "rb") as a, open(bundled, "rb") as b:
        assert a.read() == b.read(), "bundled schema has drifted from canonical"


class TestBiomoleculeMetadata:
    """Spec § 5.1 biomolecule fields: section peer keys + per-atom carriers."""

    def _structure_section(self, tmp_path, **kwargs):
        w = QvfWriter(program="t", version="0", calculation="bio")
        w.add_structure(
            [{"symbol": "C", "position": [0, 0, 0], "atomic_number": 6,
              "atom_name": "CA", "residue_name": "ALA", "residue_seq": 4,
              "chain_id": "B", "b_factor": 21.5}],
            **kwargs)
        path = os.path.join(str(tmp_path), "bio.qvf")
        w.write(path)
        validate_qvf(path)
        r = QvfReader(path)
        section = next(s for s in r.sections if s["kind"] == "structure")
        return section, r.read_json(section["members"]["structure"])

    def test_all_four_peer_fields_round_trip(self, tmp_path):
        section, _ = self._structure_section(
            tmp_path,
            biomolecule={
                "chains": ["B"],
                "residues": [{"name": "ALA", "seq": 4, "chain": "B",
                              "atom_indices": [0]}],
                "secondary_structure": [{"type": "helix", "chain": "B",
                                         "start_seq": 4, "end_seq": 4}],
                "b_factors": [21.5],
            })
        assert section["chains"] == ["B"]
        assert section["residues"][0]["atom_indices"] == [0]
        assert section["secondary_structure"][0]["type"] == "helix"
        assert section["b_factors"] == [21.5]

    def test_per_atom_fields_pass_through_to_payload(self, tmp_path):
        _, payload = self._structure_section(tmp_path)
        atom = payload["atoms"][0]
        assert atom["atom_name"] == "CA"
        assert atom["residue_name"] == "ALA"
        assert atom["residue_seq"] == 4
        assert atom["chain_id"] == "B"
        assert atom["b_factor"] == 21.5

    def test_plain_structure_carries_none_of_them(self, tmp_path):
        w = QvfWriter(program="t", version="0", calculation="plain")
        w.add_structure([{"symbol": "C", "position": [0, 0, 0],
                          "atomic_number": 6}])
        path = os.path.join(str(tmp_path), "plain.qvf")
        w.write(path)
        validate_qvf(path)
        r = QvfReader(path)
        section = next(s for s in r.sections if s["kind"] == "structure")
        for key in ("chains", "residues", "secondary_structure", "b_factors"):
            assert key not in section
        atom = r.read_json(section["members"]["structure"])["atoms"][0]
        assert set(atom) == {"symbol", "position", "atomic_number"}


class TestRunRecord:
    def test_requires_program_and_payload(self):
        w = QvfWriter(program="t", version="1")
        with pytest.raises(ValueError):
            w.add_run_record(program="", input_text="x")
        with pytest.raises(ValueError):
            w.add_run_record(program="t")

    def test_roundtrip_text_and_metadata(self, tmp_path):
        w = QvfWriter(program="packer", version="0.1", calculation="repack")
        w.add_run_record(program="orca", program_version="6.0.1",
                         command="orca water.inp", exit_status=0,
                         input_text="! RHF STO-3G\n",
                         log_text="FINAL SINGLE POINT ENERGY -74.96\n")
        path = str(tmp_path / "r.qvf")
        w.write(path)
        report = validate_qvf(path)
        assert report["ok"], report["errors"]
        with QvfReader(path) as r:
            s = next(x for x in r.sections if x["kind"] == "run.record")
            # section program identity is independent of root source.program
            assert s["program"] == "orca"
            assert r.manifest["source"]["program"] == "packer"
            assert r.read_member(s["members"]["input"]).decode("utf-8") == \
                "! RHF STO-3G\n"
            assert "ENERGY" in r.read_member(s["members"]["log"]).decode("utf-8")

    def test_validator_flags_non_utf8_log(self, tmp_path):
        w = QvfWriter(program="t", version="1")
        w.add_run_record(program="t", log_text=b"\xff\xfe\x00 not utf-8")
        path = str(tmp_path / "bad.qvf")
        w.write(path)
        report = validate_qvf(path)
        assert not report["ok"]
        assert any("UTF-8" in e for e in report["errors"]), report["errors"]

    def test_validator_flags_dangling_files_role(self, tmp_path):
        w = QvfWriter(program="t", version="1")
        w.add_run_record(program="t", input_text="x",
                         files={"log": {"filename": "a.out"}})
        path = str(tmp_path / "dangling.qvf")
        w.write(path)
        report = validate_qvf(path)
        assert not report["ok"]
        assert any("files index" in e for e in report["errors"]), \
            report["errors"]

    def test_attachments_may_be_arbitrary_bytes(self, tmp_path):
        w = QvfWriter(program="t", version="1")
        w.add_run_record(program="t", input_text="x",
                         attachments={"restart": b"\x00\x01\xfe\xff"})
        path = str(tmp_path / "att.qvf")
        w.write(path)
        report = validate_qvf(path)
        assert report["ok"], report["errors"]
