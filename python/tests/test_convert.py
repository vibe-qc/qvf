"""Conversion correctness, explicit losses and refusal before publication."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qvf import Reader, Writer
from qvf.convert import import_xyz, export_xyz, import_cube, export_cube
from qvf._legacy_writer import BOHR_PER_ANGSTROM
from qvf.validate import run

XYZ = '2\nexample\nH 0 0 0\nH 0 0 0.74\n'
CUBE = ('synthetic scalar field\nOUTER LOOP: X, MIDDLE LOOP: Y, INNER LOOP: Z\n'
        '1 0.1 -0.2 0.3\n2 1 0.1 0\n2 0 2 0.2\n2 0.3 0 3\n'
        '1 0 1 2 3\n0 1 2 3 4 5 6 7\n')


def clean(path):
    report = run(path)
    assert report['ok'] and not report['findings'], report


def test_xyz_round_trip_and_no_implicit_job(tmp_path):
    src = tmp_path/'input.xyz'; src.write_text(XYZ)
    qvf = tmp_path/'geometry.qvf'; report = import_xyz(src, qvf)
    assert report['omitted_comments'] == 1
    clean(qvf)
    with Reader(qvf) as reader:
        assert [s.kind for s in reader.sections] == ['structure']
        structure = reader.json('structure', 'structure')
        assert structure['atoms'][1]['position'] == [0, 0, 0.74]
        assert 'provenance' not in reader.raw_manifest
    text = tmp_path/'output.xyz'; export_xyz(qvf, text)
    again = tmp_path/'again.qvf'; import_xyz(text, again)
    with Reader(again) as reader:
        assert reader.json('structure', 'structure') == structure


def test_extxyz_skewed_variable_cell_trajectory(tmp_path):
    frame = ('2\nProperties=pos:R:3:species:S:1 Lattice="{cell}" pbc="T F T"\n'
             '0 0 0 C\n1 2 {z} H\n')
    src = tmp_path/'frames.xyz'
    src.write_text(frame.format(cell='4 0.1 0.2 0.3 5 0.4 0.5 0.6 6', z=3)
                   + frame.format(cell='8 0.2 0.4 0.6 10 0.8 1 1.2 12', z=4))
    archive = tmp_path/'frames.qvf'; import_xyz(src, archive); clean(archive)
    with Reader(archive) as reader:
        cells = reader.tensor('trajectory', 'lattice').tolist()
        coords = reader.tensor('trajectory', 'coords').tolist()
        assert cells[0] == [[4, .1, .2], [.3, 5, .4], [.5, .6, 6]]
        assert coords[1][1] == [1, 2, 4]
    with pytest.raises(ValueError, match='select a section'):
        export_xyz(archive, tmp_path/'ambiguous.xyz')
    output = tmp_path/'out.xyz'
    report = export_xyz(archive, output, section='trajectory')
    assert report['omitted_sections'] == ['structure']
    again = tmp_path/'again.qvf'; import_xyz(output, again); clean(again)
    with Reader(again) as reader:
        assert reader.tensor('trajectory', 'lattice').tolist() == cells
        assert reader.tensor('trajectory', 'coords').tolist() == coords
    with pytest.raises(ValueError, match='plain XYZ'):
        export_xyz(archive, tmp_path/'plain.xyz', section='trajectory', extended=False)


@pytest.mark.parametrize('text', [
    '', '1\ncomment\n', '1\nx\nH nan 0 0', '1\nx\nUnknown 0 0 0',
    '1\nx\nH 0 0 0 extra', XYZ + '1\nx\nHe 0 0 0\n',
    '1\nProperties=species:S:1:pos:R:3:forces:R:2\nH 0 0 0 1 2',
    '1\nProperties=species:S:1:pos:R:3:Z:I:1\nH 0 0 0 2',
    '1\nProperties=species:S:1:pos:R:3:forces:R:3\nH 0 0 0 1 2',
    '1\nProperties=species:S:1:pos:R:3 stress="1 2 3"\nH 0 0 0',
    '1\nProperties=species:S:1:pos:R:3:pos:R:3\nH 0 0 0 0 0 0',
    '1\nProperties=species:S:1:pos:R:3 pbc="T F F"\nH 0 0 0',
    '1\nProperties=species:S:1:pos:R:3 pbc="maybe F F"\nH 0 0 0',
    '1\nProperties=species:S:1:pos:R:3 Lattice="1 0 0"\nH 0 0 0',
])
def test_bad_xyz_leaves_no_output(tmp_path, text):
    src = tmp_path/'bad.xyz'; src.write_text(text)
    with pytest.raises(ValueError):
        import_xyz(src, tmp_path/'bad.qvf')
    assert sorted(p.name for p in tmp_path.iterdir()) == ['bad.xyz']


@pytest.mark.parametrize('endpoint', [True, False])
def test_cube_values_units_and_periodic_endpoint(tmp_path, endpoint):
    src = tmp_path/'input.cube'; src.write_text(CUBE)
    archive = tmp_path/'field.qvf'
    report = import_cube(src, archive, kind='volume.density', periodic=(True, False, True), includes_endpoint=endpoint)
    assert report['nonzero_atom_charges_omitted'] == 0
    clean(archive)
    with Reader(archive) as reader:
        structure = reader.json('structure', 'structure')
        grid = reader.json('volume', 'grid')
        assert structure['atoms'][0]['position'] == pytest.approx([v/BOHR_PER_ANGSTROM for v in [1, 2, 3]])
        assert structure['lattice_vectors'][0] == pytest.approx([v*(2-int(endpoint))/BOHR_PER_ANGSTROM for v in [1, .1, 0]])
        assert grid['voxel_vectors'][2] == [.3, 0, 3]
        assert reader.tensor('volume', 'data').tolist() == [[[0, 1], [2, 3]], [[4, 5], [6, 7]]]
    output = tmp_path/'output.cube'; result = export_cube(archive, output)
    assert result['periodic'] == [True, False, True]
    assert result['includes_endpoint'] == endpoint
    again = tmp_path/'again.qvf'
    import_cube(output, again, kind=result['kind'], periodic=result['periodic'], includes_endpoint=result['includes_endpoint'])
    clean(again)
    with Reader(again) as reader:
        assert reader.json('volume', 'grid') == grid
        assert reader.json('structure', 'structure') == structure


@pytest.mark.parametrize('text', [
    CUBE.replace('1 0.1 -0.2 0.3', '-1 0.1 -0.2 0.3'),
    CUBE.replace('1 0.1 -0.2 0.3', '1 0.1 -0.2 0.3 2'),
    CUBE.replace('2 1 0.1 0', '-2 1 0.1 0'),
    CUBE.replace('0 1 2 3 4 5 6 7', '0 1 2'),
    CUBE.replace('0 1 2 3 4 5 6 7', '0 1 2 3 4 5 6 inf'),
    CUBE.replace('OUTER LOOP: X, MIDDLE LOOP: Y', 'OUTER LOOP: Y, MIDDLE LOOP: X'),
    CUBE.replace('2 1 0.1 0', '5000001 1 0.1 0'),
])
def test_bad_cube_leaves_no_output(tmp_path, text):
    src = tmp_path/'bad.cube'; src.write_text(text)
    with pytest.raises(ValueError):
        import_cube(src, tmp_path/'bad.qvf')
    assert sorted(p.name for p in tmp_path.iterdir()) == ['bad.cube']


def test_atomic_outputs_and_existing_files(tmp_path):
    src = tmp_path/'input.xyz'; src.write_text(XYZ)
    output = tmp_path/'output.qvf'; output.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        import_xyz(src, output)
    assert output.read_bytes() == b'keep'
    # Reject a degenerate periodic cell before publishing the temporary archive.
    src.write_text('1\nProperties=species:S:1:pos:R:3 Lattice="0 0 0 0 0 0 0 0 0"\nH 0 0 0\n')
    with pytest.raises(ValueError, match='periodic cell'):
        import_xyz(src, tmp_path/'invalid.qvf')
    assert not (tmp_path/'invalid.qvf').exists()
    assert not list(tmp_path.glob('.qvf-output-*'))


def test_no_numpy_import_required(tmp_path):
    src = tmp_path/'input.xyz'; src.write_text(XYZ)
    code = '''import sys
sys.path.insert(0, sys.argv[1])
from qvf.convert import import_xyz, export_xyz
import_xyz(sys.argv[2], sys.argv[3])
export_xyz(sys.argv[3], sys.argv[4])
assert 'numpy' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-S', '-c', code, str(Path(__file__).resolve().parents[1]),
                             str(src), str(tmp_path/'out.qvf'), str(tmp_path/'out.xyz')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_convert_cli_reports_and_options(tmp_path, capsys):
    from qvf.cli import main
    src = tmp_path/'molecule.xyz'; src.write_text(XYZ)
    archive = tmp_path/'molecule.qvf'
    assert main(['convert', str(src), '-o', str(archive), '--from', 'xyz', '--to', 'qvf']) == 0
    assert json.loads(capsys.readouterr().out)['frames'] == 1
    assert main(['convert', str(archive), '-o', str(tmp_path/'out.xyz'), '--from', 'qvf', '--to', 'xyz']) == 0
    assert 'Keep the original' in json.loads(capsys.readouterr().out)['scope']
    assert main(['convert', str(src), '-o', str(tmp_path/'bad.qvf'), '--from', 'xyz', '--to', 'qvf', '--kind', 'volume.density']) == 2
    assert 'only to cube' in capsys.readouterr().err
    assert not (tmp_path/'bad.qvf').exists()


def test_independent_ase_interoperability(tmp_path):
    ase_io = pytest.importorskip('ase.io')
    np = pytest.importorskip('numpy')
    src = tmp_path/'input.cube'; src.write_text(CUBE)
    archive = tmp_path/'field.qvf'; import_cube(src, archive)
    exported = tmp_path/'exported.cube'; export_cube(archive, exported)
    from ase.io.cube import read_cube
    with exported.open() as stream:
        cube = read_cube(stream)
    np.testing.assert_array_equal(cube['data'], np.arange(8).reshape(2, 2, 2))
    np.testing.assert_allclose(cube['atoms'].positions[0], [v/BOHR_PER_ANGSTROM for v in (1, 2, 3)], rtol=1e-9)
    # Independent extXYZ writer -> QVF -> independent reader retains skew and axes.
    from ase import Atoms
    atoms = Atoms('CH', positions=[[0, 0, 0], [1, 2, 3]],
                  cell=[[4, .1, .2], [.3, 5, .4], [.5, .6, 6]], pbc=[True, False, True])
    xyz = tmp_path/'ase.xyz'; ase_io.write(xyz, atoms, format='extxyz')
    geom = tmp_path/'ase.qvf'; import_xyz(xyz, geom)
    out = tmp_path/'qvf.xyz'; export_xyz(geom, out)
    actual = ase_io.read(out, format='extxyz')
    np.testing.assert_allclose(actual.cell, atoms.cell, atol=1e-14)
    np.testing.assert_allclose(actual.positions, atoms.positions, atol=1e-14)
    np.testing.assert_array_equal(actual.pbc, atoms.pbc)


def test_cube_cli_periodicity_and_existing_export(tmp_path, capsys):
    from qvf.cli import main
    src = tmp_path/'input.cube'; src.write_text(CUBE)
    archive = tmp_path/'output.qvf'
    assert main(['convert', str(src), '-o', str(archive), '--from', 'cube', '--to', 'qvf',
                 '--kind', 'volume.density', '--periodic', 'true', 'false', 'true', '--no-endpoint']) == 0
    assert json.loads(capsys.readouterr().out)['kind'] == 'volume.density'
    output = tmp_path/'output.cube'; output.write_text('keep')
    assert main(['convert', str(archive), '-o', str(output), '--from', 'qvf', '--to', 'cube']) == 2
    assert output.read_text() == 'keep'
    assert 'already exists' in capsys.readouterr().err
