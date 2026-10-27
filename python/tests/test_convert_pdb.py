"""PDB geometry conversion: fixed columns, explicit losses and strict choices."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qvf import Reader, Writer
from qvf.convert import import_pdb, export_pdb, import_xyz
from qvf.validate import run


def atom(serial=1, *, symbol="C", name=" CA ", xyz=(1.25, -2.5, 3.75),
         alt=" ", record="ATOM  ", charge="  "):
    return (f"{record}{serial:5d} {name}{alt}ALA A   1    "
            + ''.join(f"{v:8.3f}" for v in xyz)
            + f"  0.50 12.34          {symbol:>2s}{charge}\n")


def make_pdb(tmp_path, text):
    path = tmp_path/'input.pdb'
    path.write_text(text)
    return path


def structure(path):
    assert run(path)['ok']
    with Reader(path) as reader:
        assert [s.kind for s in reader.sections] == ['structure']
        assert 'provenance' not in reader.raw_manifest
        return reader.json('structure', 'structure')


def test_fixed_columns_elements_and_reported_losses(tmp_path):
    src = make_pdb(tmp_path, 'HEADER    synthetic coordinate example\n'
                   + 'CRYST1   10.000   10.000   10.000  90.00  90.00  90.00 P 1           1\n'
                   + atom(charge='1+') + atom(2, symbol='FE', record='HETATM')
                   + 'CONECT    1    2\nEND\n')
    output = tmp_path/'geometry.qvf'
    report = import_pdb(src, output)
    assert report['omitted_records'] == {'CONECT': 1, 'CRYST1': 1, 'HEADER': 1}
    assert report['atom_charge_fields_omitted'] == 1
    geometry = structure(output)
    assert geometry['atoms'] == [
        {'symbol': 'C', 'atomic_number': 6, 'position': [1.25, -2.5, 3.75]},
        {'symbol': 'Fe', 'atomic_number': 26, 'position': [1.25, -2.5, 3.75]}]
    assert geometry['pbc'] == [False] * 3 and geometry['lattice_vectors'] is None
    assert 'charge' not in geometry and 'multiplicity' not in geometry


def test_single_model_and_geometry_round_trip(tmp_path):
    src = make_pdb(tmp_path, 'NUMMDL       1\nMODEL        1\n' + atom()
                   + atom(2, symbol='CL', name='CL  ', xyz=(-999.999, 9999.999, 0))
                   + 'TER\nENDMDL\nEND\n')
    first = tmp_path/'first.qvf'
    assert import_pdb(src, first)['model'] == 1
    output = tmp_path/'out.pdb'
    report = export_pdb(first, output)
    assert report['max_rounding_error_angstrom'] == 0
    records = output.read_text().splitlines()
    assert all(len(row) == 80 for row in records)
    assert records[2][12:16] == ' C  ' and records[3][12:16] == 'CL  '
    assert records[3][76:78] == 'CL'
    again = tmp_path/'again.qvf'
    import_pdb(output, again)
    assert structure(again) == structure(first)


@pytest.mark.parametrize('text,reason', [
    ('', 'no atoms'),
    (atom(alt='A'), 'alternate locations'),
    (atom(alt='B') + atom(2, alt='A'), 'alternate locations'),
    ('MODEL        1\n' + atom() + 'ENDMDL\nMODEL        2\n' + atom() + 'ENDMDL\n', 'one model'),
    ('NUMMDL       2\n' + atom(), 'one model'),
    ('MODEL     10000\n' + atom() + 'ENDMDL\n', 'columns 11-14'),
    ('NUMMDL    10000\n' + atom(), 'columns 11-14'),
    ('MODEL        1\n' + atom(), 'missing ENDMDL'),
    ('ENDMDL\n' + atom(), 'nonempty MODEL'),
    ('MODEL        1\nENDMDL\n', 'nonempty MODEL'),
    ('MODEL        1\n' + atom() + 'ENDMDL\n' + atom(2), 'outside MODEL'),
    (atom() + 'MODEL        1\n' + atom(2) + 'ENDMDL\n', 'one model'),
    (atom() + 'END\n' + atom(2), 'after END'),
    (atom() + atom(), 'serials must be unique'),
    (atom(serial=0), 'positive decimal'),
    (atom().replace('    1 ', 'A0001 ', 1), 'positive decimal'),
    (atom().replace('    1 ', '100000', 1), 'separators'),
    (atom(symbol=''), 'element symbol'),
    (atom(symbol='D'), 'element symbol'),
    (atom()[:76] + '\n', 'element columns'),
    (atom(xyz=(float('nan'), 0, 0)), 'Real'),
    (atom().replace('   1.250', '  1.25e0'), 'Real'),
    (atom().replace('   1.250', '        '), 'Real'),
    (atom()[:-1] + 'extra\n', '80 columns'),
    (atom() + 'CUSTOM unsupported\n', 'unsupported PDB record'),
    (atom() + 'TITLE  non-ASCII \u00e9\n', 'ASCII'),
    (atom() + '\v', 'control characters'),
    (atom() + '\t\n', 'control characters'),
    (atom().replace('ATOM  ', ' ATOM ', 1), 'left-aligned'),
])
def test_unsupported_input_never_publishes(tmp_path, text, reason):
    src = make_pdb(tmp_path, text)
    with pytest.raises(ValueError, match=reason):
        import_pdb(src, tmp_path/'output.qvf')
    assert [p.name for p in tmp_path.iterdir()] == ['input.pdb']


def archive(tmp_path, position=(0.123456, -0.123456, 0), *, cell=None, count=1):
    path = tmp_path/'geometry.qvf'
    with Writer(path, 'qvf-test', '1') as writer:
        writer.add_section({'id': 'structure', 'kind': 'structure'})
        writer.add_json('structure', 'structure', {
            'atoms': [{'symbol': 'C', 'atomic_number': 6, 'position': list(position)}] * count,
            'pbc': [False] * 3, 'lattice_vectors': cell})
    return path


def test_export_reports_precision_and_omitted_sections(tmp_path):
    src = archive(tmp_path)
    output = tmp_path/'geometry.pdb'
    report = export_pdb(src, output)
    assert report['coordinate_precision_angstrom'] == .001
    assert report['max_rounding_error_angstrom'] == pytest.approx(.000456)
    assert 'no chemical or experimental meaning' in report['generated']
    restored = tmp_path/'round.qvf'; import_pdb(output, restored)
    assert structure(restored)['atoms'][0]['position'] == [.123, -.123, 0]


@pytest.mark.parametrize('kwargs,reason', [
    ({'position': (10000, 0, 0)}, 'overflow'),
    ({'position': (-1000, 0, 0)}, 'overflow'),
    ({'position': (9999.9999, 0, 0)}, 'overflow'),
    ({'cell': [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}, 'cell or periodicity'),
    ({'count': 10000}, '1-9999'),
])
def test_export_limit_refusals_are_atomic(tmp_path, kwargs, reason):
    src = archive(tmp_path, **kwargs)
    with pytest.raises(ValueError, match=reason):
        export_pdb(src, tmp_path/'output.pdb')
    assert [p.name for p in tmp_path.iterdir()] == ['geometry.qvf']


def test_trajectory_is_not_silently_reduced_to_initial_geometry(tmp_path):
    src = tmp_path/'frames.xyz'; src.write_text('1\n\nH 0 0 0\n1\n\nH 1 0 0\n')
    qvf = tmp_path/'frames.qvf'; import_xyz(src, qvf)
    with pytest.raises(ValueError, match='select a section'):
        export_pdb(qvf, tmp_path/'out.pdb')
    with pytest.raises(ValueError, match='not a trajectory'):
        export_pdb(qvf, tmp_path/'out.pdb', section='trajectory')
    report = export_pdb(qvf, tmp_path/'out.pdb', section='structure')
    assert report['omitted_sections'] == ['trajectory']


def test_existing_outputs_are_preserved(tmp_path):
    src = make_pdb(tmp_path, atom())
    qvf = tmp_path/'out.qvf'; import_pdb(src, qvf)
    before = qvf.read_bytes()
    with pytest.raises(FileExistsError):
        import_pdb(src, qvf)
    with pytest.raises(FileExistsError):
        export_pdb(qvf, src)
    assert qvf.read_bytes() == before and src.read_text() == atom()


def test_cli_conversion_and_invalid_options(tmp_path, capsys):
    from qvf.cli import main
    src = make_pdb(tmp_path, atom())
    qvf = tmp_path/'out.qvf'; output = tmp_path/'out.pdb'
    args = ['convert', str(src), '-o', str(qvf), '--from', 'pdb', '--to', 'qvf']
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)['atoms'] == 1
    assert main(['convert', str(qvf), '-o', str(output), '--from', 'qvf', '--to', 'pdb']) == 0
    assert json.loads(capsys.readouterr().out)['format'] == 'pdb'
    assert main(args + ['--periodic', 'true', 'true', 'true']) == 2
    assert 'only to cube/XSF import' in capsys.readouterr().err
    assert main(args + ['--section', 'structure']) == 2
    assert '--section applies only' in capsys.readouterr().err


def test_no_numpy_needed(tmp_path):
    src = make_pdb(tmp_path, atom())
    code = '''import sys
sys.path.insert(0, sys.argv[1])
from qvf.convert import import_pdb, export_pdb
import_pdb(sys.argv[2], sys.argv[3])
export_pdb(sys.argv[3], sys.argv[4])
assert 'numpy' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-S', '-c', code, str(Path(__file__).resolve().parents[1]),
                             str(src), str(tmp_path/'out.qvf'), str(tmp_path/'out.pdb')],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_independent_rdkit_coordinate_reader(tmp_path):
    chem = pytest.importorskip('rdkit.Chem')
    src = make_pdb(tmp_path, atom() + atom(2, symbol='CL', name='CL  ', xyz=(2, 3, 4)))
    qvf = tmp_path/'geometry.qvf'; import_pdb(src, qvf)
    out = tmp_path/'out.pdb'; export_pdb(qvf, out)
    molecule = chem.MolFromPDBFile(str(out), sanitize=False, removeHs=False, proximityBonding=False)
    assert molecule is not None and molecule.GetNumAtoms() == 2
    assert molecule.GetNumBonds() == 0
    assert [a.GetAtomicNum() for a in molecule.GetAtoms()] == [6, 17]
    coordinates = molecule.GetConformer()
    assert list(coordinates.GetAtomPosition(0)) == [1.25, -2.5, 3.75]
    assert list(coordinates.GetAtomPosition(1)) == [2, 3, 4]
