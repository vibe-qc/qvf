"""XSF point coordinates, independent storage order and strict conversion scope."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qvf import Reader, Writer
from qvf.convert import import_xsf, export_xsf, import_cube
from qvf._legacy_writer import BOHR_PER_ANGSTROM
from qvf.validate import run

GEOMETRY = ('CRYSTAL\n# cell\nPRIMVEC\n2 0.1 0.2\n0.3 4 0.5\n0.6 0.7 6\n'
            '# atoms\nPRIMCOORD\n2 1\n6 0.1 0.2 0.3\nH 1.1 1.2 1.3\n')
# Deliberately unequal axis lengths, skewed spans, nonzero origin and indices.
GRID = ('BEGIN_BLOCK_DATAGRID_3D\nsynthetic\nBEGIN_DATAGRID_3D_samples\n'
        '2 3 4\n0.2 -0.3 0.4\n2 0.1 0.2\n0.3 4 0.5\n0.6 0.7 6\n'
        + ' '.join(str(100*x+10*y+z) for z in range(4) for y in range(3) for x in range(2))
        + '\nEND_DATAGRID_3D\nEND_BLOCK_DATAGRID_3D\n')


def clean(path):
    report = run(path)
    assert report['ok'] and not report['findings'], report


def test_grid_units_endpoint_storage_and_explicit_periodicity(tmp_path):
    src = tmp_path/'input.xsf'; src.write_text(GEOMETRY + GRID)
    archive = tmp_path/'out.qvf'; report = import_xsf(src, archive, kind='volume.density', periodic=(True, True, True))
    assert report['omitted_comments'] == 2
    assert report['omitted'] == []
    assert report['grids'] == [{'section': 'volume', 'label': 'synthetic/samples'}]
    clean(archive)
    with Reader(archive) as reader:
        geometry = reader.json('structure', 'structure')
        grid = reader.json('volume', 'grid')
        assert geometry['atoms'][1]['position'] == [1.1, 1.2, 1.3]
        assert geometry['lattice_vectors'] == [[2, .1, .2], [.3, 4, .5], [.6, .7, 6]]
        assert grid['origin'] == pytest.approx([v * BOHR_PER_ANGSTROM for v in [.2, -.3, .4]])
        assert grid['includes_endpoint'] is True
        assert grid['periodic'] == [True] * 3
        for i, row in enumerate(grid['voxel_vectors']):
            assert row == pytest.approx([v * BOHR_PER_ANGSTROM / (grid['shape'][i]-1) for v in geometry['lattice_vectors'][i]])
        data = reader.tensor('volume', 'data').tolist()
        assert data == [[[100*x+10*y+z for z in range(4)] for y in range(3)] for x in range(2)]
    with pytest.raises(ValueError, match='select a section'):
        export_xsf(archive, tmp_path/'ambiguous.xsf')
    output = tmp_path/'export.xsf'; exported = export_xsf(archive, output, section='volume')
    again = tmp_path/'again.qvf'; import_xsf(output, again, kind=exported['kind'], periodic=exported['periodic'])
    clean(again)
    with Reader(again) as reader:
        assert reader.tensor('volume', 'data').tolist() == data
        actual = reader.json('volume', 'grid')
        assert actual['origin'] == pytest.approx(grid['origin'])
        for actual_row, expected in zip(actual['voxel_vectors'], grid['voxel_vectors']):
            assert actual_row == pytest.approx(expected)
        assert reader.json('structure', 'structure') == geometry
    # CRYSTAL does not imply that this particular field repeats with the cell.
    finite = tmp_path/'finite.qvf'; import_xsf(src, finite)
    with Reader(finite) as reader:
        assert reader.json('volume', 'grid')['periodic'] == [False] * 3
        assert reader.json('structure', 'structure')['pbc'] == [True] * 3


@pytest.mark.parametrize('header,pbc', [('CRYSTAL', [True]*3), ('SLAB', [True, True, False]), ('POLYMER', [True, False, False])])
def test_geometry_round_trip(tmp_path, header, pbc):
    src = tmp_path/'cell.xsf'; src.write_text(GEOMETRY.replace('CRYSTAL', header))
    archive = tmp_path/'cell.qvf'; import_xsf(src, archive); clean(archive)
    out = tmp_path/'out.xsf'; result = export_xsf(archive, out)
    assert result['omitted_sections'] == []
    assert out.read_text().startswith(header+'\n')
    again = tmp_path/'again.qvf'; import_xsf(out, again); clean(again)
    with Reader(archive) as before, Reader(again) as after:
        assert before.json('structure', 'structure') == after.json('structure', 'structure')
        assert after.json('structure', 'structure')['pbc'] == pbc


@pytest.mark.parametrize('prefix', ['', 'MOLECULE\n'])
def test_molecule_and_finite_grid(tmp_path, prefix):
    src = tmp_path/'molecule.xsf'; src.write_text(prefix+'ATOMS\n8 0 0 0\nH 1 0 0\n'+GRID)
    archive = tmp_path/'molecule.qvf'; import_xsf(src, archive); clean(archive)
    out = tmp_path/'out.xsf'; export_xsf(archive, out, section='volume')
    with Reader(archive) as reader:
        assert reader.json('structure', 'structure')['lattice_vectors'] is None
    assert out.read_text().startswith('ATOMS\n')


@pytest.mark.parametrize('text', [
    '', 'ATOMS\n', 'ANIMSTEPS 1\n'+GEOMETRY, GEOMETRY.replace('PRIMVEC', 'CONVVEC'),
    GEOMETRY.replace('PRIMCOORD', 'PRIMCOORD 2'), GEOMETRY.replace('2 1\n', '2 2\n'),
    GEOMETRY.replace('H 1.1 1.2 1.3', 'H 1.1 1.2 1.3 0 0 0'),
    GEOMETRY.replace('H 1.1 1.2 1.3', 'X 1.1 1.2 1.3'),
    GEOMETRY.replace('H 1.1 1.2 1.3', '0 1.1 1.2 1.3'),
    GEOMETRY.replace('H 1.1 1.2 1.3', 'H nan 1.2 1.3'),
    GEOMETRY.replace('H 1.1 1.2 1.3', '# unexpected comment\nH 1.1 1.2 1.3'),
    GEOMETRY+GRID.replace('2 3 4\n', '1 3 4\n'),
    GEOMETRY+GRID.replace('2 3 4\n', '5000001 3 4\n'),
    GEOMETRY+GRID.replace('END_DATAGRID_3D', '999\nEND_DATAGRID_3D'),
    GEOMETRY+GRID.replace('END_DATAGRID_3D', 'BEGIN_DATAGRID_3D_other'),
    GEOMETRY+GRID.replace('0 100 10', '0 inf 10'),
    GEOMETRY+GRID.replace('2 0.1 0.2\n', '0 0 0\n'),
    GEOMETRY+GRID.replace('BEGIN_BLOCK_DATAGRID_3D', 'BEGIN_BLOCK_DATAGRID_2D'),
    GEOMETRY+GRID.replace('END_BLOCK_DATAGRID_3D', '').replace('END_DATAGRID_3D\n', ''),
    GEOMETRY+'BEGIN_BLOCK_DATAGRID_3D\nempty\nEND_BLOCK_DATAGRID_3D\n',
    GEOMETRY+GEOMETRY,
])
def test_unsupported_xsf_never_published(tmp_path, text):
    src = tmp_path/'invalid.xsf'; src.write_text(text)
    with pytest.raises(ValueError):
        import_xsf(src, tmp_path/'invalid.qvf')
    assert sorted(p.name for p in tmp_path.iterdir()) == ['invalid.xsf']


@pytest.mark.parametrize('options', [{'kind':'structure'}, {'periodic':[1,0,0]}, {'kind':'volume.density'}, {'periodic':[False]*3}])
def test_invalid_options_and_geometry_options(tmp_path, options):
    src = tmp_path/'geometry.xsf'; src.write_text(GEOMETRY)
    with pytest.raises(ValueError):
        import_xsf(src, tmp_path/'out.qvf', **options)
    assert not (tmp_path/'out.qvf').exists()


def test_periodic_declaration_must_match_cell(tmp_path):
    src = tmp_path/'cell.xsf'; src.write_text(GEOMETRY+GRID.replace('2 0.1 0.2\n', '3 0.1 0.2\n'))
    with pytest.raises(ValueError, match='validation'):
        import_xsf(src, tmp_path/'out.qvf', periodic=(True, True, True))
    assert not list(tmp_path.glob('.qvf-output-*'))
    src.write_text(GEOMETRY.replace('CRYSTAL', 'SLAB')+GRID)
    with pytest.raises(ValueError, match='matching periodic'):
        import_xsf(src, tmp_path/'out.qvf', periodic=(False, False, True))


def test_export_refuses_axis_permutation_and_missing_endpoints(tmp_path):
    from test_convert import CUBE
    src = tmp_path/'input.cube'; src.write_text(CUBE)
    no_endpoint = tmp_path/'no_endpoint.qvf'
    import_cube(src, no_endpoint, periodic=(True, True, True), includes_endpoint=False)
    with pytest.raises(ValueError, match='included endpoints'):
        export_xsf(no_endpoint, tmp_path/'out.xsf', section='volume')
    odd_axes = tmp_path/'odd_axes.qvf'; import_cube(src, odd_axes, periodic=(False, True, True))
    with pytest.raises(ValueError, match='leading cell axes'):
        export_xsf(odd_axes, tmp_path/'out.xsf', section='structure')
    assert not (tmp_path/'out.xsf').exists()


def test_atomic_existing_outputs_and_cli(tmp_path, capsys):
    from qvf.cli import main
    src = tmp_path/'input.xsf'; src.write_text(GEOMETRY+GRID)
    archive = tmp_path/'out.qvf'
    assert main(['convert',str(src),'--from','xsf','--to','qvf','-o',str(archive),
                 '--kind','volume.density','--periodic','true','true','true']) == 0
    assert json.loads(capsys.readouterr().out)['kind'] == 'volume.density'
    before = archive.read_bytes()
    with pytest.raises(FileExistsError):
        import_xsf(src, archive)
    assert archive.read_bytes() == before
    out = tmp_path/'out.xsf'
    assert main(['convert',str(archive),'--from','qvf','--to','xsf','--section','volume','-o',str(out)]) == 0
    assert json.loads(capsys.readouterr().out)['periodic'] == [True]*3
    before = out.read_bytes()
    with pytest.raises(FileExistsError):
        export_xsf(archive, out, section='volume')
    assert out.read_bytes() == before
    assert main(['convert',str(src),'--from','xsf','--to','qvf','-o',str(tmp_path/'bad.qvf'),'--no-endpoint']) == 2
    assert not (tmp_path/'bad.qvf').exists()


def test_no_numpy_and_independent_ase_reader(tmp_path):
    src = tmp_path/'input.xsf'; src.write_text(GEOMETRY+GRID)
    out = tmp_path/'out.xsf'
    code = '''import sys
sys.path.insert(0, sys.argv[1])
from qvf.convert import import_xsf, export_xsf
import_xsf(sys.argv[2], sys.argv[3])
export_xsf(sys.argv[3], sys.argv[4], section='volume')
assert 'numpy' not in sys.modules
'''
    result = subprocess.run([sys.executable,'-S','-c',code,str(Path(__file__).resolve().parents[1]),
                             str(src),str(tmp_path/'out.qvf'),str(out)],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    ase_xsf = pytest.importorskip('ase.io.xsf')
    with out.open() as stream:
        atoms, (data, origin, spans) = list(ase_xsf.iread_xsf(stream, read_data=True))
    assert data[1,2,3] == 123
    assert origin.tolist() == pytest.approx([.2,-.3,.4])
    assert spans[1].tolist() == pytest.approx([.3,4,.5])
    assert atoms.get_chemical_symbols() == ['C','H']
    assert atoms.positions[1].tolist() == pytest.approx([1.1,1.2,1.3])


def test_independent_ase_writer_and_float32_export(tmp_path):
    ase_xsf = pytest.importorskip('ase.io.xsf')
    np = pytest.importorskip('numpy')
    from ase import Atoms
    spans = [[2,.1,.2],[.3,4,.5],[.6,.7,6]]
    atoms = Atoms('CH', positions=[[.1,.2,.3],[1.1,1.2,1.3]], cell=spans, pbc=True)
    data = np.arange(24, dtype=np.float32).reshape(2,3,4)
    src = tmp_path/'ase.xsf'
    with src.open('w') as stream:
        ase_xsf.write_xsf(stream, [atoms], data=data, origin=[.2,-.3,.4], span_vectors=spans)
    archive = tmp_path/'ase.qvf'; import_xsf(src, archive, periodic=(True,True,True)); clean(archive)
    with Reader(archive) as reader:
        np.testing.assert_array_equal(reader.tensor('volume','data').tolist(), data)
        payload = reader.json('structure', 'structure')
        grid = reader.json('volume','grid')
    f32 = tmp_path/'float32.qvf'
    with Writer(f32, 'test', '1') as writer:
        writer.add_section({'id':'structure', 'kind':'structure'})
        writer.add_json('structure', 'structure', payload)
        writer.add_section({'id':'volume', 'kind':'volume.generic'})
        writer.add_json('volume', 'grid', grid)
        with writer.begin_binary('volume', 'data', dtype='float32', shape=[2,3,4]) as sink:
            sink.write(data.astype('<f4').tobytes())
    out = tmp_path/'float32.xsf'; export_xsf(f32, out, section='volume')
    with out.open() as stream:
        image, (actual, origin, actual_spans) = list(ase_xsf.iread_xsf(stream, read_data=True))
    np.testing.assert_array_equal(actual, data)
    np.testing.assert_allclose(actual_spans, spans, atol=1e-14)


def test_nonperiodic_cell_export_is_refused(tmp_path):
    from qvf.convert import import_xyz
    src = tmp_path/'input.xyz'
    src.write_text('1\nProperties=species:S:1:pos:R:3 Lattice="1 0 0 0 1 0 0 0 1" pbc="F F F"\nH 0 0 0\n')
    archive = tmp_path/'out.qvf'; import_xyz(src, archive)
    with pytest.raises(ValueError, match='nonperiodic cell'):
        export_xsf(archive, tmp_path/'out.xsf')
    assert not (tmp_path/'out.xsf').exists()


def test_forces_grids_and_conventional_cell(tmp_path):
    from qvf.convert import export_xsf
    text = (GEOMETRY.replace('# atoms\nPRIMCOORD', 'CONVVEC\n4 0 0\n0 8 0\n0 0 12\nPRIMCOORD')
            .replace('6 0.1 0.2 0.3', '6 0.1 0.2 0.3 0 0 0.5')
            .replace('H 1.1 1.2 1.3', 'H 1.1 1.2 1.3 0.01 -0.02 0.03'))
    text += 'CONVCOORD\n1 1\nH 0 0 0\n'
    second = GRID.replace('synthetic', 'other').replace('_samples', '_second')
    src = tmp_path/'rich.xsf'; src.write_text(text + GRID + second)
    out = tmp_path/'rich.qvf'
    report = import_xsf(src, out)
    assert run(out)['ok']
    assert report['forces'] is True and report['conventional_cell_omitted'] is True
    assert report['grids'] == [{'section': 'volume', 'label': 'synthetic/samples'},
                               {'section': 'volume_2', 'label': 'other/second'}]
    with Reader(out) as reader:
        gradient = reader.tensor('forces', 'gradient').tolist()
        assert [s.kind for s in reader.sections].count('volume.generic') == 2
    bohr = 1.8897261246257702
    assert gradient[-1] == pytest.approx([-0.01 / bohr, 0.02 / bohr, -0.03 / bohr])
    exported = tmp_path/'rich-out.xsf'
    report = export_xsf(out, exported, section='structure')
    assert report['forces'] is True and 'forces' not in report['omitted_sections']
    back = tmp_path/'back.qvf'
    import_xsf(exported, back)
    with Reader(back) as reader:
        assert sum(reader.tensor('forces', 'gradient').tolist(), []) == pytest.approx(
            sum(gradient, []))


def test_independent_ase_reads_xsf_forces(tmp_path):
    ase_io = pytest.importorskip('ase.io')
    from ase import Atoms
    from ase.calculators.singlepoint import SinglePointCalculator
    atoms = Atoms('OH', positions=[[0, 0, 0], [0.96, 0, 0]], cell=[5, 5, 5], pbc=True)
    atoms.calc = SinglePointCalculator(atoms, forces=[[0.5, -1, 2], [-0.5, 1, -2]])
    src = tmp_path/'ase.xsf'
    ase_io.write(str(src), atoms, format='xsf')
    out = tmp_path/'ase.qvf'
    assert import_xsf(src, out)['forces'] is True
    from qvf.convert import export_xsf
    exported = tmp_path/'out.xsf'
    export_xsf(out, exported, section='structure')
    back = ase_io.read(str(exported), format='xsf')
    assert back.get_forces().ravel().tolist() == pytest.approx([0.5, -1, 2, -0.5, 1, -2])
