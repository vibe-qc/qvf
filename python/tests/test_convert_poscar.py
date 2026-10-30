"""VASP POSCAR/CONTCAR import/export (qvf.convert, issue #35)."""
import pytest

from qvf import Reader, Writer
from qvf.convert import export_poscar, import_poscar
from qvf.validate import run

# Synthetic wurtzite-like cell, VASP 5, Direct, with Selective dynamics.
POSCAR = """synthetic GaN cell
   1.0000000000
     3.1890000000    0.0000000000    0.0000000000
    -1.5945000000    2.7617646000    0.0000000000
     0.0000000000    0.0000000000    5.1850000000
   Ga_d   N
     2    2
Selective dynamics
Direct
  0.3333333333  0.6666666667  0.0000000000   F   F   F
  0.6666666667  0.3333333333  0.5000000000   T   T   T
  0.3333333333  0.6666666667  0.3770000000   F   F   T
  0.6666666667  0.3333333333  0.8770000000   T   T   T
"""


def write(tmp_path, text, name='POSCAR'):
    path = tmp_path/name
    path.write_text(text)
    return path


def imported(tmp_path, text, **kw):
    out = tmp_path/f'out{len(list(tmp_path.glob("out*.qvf")))}.qvf'
    report = import_poscar(write(tmp_path, text), out, **kw)
    assert run(out)['ok']
    with Reader(out) as reader:
        geometry = reader.json('structure', 'structure')
        raw = reader.raw_manifest
    return report, geometry, raw, out


def test_vasp5_direct_with_selective_dynamics(tmp_path):
    report, geometry, raw, _ = imported(tmp_path, POSCAR)
    assert (report['species'], report['counts'], report['vasp_format']) == (['Ga', 'N'], [2, 2], 5)
    assert report['coordinates'] == 'direct' and report['selective_dynamics'] is True
    assert report['frozen_atoms'] == 1 and report['partially_fixed_atoms_omitted'] == 1
    assert report['velocities_omitted'] == 0
    assert raw['constraints'] == {'frozen_atoms': [0]}
    assert raw['sections'][0]['label'] == 'synthetic GaN cell'
    assert [a['symbol'] for a in geometry['atoms']] == ['Ga', 'Ga', 'N', 'N']
    assert geometry['pbc'] == [True] * 3
    assert geometry['lattice_vectors'][1] == [-1.5945, 2.7617646, 0]
    assert geometry['atoms'][1]['position'] == pytest.approx(
        [0.6666666667 * 3.189 - 0.3333333333 * 1.5945, 0.3333333333 * 2.7617646, 2.5925])


def test_scale_volume_cartesian_and_vasp4(tmp_path):
    # VASP 4 (no species line), a negative scale giving the volume, and
    # Cartesian positions, which the scale also multiplies.
    text = ("cubic\n-64.0\n2 0 0\n0 2 0\n0 0 2\n1 1\nCartesian\n0 0 0\n1 1 1\n")
    with pytest.raises(ValueError, match='needs species='):
        import_poscar(write(tmp_path, text), tmp_path/'x.qvf')
    report, geometry, raw, _ = imported(tmp_path, text, species=['Na', 'Cl'])
    assert report['vasp_format'] == 4 and report['coordinates'] == 'cartesian'
    assert geometry['lattice_vectors'] == [[4, 0, 0], [0, 4, 0], [0, 0, 4]]
    assert geometry['atoms'][1]['position'] == [2, 2, 2]
    assert 'constraints' not in raw
    three = ("axes\n1 2 0.5\n1 0 0\n0 1 0\n0 0 4\nSi\n1\nC\n0.5 0.5 0.5\n")
    _, geometry, _, _ = imported(tmp_path, three)
    assert geometry['lattice_vectors'] == [[1, 0, 0], [0, 2, 0], [0, 0, 2]]
    assert geometry['atoms'][0]['position'] == [0.5, 1, 0.25]


def test_contcar_velocities_and_predictor_are_reported(tmp_path):
    text = POSCAR + "\n  0.1 0.2 0.3\n  0.0 0.0 0.0\n -0.1 0.0 0.2\n  0 0 0\n\n 1\n 0.5\n 0.25\n"
    report, _, _, _ = imported(tmp_path, text)
    assert report['velocities_omitted'] == 4
    assert report['predictor_corrector_lines_omitted'] == 3
    lattice = (POSCAR + "\nLattice velocities and vectors\n 1\n" + " 0 0 0\n" * 6
               + "\nCartesian\n" + " 0 0 0\n" * 4)
    report, _, _, _ = imported(tmp_path, lattice)
    assert report['lattice_velocities_omitted'] is True and report['velocities_omitted'] == 4


@pytest.mark.parametrize('text, kw, message', [
    (POSCAR.replace('Ga_d   N', 'Ga_d   Xq'), {}, 'not an element'),
    (POSCAR, {'species': ['Ga', 'O']}, 'disagrees'),
    (POSCAR.replace('     2    2', '     2    0'), {}, 'positive integers'),
    (POSCAR.replace('   1.0000000000\n', '   0\n'), {}, 'must not be zero'),
    (POSCAR.replace('   1.0000000000\n', '   1 1\n'), {}, 'one value or three'),
    (POSCAR.replace('    -1.5945000000    2.7617646000', '     6.3780000000    0.0000000000'),
     {}, 'linearly dependent'),
    (POSCAR.replace('   F   F   F', '   F   F'), {}, 'T or F'),
    (POSCAR.replace('Direct\n', ''), {}, 'Direct or Cartesian line'),
    (POSCAR.rsplit('\n', 2)[0] + '\n', {}, 'fewer position lines'),
    (POSCAR + '\nsome trailing words\n', {}, 'not a velocity row'),
    ('short\n1\n', {}, 'too short'),
])
def test_refusals(tmp_path, text, kw, message):
    with pytest.raises(ValueError, match=message):
        import_poscar(write(tmp_path, text), tmp_path/'bad.qvf', **kw)
    assert not (tmp_path/'bad.qvf').exists()


def test_export_round_trip_keeps_order_and_frozen_atoms(tmp_path):
    _, geometry, raw, qvf = imported(tmp_path, POSCAR)
    out = tmp_path/'POSCAR.out'
    report = export_poscar(qvf, out)
    assert report['species'] == ['Ga', 'N'] and report['counts'] == [2, 2]
    assert report['selective_dynamics'] is True and report['frozen_atoms'] == 1
    assert report['max_rounding_error_angstrom'] < 1e-9
    lines = out.read_text().splitlines()
    assert lines[:2] == ['synthetic GaN cell', '1.0']
    assert lines[7:9] == ['Selective dynamics', 'Direct']
    assert lines[9].endswith(' F F F') and lines[10].endswith(' T T T')
    again = tmp_path/'again.qvf'
    second = import_poscar(out, again)
    assert second['frozen_atoms'] == 1
    with Reader(again) as reader:
        back = reader.json('structure', 'structure')
        assert reader.raw_manifest['constraints'] == raw['constraints']
    for a, b in zip(back['atoms'], geometry['atoms']):
        assert a['symbol'] == b['symbol']
        assert a['position'] == pytest.approx(b['position'], abs=1e-9)


def periodic(tmp_path, atoms, lattice, constraints=None, name='p.qvf', second=False):
    path = tmp_path/name
    with Writer(path, 'qvf-test', '1') as writer:
        if second:
            writer.add_section({'id': 'first', 'kind': 'structure'})
            writer.add_json('first', 'structure', {'atoms': atoms, 'pbc': [True] * 3,
                                                   'lattice_vectors': lattice})
        writer.add_section({'id': 'structure', 'kind': 'structure'})
        writer.add_json('structure', 'structure', {'atoms': atoms, 'pbc': [True] * 3,
                                                   'lattice_vectors': lattice})
        if constraints:
            writer.set_constraints(**constraints)
    return path


def test_export_writes_runs_in_archive_order(tmp_path):
    atoms = [{'symbol': s, 'atomic_number': z, 'position': p} for s, z, p in
             (('Si', 14, [0, 0, 0]), ('O', 8, [1, 0, 0]), ('Si', 14, [0, 1, 0]))]
    path = periodic(tmp_path, atoms, [[0, 3, 0], [-4, 0, 0], [0, 0, 5]],
                    {'distance_constraints': [{'atoms': [0, 1], 'target_angstrom': 1.6}]})
    out = tmp_path/'runs.vasp'
    report = export_poscar(path, out)
    assert report['species'] == ['Si', 'O', 'Si'] and report['counts'] == [1, 1, 1]
    assert report['constraints_not_written'] == ['distance_constraints']
    lines = out.read_text().splitlines()
    assert lines[5].split() == ['Si', 'O', 'Si'] and lines[7] == 'Direct'
    assert [float(v) for v in lines[9].split()] == pytest.approx([0, -0.25, 0])
    # frozen_atoms index the archive's first structure only.
    other = periodic(tmp_path, atoms, [[3, 0, 0], [0, 3, 0], [0, 0, 3]],
                     {'frozen_atoms': [1]}, name='two.qvf', second=True)
    report = export_poscar(other, tmp_path/'second.vasp', section='structure')
    assert report['selective_dynamics'] is False
    assert report['constraints_not_written'] == [
        "frozen_atoms (they index the archive's first structure)"]


def test_export_refuses_nonperiodic(tmp_path):
    path = tmp_path/'molecule.qvf'
    with Writer(path, 'qvf-test', '1') as writer:
        writer.add_section({'id': 'structure', 'kind': 'structure'})
        writer.add_json('structure', 'structure', {
            'atoms': [{'symbol': 'H', 'atomic_number': 1, 'position': [0, 0, 0]}],
            'pbc': [True, True, False], 'lattice_vectors': [[3, 0, 0], [0, 3, 0], [0, 0, 3]]})
    with pytest.raises(ValueError, match='periodic on all three axes'):
        export_poscar(path, tmp_path/'POSCAR')


def test_independent_ase_reads_and_writes(tmp_path):
    ase_io = pytest.importorskip('ase.io')
    _, geometry, _, qvf = imported(tmp_path, POSCAR)
    out = tmp_path/'POSCAR.out'; export_poscar(qvf, out)
    crystal = ase_io.read(str(out), format='vasp')
    assert crystal.get_chemical_symbols() == ['Ga', 'Ga', 'N', 'N']
    assert crystal.cell.array.ravel().tolist() == pytest.approx(
        [v for row in geometry['lattice_vectors'] for v in row])
    assert crystal.positions.ravel().tolist() == pytest.approx(
        [v for a in geometry['atoms'] for v in a['position']], abs=1e-8)
    assert [c.index for c in crystal.constraints][0].tolist() == [0]
    # ASE's own POSCAR layout imports to the same structure.
    written = tmp_path/'ase.vasp'
    ase_io.write(str(written), crystal, format='vasp', direct=False)
    report = import_poscar(written, tmp_path/'ase.qvf')
    assert report['coordinates'] == 'cartesian' and report['frozen_atoms'] == 1
    with Reader(tmp_path/'ase.qvf') as reader:
        back = reader.json('structure', 'structure')
    for a, b in zip(back['atoms'], geometry['atoms']):
        assert a['position'] == pytest.approx(b['position'], abs=1e-6)


def test_cli_poscar(tmp_path, capsys):
    from qvf.cli import main
    src = write(tmp_path, "cubic\n4.0\n1 0 0\n0 1 0\n0 0 1\n1\nDirect\n0 0 0\n")
    qvf = tmp_path/'cli.qvf'
    assert main(['convert', str(src), '-o', str(qvf), '--from', 'poscar', '--to', 'qvf',
                 '--species', 'Cu']) == 0
    assert main(['convert', str(qvf), '-o', str(tmp_path/'CONTCAR'), '--from', 'qvf',
                 '--to', 'poscar']) == 0
    capsys.readouterr()
    assert main(['convert', str(src), '-o', str(tmp_path/'x.qvf'), '--from', 'xyz', '--to',
                 'qvf', '--species', 'Cu']) == 2
    assert '--species applies only to POSCAR/CHGCAR import' in capsys.readouterr().err
