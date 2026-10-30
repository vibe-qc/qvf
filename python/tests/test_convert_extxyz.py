"""extXYZ energy, forces and stress (qvf.convert, issue #39)."""
import pytest

from qvf import Reader
from qvf.convert import export_xyz, import_xyz
from qvf.units import HARTREE_IN_EV
from qvf.validate import run

BOHR = 1.8897261246257702
FRAME = ('2\nProperties=species:S:1:pos:R:3:forces:R:3:Z:I:1:tags:I:1 energy=-12.5 '
         'Lattice="5 0 0 0 5 0 0 0 5" pbc="T T T" stress="0.1 0 0 0 0.2 0 0 0 0.3" '
         'config_type=bulk Time=3.0\n'
         'O 0 0 0 0.5 -1 2 8 7\nH 0.96 0 0 -0.5 1 -2 1 0\n')


def imported(tmp_path, text, name='in.xyz'):
    src = tmp_path/name; src.write_text(text)
    out = tmp_path/(name + '.qvf')
    report = import_xyz(src, out)
    assert run(out)['ok']
    return report, out


def test_one_frame_energy_forces_and_stress(tmp_path):
    report, out = imported(tmp_path, FRAME)
    assert (report['energies'], report['forces'], report['stress']) == (1, 1, 1)
    assert report['omitted']['header_keys'] == ['Time', 'config_type']
    assert report['omitted']['properties'] == ['tags']
    with Reader(out) as reader:
        assert reader.raw_manifest['energies']['total'] == {
            'value': pytest.approx(-12.5 / HARTREE_IN_EV), 'units': 'hartree'}
        gradient = reader.tensor('forces', 'gradient').tolist()
        stress = reader.tensor('forces', 'stress').tolist()
    assert gradient[0] == pytest.approx([-0.5 / (HARTREE_IN_EV * BOHR),
                                         1 / (HARTREE_IN_EV * BOHR),
                                         -2 / (HARTREE_IN_EV * BOHR)])
    assert stress[2][2] == pytest.approx(0.3 / (HARTREE_IN_EV * BOHR ** 3))


def test_trajectory_energies_and_gradient(tmp_path):
    second = FRAME.replace('energy=-12.5', 'energy=-12.0').replace('0.5 -1 2', '0.25 -1 2')
    report, out = imported(tmp_path, FRAME + second)
    assert report['frames'] == 2 and report['energies'] == 2 and report['forces'] == 2
    assert report['stress'] == 0 and report['omitted']['stress'] == 2
    with Reader(out) as reader:
        metadata = reader.json('trajectory', 'metadata')
        gradient = reader.tensor('trajectory', 'gradient').tolist()
        assert not any(s.kind == 'forces' for s in reader.sections)
    assert metadata['energies'] == pytest.approx([-12.5 / HARTREE_IN_EV, -12 / HARTREE_IN_EV])
    assert gradient[1][0][0] == pytest.approx(-0.25 / (HARTREE_IN_EV * BOHR))
    partial = FRAME + second.replace(' energy=-12.0', '')
    report, _ = imported(tmp_path, partial, 'partial.xyz')
    assert report['energies'] == 0 and report['omitted']['energies'] == 1


def test_export_round_trip(tmp_path):
    _, out = imported(tmp_path, FRAME)
    xyz = tmp_path/'out.xyz'
    report = export_xyz(out, xyz, section='structure')
    assert report['energy'] and report['forces'] and report['stress']
    assert report['omitted_sections'] == []
    again, back = imported(tmp_path, xyz.read_text(), 'again.xyz')
    with Reader(out) as a, Reader(back) as b:
        assert sum(b.tensor('forces', 'gradient').tolist(), []) == pytest.approx(
            sum(a.tensor('forces', 'gradient').tolist(), []))
        assert b.raw_manifest['energies'] == a.raw_manifest['energies']
    second = FRAME.replace('energy=-12.5', 'energy=-12.0')
    _, traj = imported(tmp_path, FRAME + second, 'traj.xyz')
    report = export_xyz(traj, tmp_path/'traj-out.xyz', section='trajectory')
    assert report['energy'] and report['forces'] and not report['stress']


def test_independent_ase(tmp_path):
    ase_io = pytest.importorskip('ase.io')
    from ase import Atoms
    from ase.calculators.singlepoint import SinglePointCalculator
    atoms = Atoms('OH', positions=[[0, 0, 0], [0.96, 0, 0]], cell=[5, 5, 5], pbc=True)
    atoms.calc = SinglePointCalculator(atoms, energy=-12.5, forces=[[0.5, -1, 2], [-0.5, 1, -2]],
                                       stress=[0.1, 0.2, 0.3, 0.0, 0.0, 0.0])
    src = tmp_path/'ase.xyz'
    ase_io.write(str(src), atoms, format='extxyz')
    out = tmp_path/'ase.qvf'
    report = import_xyz(src, out)
    assert report['energies'] == 1 and report['forces'] == 1 and report['stress'] == 1
    xyz = tmp_path/'back.xyz'
    export_xyz(out, xyz, section='structure')
    back = ase_io.read(str(xyz), format='extxyz')
    assert back.get_potential_energy() == pytest.approx(-12.5)
    assert back.get_forces().ravel().tolist() == pytest.approx([0.5, -1, 2, -0.5, 1, -2])
    assert back.get_stress().tolist() == pytest.approx([0.1, 0.2, 0.3, 0, 0, 0])
