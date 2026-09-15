#!/usr/bin/env python3
"""Generate the QVF conformance golden corpus.

Writes a set of fixed reference ``.qvf`` archives under ``corpus/``, each paired
with a ``.expected.json`` describing the values a conforming consumer must decode
from it. The archives are **frozen test vectors**: they define the format, not
the writer, so they are committed and only regenerated when the corpus is
intentionally extended (a producer proves conformance by *decoding to the same
expected values*, not by reproducing bytes).

Run:  python generate_corpus.py

This uses the reference Python writer as the source of truth. The runner
(``run_conformance.py``) is what every consumer implements to self-certify.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "python")))
from qvf_writer import QvfWriter, primitive_norm  # noqa: E402

_PROGRAM = "qvf-conformance"
_VERSION = "0.1.0"


def _write(name, writer, checks, description):
    """Write one archive + its expected.json."""
    path = os.path.join(CORPUS, f"{name}.qvf")
    writer.write(path)
    manifest = writer.build_manifest()
    expected = {
        "archive": f"{name}.qvf",
        "description": description,
        "source_program": _PROGRAM,
        "kinds": sorted({s["kind"] for s in manifest["sections"]}),
        "checks": checks,
    }
    with open(os.path.join(CORPUS, f"{name}.expected.json"), "w",
              encoding="utf-8") as fh:
        json.dump(expected, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(f"  {name}.qvf  ({len(manifest['sections'])} sections, "
          f"{len(checks)} checks)")


def build() -> None:
    os.makedirs(CORPUS, exist_ok=True)

    # 1) minimal molecular structure + explicit bonds
    w = QvfWriter(_PROGRAM, _VERSION, "water")
    w.add_structure(
        [{"symbol": "O", "position": [0.0, 0.0, 0.1173], "atomic_number": 8},
         {"symbol": "H", "position": [0.0, 0.7572, -0.4692], "atomic_number": 1},
         {"symbol": "H", "position": [0.0, -0.7572, -0.4692], "atomic_number": 1}],
        bonds=[{"i": 0, "j": 1, "order": 1.0}, {"i": 0, "j": 2, "order": 1.0}])
    _write("structure_water", w, [
        {"manifest_pointer": ["qvf_version"], "equals": 1},
        {"manifest_pointer": ["source", "program"], "equals": _PROGRAM},
        {"section": "structure", "member": "structure",
         "json_pointer": ["atoms", 0, "symbol"], "equals": "O"},
        {"section": "structure", "member": "structure",
         "json_pointer": ["atoms", 1, "position", 1], "equals": 0.7572,
         "tol": 1e-9},
        {"section": "structure", "member": "structure",
         "json_pointer": ["atoms", 0, "atomic_number"], "equals": 8},
        {"section": "structure", "member": "bonds",
         "json_pointer": ["pairs", 0, "order"], "equals": 1.0, "tol": 1e-9},
    ], "Minimal molecular structure (H2O) with explicit bonds; Angstrom.")

    # 2) periodic structure with a cubic lattice
    w = QvfWriter(_PROGRAM, _VERSION, "mgo")
    w.add_structure(
        [{"symbol": "Mg", "position": [0.0, 0.0, 0.0], "atomic_number": 12},
         {"symbol": "O", "position": [2.1, 2.1, 2.1], "atomic_number": 8}],
        pbc=[True, True, True],
        lattice_vectors=[[4.2, 0, 0], [0, 4.2, 0], [0, 0, 4.2]])
    _write("structure_periodic", w, [
        {"section": "structure", "member": "structure",
         "json_pointer": ["pbc", 0], "equals": True},
        {"section": "structure", "member": "structure",
         "json_pointer": ["lattice_vectors", 0, 0], "equals": 4.2, "tol": 1e-9},
    ], "Periodic structure (MgO) with a cubic lattice; row vectors, Angstrom.")

    # 2b) 2-D slab. pbc marks the third axis aperiodic, so lattice row 2 is a
    # synthesized normal that a consumer must not draw, tile, or measure. Its
    # length is deliberately vacuum-gap-sized (15.875 A ~ 30 bohr): a reader
    # keying off lattice geometry instead of off pbc gets this archive wrong.
    w = QvfWriter(_PROGRAM, _VERSION, "graphene")
    w.add_structure(
        [{"symbol": "C", "position": [0.0, 0.0, 0.0], "atomic_number": 6},
         {"symbol": "C", "position": [1.23, 0.7101, 0.0], "atomic_number": 6}],
        pbc=[True, True, False],
        lattice_vectors=[[2.46, 0.0, 0.0], [1.23, 2.1304, 0.0],
                         [0.0, 0.0, 15.875]],
        dimensionality=2)
    _write("structure_slab_2d", w, [
        {"section": "structure", "member": "structure",
         "json_pointer": ["pbc", 0], "equals": True},
        {"section": "structure", "member": "structure",
         "json_pointer": ["pbc", 1], "equals": True},
        {"section": "structure", "member": "structure",
         "json_pointer": ["pbc", 2], "equals": False},
        {"section": "structure", "member": "structure",
         "json_pointer": ["dimensionality"], "equals": 2},
        {"section": "structure", "member": "structure",
         "json_pointer": ["lattice_vectors", 2, 2], "equals": 15.875,
         "tol": 1e-9},
    ], "2-D slab (graphene): pbc [true, true, false], dimensionality 2. Lattice "
       "row 2 is a non-physical synthesized normal, present only so the matrix "
       "stays full-rank 3x3; it is not a cell edge.")

    # 3) restricted wavefunction.gto with the primitive-norm divide
    shells = [{"center": 0, "l": 0, "exponents": [1.0, 0.5],
               "coefficients": [0.6, 0.4]},
              {"center": 0, "l": 1, "exponents": [1.0], "coefficients": [1.0]}]
    C = np.eye(4, dtype=np.float64)
    w = QvfWriter(_PROGRAM, _VERSION, "wf_rhf")
    w.add_structure([{"symbol": "Ne", "position": [0, 0, 0], "atomic_number": 10}])
    w.add_wavefunction_gto(shells, mo_coefficients=C, energies=[-1, -0.5, 0.5, 1],
                           occupations=[2, 2, 0, 0],
                           coeffs_are_libint_normalized=True)
    # The stored coefficient must be the input divided by the primitive norm.
    expect_c0 = 0.6 / primitive_norm(1.0, 0)
    _write("wavefunction_rhf", w, [
        {"section": "wf", "member": "basis", "json_pointer": ["n_ao"], "equals": 4},
        {"section": "wf", "member": "basis",
         "json_pointer": ["shells", 0, "coefficients", 0], "equals": expect_c0,
         "tol": 1e-9},
        {"section": "wf", "member": "basis",
         "json_pointer": ["shells", 0, "pure"], "equals": True},
        {"section": "wf", "member": "mo_metadata",
         "json_pointer": ["spin"], "equals": "restricted"},
        {"section": "wf", "member": "mo_coefficients", "binary_index": [0, 0],
         "equals": 1.0, "tol": 1e-12},
    ], "Restricted wavefunction.gto; coefficients on N_i-normalized primitives "
       "(the N_i divide is the key contract; see spec Appendix A.1).")

    # 4) IR spectrum (frequency/intensity) + provenance + dipole (root metadata)
    w = QvfWriter(_PROGRAM, _VERSION, "ir")
    w.add_structure([{"symbol": "C", "position": [0, 0, 0], "atomic_number": 6},
                     {"symbol": "O", "position": [0, 0, 1.13], "atomic_number": 8}])
    w.add_spectrum("spectra.ir", frequencies=[2143.0], intensities=[500.0])
    w.set_provenance(method="RKS", functional="PBE", basis="def2-SVP",
                     scf_converged=True, scf_energy_eh=-113.3)
    w.set_dipole_moment(total_debye=0.11, vector_debye=[0.0, 0.0, 0.11],
                        origin="center_of_mass")
    _write("spectra_ir", w, [
        {"section": "spectra_ir", "member": "spectrum",
         "json_pointer": ["frequencies", 0], "equals": 2143.0, "tol": 1e-9},
        {"section": "spectra_ir", "member": "spectrum",
         "json_pointer": ["intensities", 0], "equals": 500.0, "tol": 1e-9},
        {"manifest_pointer": ["provenance", "functional"], "equals": "PBE"},
        {"manifest_pointer": ["provenance", "scf_energy", "value"],
         "equals": -113.3, "tol": 1e-9},
        {"manifest_pointer": ["provenance", "scf_energy", "units"], "equals": "Eh"},
        {"manifest_pointer": ["dipole_moment", "total_debye"], "equals": 0.11,
         "tol": 1e-9},
    ], "IR spectrum (cm^-1 / km*mol^-1) with root provenance + dipole metadata.")

    # 5) canonical EPR (object-shaped spectrum)
    w = QvfWriter(_PROGRAM, _VERSION, "epr")
    w.add_structure([{"symbol": "N", "position": [0, 0, 0], "atomic_number": 7}])
    w.add_spectrum("spectra.epr", payload={
        "g_tensor": {"principal": [2.0023, 2.0021, 2.0089], "isotropic": 2.0044},
        "hyperfine": [{"atom_index": 0, "symbol": "N", "a_iso_mhz": 45.2}],
        "zero_field_splitting": {"d_mhz": 1200.0, "e_mhz": 30.0}})
    _write("spectra_epr", w, [
        {"section": "spectra_epr", "member": "spectrum",
         "json_pointer": ["g_tensor", "principal", 2], "equals": 2.0089,
         "tol": 1e-9},
        {"section": "spectra_epr", "member": "spectrum",
         "json_pointer": ["zero_field_splitting", "d_mhz"], "equals": 1200.0,
         "tol": 1e-9},
    ], "Canonical spectra.epr: g-tensor / hyperfine / ZFS; g dimensionless, "
       "A and D in MHz.")

    # 6) volume.density grid (bohr) — binary + grid JSON contract
    rng = np.random.default_rng(0)
    dens = rng.random((6, 6, 6)).astype(np.float32)
    w = QvfWriter(_PROGRAM, _VERSION, "density")
    w.add_structure([{"symbol": "H", "position": [0, 0, 0], "atomic_number": 1}])
    w.add_density(dens, origin=[-1.5, -1.5, -1.5],
                  voxel_vectors=[[0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5]],
                  label="rho", section_id="rho")
    _write("volume_density", w, [
        {"section": "rho", "member": "grid",
         "json_pointer": ["shape", 0], "equals": 6},
        {"section": "rho", "member": "grid",
         "json_pointer": ["voxel_vectors", 0, 0], "equals": 0.5, "tol": 1e-9},
        {"section": "rho", "member": "data", "binary_index": [1, 2, 3],
         "equals": float(dens[1, 2, 3]), "tol": 1e-6},
    ], "volume.density grid; origin + voxel_vectors in bohr, float32 [nx,ny,nz].")

    # 7) band structure — rank-3 eigenvalue tensor (eV)
    eig = np.linspace(-5.0, 5.0, 1 * 8 * 3).reshape(1, 8, 3).astype(np.float64)
    w = QvfWriter(_PROGRAM, _VERSION, "bands")
    w.add_structure([{"symbol": "Si", "position": [0, 0, 0], "atomic_number": 14}],
                    pbc=[True, True, True],
                    lattice_vectors=[[3.8, 0, 0], [0, 3.8, 0], [0, 0, 3.8]])
    w.add_bands({"n_spin": 1, "n_kpoints": 8, "n_bands": 3, "fermi": 0.0,
                 "segments": [{"label_start": "G", "label_end": "X",
                               "k_start": [0, 0, 0], "k_end": [0.5, 0, 0],
                               "n_points": 8}]}, eig, section_id="bands0")
    _write("bands", w, [
        {"section": "bands0", "member": "kpath",
         "json_pointer": ["n_bands"], "equals": 3},
        {"section": "bands0", "member": "eigenvalues", "binary_index": [0, 0, 0],
         "equals": float(eig[0, 0, 0]), "tol": 1e-9},
        {"section": "bands0", "member": "eigenvalues", "binary_index": [0, 7, 2],
         "equals": float(eig[0, 7, 2]), "tol": 1e-9},
    ], "Band structure; eigenvalues [n_spin, n_kpoints, n_bands] in eV.")

    # 8) analysis: atom_properties + bond_orders + scf_history
    w = QvfWriter(_PROGRAM, _VERSION, "analysis")
    w.add_structure([{"symbol": "O", "position": [0, 0, 0], "atomic_number": 8},
                     {"symbol": "H", "position": [0, 0, 0.96], "atomic_number": 1}])
    w.add_atom_properties(mulliken_charge=[-0.34, 0.34],
                          loewdin_charge=[-0.20, 0.20])
    w.add_bond_orders("mayer", [{"i": 0, "j": 1, "order": 0.98,
                                 "distance_ang": 0.96}])
    w.add_scf_history([{"iter": 1, "energy_eh": -75.0, "delta_e": 1.0,
                        "diis_error": 0.1},
                       {"iter": 2, "energy_eh": -75.9, "delta_e": -0.9,
                        "diis_error": 1e-4}])
    _write("analysis", w, [
        {"section": "atom_properties", "member": "mulliken_charge",
         "binary_index": [0], "equals": -0.34, "tol": 1e-9},
        {"section": "bond_orders", "member": "bond_orders",
         "json_pointer": ["pairs", 0, "order"], "equals": 0.98, "tol": 1e-9},
        {"section": "scf_history", "member": "iterations",
         "json_pointer": ["iterations", 1, "energy_eh"], "equals": -75.9,
         "tol": 1e-9},
    ], "Analysis sections: atom_properties (float64 [n_atoms]), bond_orders, "
       "scf_history.")

    # 9) vendor extension + extensions governance
    w = QvfWriter(_PROGRAM, _VERSION, "vendor")
    w.add_structure([{"symbol": "H", "position": [0, 0, 0], "atomic_number": 1}])
    w.set_extensions({"x_demo": {"version": "1.0", "critical": False}})
    w.add_vendor_section("x_demo.custom",
                         json_members={"payload": {"answer": 42}},
                         critical=False)
    _write("vendor", w, [
        {"manifest_pointer": ["extensions", "x_demo", "version"], "equals": "1.0"},
        {"section": "x_demo_custom", "member": "payload",
         "json_pointer": ["answer"], "equals": 42},
    ], "Vendor namespace (x_demo.*) with an extensions governance declaration.")

    # 10) run.record — self-contained input + log of one program invocation
    input_text = ("! RHF STO-3G TightSCF\n"
                  "* xyz 0 1\n"
                  "O  0.0000  0.0000  0.1173\n"
                  "H  0.0000  0.7572 -0.4692\n"
                  "H  0.0000 -0.7572 -0.4692\n"
                  "*\n")
    log_text = ("democode 1.0.0 — water.inp\n"
                "SCF iteration   1  E = -74.880\n"
                "SCF iteration   8  E = -74.965901\n"
                "SCF CONVERGED\n"
                "FINAL SINGLE POINT ENERGY  -74.965901\n")
    w = QvfWriter(_PROGRAM, _VERSION, "run-record")
    w.add_structure(
        [{"symbol": "O", "position": [0.0, 0.0, 0.1173], "atomic_number": 8},
         {"symbol": "H", "position": [0.0, 0.7572, -0.4692], "atomic_number": 1},
         {"symbol": "H", "position": [0.0, -0.7572, -0.4692],
          "atomic_number": 1}])
    w.add_run_record(
        program="democode", program_version="1.0.0",
        command="democode water.inp", exit_status=0,
        started_utc="2026-07-24T12:00:00Z", finished_utc="2026-07-24T12:00:41Z",
        input_text=input_text, log_text=log_text,
        files={"input": {"filename": "water.inp"},
               "log": {"filename": "water.out"},
               "attachment.geom": {"filename": "water.xyz",
                                   "media_type": "chemical/x-xyz"}},
        attachments={"geom": b"3\nwater\nO 0 0 0.1173\nH 0 0.7572 -0.4692\n"
                             b"H 0 -0.7572 -0.4692\n"})
    _write("run_record", w, [
        {"manifest_pointer": ["sections", 1, "program"], "equals": "democode"},
        {"manifest_pointer": ["sections", 1, "program_version"],
         "equals": "1.0.0"},
        {"manifest_pointer": ["sections", 1, "exit_status"], "equals": 0},
        {"section": "run_record", "member": "input", "decode": "utf8",
         "equals": input_text},
        {"section": "run_record", "member": "log", "decode": "utf8",
         "contains": "FINAL SINGLE POINT ENERGY  -74.965901"},
        {"section": "run_record", "member": "files",
         "json_pointer": ["input", "filename"], "equals": "water.inp"},
        {"section": "run_record", "member": "attachment.geom",
         "decode": "utf8", "contains": "water"},
    ], "run.record: verbatim program input + full log + attachment, making "
       "the archive a self-contained record of the calculation.")

    # 11) job.spec — a pending archive: structure + declarative job request,
    # provenance.run_status = "pending" (nothing has run yet).
    w = QvfWriter(_PROGRAM, _VERSION, "pending-job")
    w.add_structure(
        [{"symbol": "Mg", "position": [0.0, 0.0, 0.0], "atomic_number": 12},
         {"symbol": "O", "position": [2.1, 2.1, 2.1], "atomic_number": 8}],
        pbc=[True, True, True],
        lattice_vectors=[[4.2, 0, 0], [0, 4.2, 0], [0, 0, 4.2]])
    w.add_job_spec(job_type="periodic", method="rks", basis="pob-tzvp-rev2",
                   functional="pbe", charge=0, multiplicity=1,
                   kpoints=[4, 4, 4], tasks=["single_point"],
                   options={"cutoff_ha": 300.0})
    w.set_provenance(run_status="pending")
    _write("job_spec", w, [
        {"manifest_pointer": ["provenance", "run_status"], "equals": "pending"},
        {"section": "job_spec", "member": "spec",
         "json_pointer": ["job_type"], "equals": "periodic"},
        {"section": "job_spec", "member": "spec",
         "json_pointer": ["method"], "equals": "rks"},
        {"section": "job_spec", "member": "spec",
         "json_pointer": ["kpoints", 1], "equals": 4},
        {"section": "job_spec", "member": "spec",
         "json_pointer": ["tasks", 0], "equals": "single_point"},
        {"section": "job_spec", "member": "spec",
         "json_pointer": ["options", "cutoff_ha"], "equals": 300.0,
         "tol": 1e-9},
    ], "job.spec: a pending container — structure + declarative job request "
       "(provenance.run_status = 'pending'), the executable-input half of "
       "run.record.")

    print(f"Corpus written to {CORPUS}")


if __name__ == "__main__":
    build()
