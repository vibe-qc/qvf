"""xTB producer contract: units, identity, optional results and atomic output.

Synthetic values use the field names/layouts of xTB 6.7.1's JSON and
g98fake2 writers. No xTB installation or scientific calculation is needed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qvf import Reader
from qvf.adapters.xtb import write_xtb
from qvf.units import BOHR_PER_ANGSTROM, HARTREE_IN_EV
from qvf._legacy_writer import primitive_norm
from qvf.validate import run


WATER = "3\nresult\nO 0 0 0\nH 0 0 1\nH 1 0 0\n"
DATA = {
    "method": "GFN2-xTB", "xtb version": "6.7.1", "total energy": -5.1,
    "number of electrons": 8, "number of unpaired electrons": 0,
    "number of molecular orbitals": 6,
    "orbital energies / eV": [-20., -10., -8., -7., 1., 2.],
    "fractional occupation": [2., 2., 2., 2., 0., 0.],
    "partial charges": [-0.6, 0.3, 0.3], "dipole / a.u.": [1., 0., 0.],
    "program call": "xtb /scratch/example/structure.xyz --opt",
    "atomic quadrupole moments": [[0.] * 6] * 3,
}


def put(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def inputs(tmp_path, **changes):
    return (put(tmp_path, "xtbout.json", json.dumps({**DATA, **changes})),
            put(tmp_path, "final.xyz", WATER), tmp_path / "result.qvf")


def test_properties_trajectory_units_identity_and_private_fields(tmp_path):
    source, geometry, output = inputs(tmp_path)
    first = WATER.replace("result", "energy: -5.0 gnorm: 0.1 xtb: 6.7.1").replace("H 0 0 1", "H 0 0 1.1")
    last = WATER.replace("result", "energy: -5.1 gnorm: 0.001 xtb: 6.7.1")
    trajectory = put(tmp_path, "xtbopt.log", first + last)
    bonds = put(tmp_path, "wbo", "1 2 0.95\n3 1 0.96\n")
    report = write_xtb(source, geometry, output, trajectory=trajectory, wbo=bonds, charge=0)
    assert run(output)["ok"]
    assert not report["findings"]
    assert report["omitted_json_fields"] == ["atomic quadrupole moments", "program call"]
    with Reader(output) as reader:
        root = reader.raw_manifest
        assert root["source"]["program"] == "qvf.adapters.xtb"
        prov = root["provenance"]
        assert prov["charge"] == 0  # xTB's 8 valence electrons are NOT charge +2.
        assert prov["multiplicity"] == 1
        assert prov["x_xtb"]["valence_electrons"] == 8
        assert "n_electrons" not in prov and "run_status" not in prov and "scf_converged" not in prov
        assert prov["x_xtb"]["orbital_energies_hartree"][0] == pytest.approx(-20 / HARTREE_IN_EV)
        assert root["energies"]["total"] == {"value": -5.1, "units": "hartree"}
        assert root["dipole_moment"]["vector_debye"] == pytest.approx([2.541746473, 0, 0])
        assert "scratch" not in json.dumps(root)
        assert reader.tensor("charges", "mulliken_charge").tolist() == [-0.6, 0.3, 0.3]
        assert reader.json("bond_orders", "bond_orders")["pairs"] == [
            {"i": 0, "j": 1, "order": .95}, {"i": 2, "j": 0, "order": .96}]
        assert reader.json("trajectory", "metadata")["energies"] == [-5., -5.1]
        assert reader.tensor("trajectory", "coords").tolist()[-1] == [[0, 0, 0], [0, 0, 1], [1, 0, 0]]


def test_coord_bohr_charge_spin_and_missing_properties(tmp_path):
    source, _, output = inputs(tmp_path)
    source.write_text(json.dumps({"method": "GFN1-xTB", "xtb version": "6.7.1", "total energy": -4.}))
    geometry = put(tmp_path, "coord", f"$coord\n0 0 0 o\n0 0 {BOHR_PER_ANGSTROM} h\n{BOHR_PER_ANGSTROM} 0 0 h\n$chrg 1\n$spin 1\n$end\n")
    report = write_xtb(source, geometry, output, run_status="failed")
    assert report["sections"] == ["structure"]
    with Reader(output) as reader:
        assert reader.raw_manifest["provenance"]["charge"] == 1
        assert reader.raw_manifest["provenance"]["multiplicity"] == 2
        assert reader.raw_manifest["provenance"]["run_status"] == "failed"
        assert reader.json("structure", "structure")["atoms"][1]["position"][2] == pytest.approx(1.)


def test_json_cli_without_optional_packages_and_duplicate_keys(tmp_path):
    source, geometry, output = inputs(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    result = subprocess.run([sys.executable, "-S", "-m", "qvf", "export-xtb", str(source),
        "--geometry", str(geometry), "--charge", "0", "-o", str(output)],
        env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert run(output)["ok"]
    output.unlink()
    source.write_text(source.read_text().replace('"total energy": -5.1', '"total energy": -5.1, "total energy": -6'))
    with pytest.raises(ValueError, match="duplicate"):
        write_xtb(source, geometry, output)
    assert not output.exists()


def test_gfn0_charge_is_not_mislabeled_mulliken(tmp_path):
    source, geometry, output = inputs(tmp_path, method="GFN0-xTB")
    write_xtb(source, geometry, output, charge=0)
    assert run(output)["ok"]
    with Reader(output) as reader:
        assert reader.tensor("charges", "custom.xtb_charge").tolist() == [-.6, .3, .3]
        assert "mulliken_charge" not in reader.section("charges").members


def test_xtb_primitive_normalization_phase_and_canonical_assertion(tmp_path):
    source, geometry, output = inputs(tmp_path)
    geometry.write_text("1\nresult\nHe 0 0 0\n")
    source.write_text(json.dumps({"method": "GFN2-xTB", "xtb version": "6.7.1", "total energy": -1.}))
    molden = put(tmp_path, "molden.input", "[Molden Format]\n[Atoms] AU\nHe 1 2 0 0 0\n[GTO]\n1 0\n"
        f"s 1 1\n1.2 {primitive_norm(1.2, 0)}\np 1 1\n.8 {primitive_norm(.8, 1)}\n"
        "[MO]\nSym= a\nEne= -.5\nSpin= Alpha\nOccup= 2\n1 .5\n2 .3\n3 -.2\n4 .1\n")
    write_xtb(source, geometry, output, molden=molden, spin="restricted", canonical_orbitals=True)
    with Reader(output) as reader:
        assert reader.json("wavefunction", "basis")["shells"][1]["coefficients"] == [1.]
        assert reader.tensor("wavefunction", "mo_coefficients").tolist()[0] == pytest.approx([.5, -.3, .2, -.1])
        assert reader.json("wavefunction", "mo_metadata")["orbital_kind"] == "canonical"


def g98():
    return """ Entering Gaussian System
 *********************************************
 Gaussian 98:
 frequency output generated by the xtb code
 *********************************************
 Standard orientation:
 --------------------------
 Center Atomic Atomic Coordinates (Angstroms)
 Number Number Type X Y Z
 --------------------------
 1 8 0 0.000000 0.000000 0.000000
 2 1 0 0.000000 0.000000 1.000000
 3 1 0 1.000000 0.000000 0.000000
 --------------------------
 Frequencies -- -12.5000 1000.0000 1500.0000
 Red. masses -- 1 1 1
 Frc consts  -- 0 0 0
 IR Inten    -- 2 3 4
 Raman Activ -- 0 0 0
 Depolar     -- 0 0 0
 Atom AN X Y Z X Y Z X Y Z
 1 8 0.01 0 0 0 0.02 0 0 0 0.03
 2 1 -0.01 0 0 0 -0.02 0 0 0 -0.03
 3 1 0 0 0 0 0 0 0 0 0
"""


def test_modes_use_filtered_json_and_ignore_fake_raman_and_force_constants(tmp_path):
    source, geometry, output = inputs(tmp_path, **{
        "vibrational frequencies / rcm": [-12.5, 0, .05, 1000, 1500],
        "IR intensities / km/mol": [2, 0, 0, 3, 4], "reduced masses": [1, 0, 0, 2, 3]})
    modefile = put(tmp_path, "g98.out", g98())
    write_xtb(source, geometry, output, modes=modefile)
    assert run(output)["ok"]
    with Reader(output) as reader:
        meta = reader.json("vibrations", "metadata")
        assert meta["frequencies"] == [-12.5, 1000, 1500]
        assert meta["reduced_masses"] == [1, 2, 3]
        assert "raman_activities" not in meta and "force_constants" not in meta
        assert reader.tensor("vibrations", "displacements").tolist()[1][0] == [0, .02, 0]
        assert len(reader.json("ir_intensities", "spectrum")["frequencies"]) == 5
    output.unlink()
    report = write_xtb(source, geometry, output)
    assert "vibrations" not in report["sections"]
    assert any("displacements" in text for text in report["limitations"])
    output.unlink()
    modefile.write_text(g98().replace("1500.0000", "1600.0000"))
    with pytest.raises(ValueError, match="frequencies"):
        write_xtb(source, geometry, output, modes=modefile)
    assert not output.exists()


def test_molden_cube_companions_and_no_dependencies(tmp_path):
    source, geometry, output = inputs(tmp_path)
    geometry.write_text("1\nHe\nHe 0 0 0\n")
    source.write_text(json.dumps({"method": "GFN2-xTB", "xtb version": "6.7.1", "total energy": -1.}))
    molden = put(tmp_path, "molden.input", "[Molden Format]\n[Atoms] AU\nHe 1 2 0 0 0\n[GTO]\n1 0\ns 1 1.00\n"
                 f"1.2 {primitive_norm(1.2, 0)}\n[MO]\nSym= A\nEne= -0.5\nSpin= Alpha\nOccup= 2\n1 1.0\n")
    cube = put(tmp_path, "density.cub", "density\nexample\n1 0 0 0\n2 1 0 0\n2 0 1 0\n2 0 0 1\n2 2 0 0 0\n0 1 2 3 4 5 6 7\n")
    # -S removes site packages: exercises the complete adapter without NumPy,
    # jsonschema, xTB, PySCF or vibe-view, including generic converters.
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    result = subprocess.run([sys.executable, "-S", "-m", "qvf", "export-xtb", str(source),
        "--geometry", str(geometry), "-o", str(output), "--molden", str(molden), "--spin", "restricted",
        "--cube", str(cube), "volume.density"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert run(output)["ok"]
    with Reader(output) as reader:
        assert reader.json("wavefunction", "mo_metadata")["energies"] == [-.5]
        assert reader.tensor("wavefunction", "mo_coefficients").tolist() == [[1.]]
        assert reader.tensor("volume_0", "data").tolist()[1][1][1] == 7
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        write_xtb(source, geometry, output)
    assert output.read_bytes() == original
    output.unlink()
    cube.write_text(cube.read_text().replace("2 2 0 0 0", "2 2 0 0 1"))
    with pytest.raises(ValueError, match="geometry"):
        write_xtb(source, geometry, output, cubes=[(cube, "volume.density")])
    assert not output.exists() and not list(tmp_path.glob(".qvf-output-*"))


@pytest.mark.parametrize("changes, message", [
    ({"partial charges": [0, 0]}, "length"),
    ({"partial charges": [0, 0, 1]}, "sum"),
    ({"partial charges": [False, 0, 0]}, "numeric"),
    ({"number of unpaired electrons": 1}, "valence electron"),
    ({"fractional occupation": [2, 2, 2, 1, 0, 0]}, "occupations disagree"),
    ({"orbital energies / eV": [1]}, "matching lengths"),
    ({"number of molecular orbitals": 5}, "orbital arrays"),
    ({"total energy": float("nan")}, "non-finite"),
    ({"method": "GFN-FF"}, "GFN0-xTB"),
])
def test_malformed_results_refused_without_output(tmp_path, changes, message):
    source, geometry, output = inputs(tmp_path, **changes)
    with pytest.raises(ValueError, match=message):
        write_xtb(source, geometry, output, charge=0)
    assert not output.exists()


def test_companion_mismatches_truncation_and_options(tmp_path):
    source, geometry, output = inputs(tmp_path)
    for content, message in [(WATER, "comments"),
        (WATER.replace("result", "energy: -6 gnorm: .1 xtb: 6.7.1"), "energy"),
        (WATER.replace("result", "energy: -5.1 gnorm: .1 xtb: 6.7.1").replace("H 1 0 0", "H 2 0 0"), "geometry"),
        ("3\nenergy: -5.1 gnorm: .1 xtb: 6.7.1\nO 0 0 0\n", "truncated")]:
        trajectory = put(tmp_path, "xtbopt.log", content)
        with pytest.raises(ValueError, match=message):
            write_xtb(source, geometry, output, trajectory=trajectory)
    for content in ("1 4 .2", "1 2 .2\n2 1 .2", "1 1 .2"):
        bonds = put(tmp_path, "wbo", content)
        with pytest.raises(ValueError, match="atom pair"):
            write_xtb(source, geometry, output, wbo=bonds)
    for options in ({"spin": "restricted"}, {"charge": True}, {"multiplicity": 3}, {"run_status": "running"}):
        with pytest.raises(ValueError):
            write_xtb(source, geometry, output, **options)
    geometry.write_text("$coord\n0 0 0 he\n$periodic 3\n$end\n")
    with pytest.raises(ValueError, match="molecular"):
        write_xtb(source, geometry, output)
    assert not output.exists()
