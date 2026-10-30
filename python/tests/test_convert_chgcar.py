"""VASP CHGCAR import/export (qvf.convert, issue #36)."""
import json
import math

import pytest

from qvf import Reader
from qvf.convert import export_chgcar, import_chgcar
from qvf.validate import run

BOHR = 1.8897261246257702  # bohr per angstrom, as the writer uses
HEAD = """synthetic Si cell
1.0
  3.0 0.0 0.0
  0.0 4.0 0.0
  1.0 0.0 5.0
Si
2
Direct
0 0 0
0.5 0.5 0.5
"""
SHAPE = (2, 3, 4)


def field(x, y, z, scale=1.0):
    return scale * (1 + x + 10 * y + 100 * z)


def grid_text(scale=1.0):
    nx, ny, nz = SHAPE
    values = [field(x, y, z, scale) for z in range(nz) for y in range(ny) for x in range(nx)]
    rows = [' '.join(f'{v:.11E}' for v in values[k:k + 5]) for k in range(0, len(values), 5)]
    return f"\n   {nx}   {ny}   {nz}\n" + '\n'.join(rows) + '\n'


AUGMENTATION = ("augmentation occupancies   1  4\n 0.1 0.2 0.3 0.4\n"
                "augmentation occupancies   2  4\n 0.1 0.2 0.3 0.4\n")


def write(tmp_path, text, name='CHGCAR'):
    path = tmp_path/name
    path.write_text(text)
    return path


def read(path, sid):
    with Reader(path) as reader:
        grid = reader.json(sid, 'grid')
        tensor = reader.tensor(sid, 'data')
        return grid, tensor.tolist() if hasattr(tensor, 'tolist') else tensor


def test_density_import_scales_and_reorders(tmp_path):
    out = tmp_path/'chg.qvf'
    report = import_chgcar(write(tmp_path, HEAD + grid_text() + AUGMENTATION), out)
    assert run(out)['ok']
    volume = 60.0
    assert report['spin'] == 'none' and report['shape'] == [2, 3, 4]
    assert report['cell_volume_angstrom3'] == pytest.approx(volume)
    assert report['lines_skipped'] == 4 and report['atoms'] == 2
    mean = sum(field(x, y, z) for x in range(2) for y in range(3) for z in range(4)) / 24
    assert report['electrons'] == pytest.approx(mean)
    grid, data = read(out, 'density')
    assert grid['includes_endpoint'] is False and grid['periodic'] == [True] * 3
    assert grid['origin'] == [0, 0, 0]
    assert grid['voxel_vectors'][2] == pytest.approx([1 * BOHR / 4, 0, 5 * BOHR / 4])
    for x, y, z in ((0, 0, 0), (1, 2, 3), (1, 0, 2)):
        assert data[x][y][z] == pytest.approx(field(x, y, z) / (volume * BOHR ** 3))


def test_collinear_and_noncollinear_magnetization(tmp_path):
    moments = " 0.000 0.000\n"
    text = HEAD + grid_text() + AUGMENTATION + moments + grid_text(-0.5) + AUGMENTATION
    out = tmp_path/'spin.qvf'
    report = import_chgcar(write(tmp_path, text), out)
    assert report['spin'] == 'collinear' and report['lines_skipped'] == 9
    with Reader(out) as reader:
        kinds = {s.id: s.kind for s in reader.sections}
    assert kinds['magnetization'] == 'volume.spin'
    _, data = read(out, 'magnetization')
    assert data[1][2][3] == pytest.approx(-0.5 * field(1, 2, 3) / (60 * BOHR ** 3))
    text = HEAD + grid_text() + grid_text(0.1) + grid_text(0.2) + grid_text(0.3)
    out = tmp_path/'ncl.qvf'
    report = import_chgcar(write(tmp_path, text, 'CHGCAR_ncl'), out)
    assert report['spin'] == 'noncollinear' and len(report['magnetization']) == 3
    _, data = read(out, 'magnetization')
    assert data[1][0][2] == pytest.approx(
        [s * field(1, 0, 2) / (60 * BOHR ** 3) for s in (0.1, 0.2, 0.3)])


@pytest.mark.parametrize('text, message', [
    (HEAD, 'grid dimension line'),
    (HEAD + grid_text() + grid_text(), None),
    (HEAD + grid_text() + grid_text() + grid_text(), r'1 \(no spin\), 2'),
    (HEAD + grid_text().rsplit('\n', 2)[0] + '\n', 'fewer values'),
    (HEAD + grid_text() + '\n 2 3 5\n' + ' 0.0' * 30 + '\n', 'share one shape'),
    (HEAD + grid_text() + grid_text().replace('E+', 'X+', 1), 'finite|could not|convert'),
])
def test_refusals(tmp_path, text, message):
    if message is None:
        import_chgcar(write(tmp_path, text), tmp_path/'ok.qvf')
        return
    with pytest.raises(ValueError, match=message):
        import_chgcar(write(tmp_path, text), tmp_path/'bad.qvf')
    assert not (tmp_path/'bad.qvf').exists()


def test_export_round_trip(tmp_path):
    text = HEAD + grid_text() + AUGMENTATION + grid_text(-0.5)
    qvf = tmp_path/'spin.qvf'
    import_chgcar(write(tmp_path, text), qvf)
    out = tmp_path/'CHGCAR.out'
    report = export_chgcar(qvf, out)
    assert report['spin'] == 'collinear' and report['magnetization_section'] == 'magnetization'
    assert report['omitted_sections'] == []
    again = tmp_path/'again.qvf'
    second = import_chgcar(out, again)
    assert second['spin'] == 'collinear' and second['lines_skipped'] == 0
    for sid in ('density', 'magnetization'):
        (g1, d1), (g2, d2) = read(qvf, sid), read(again, sid)
        assert g1['shape'] == g2['shape']
        for a, b in zip(sum(sum(d1, []), []), sum(sum(d2, []), [])):
            assert a == pytest.approx(b, rel=1e-10)


def test_export_refuses_cube_style_grids(tmp_path):
    from qvf.convert import import_cube
    cube = tmp_path/'f.cube'
    cube.write_text("c\nc\n1 0 0 0\n2 1 0 0\n2 0 1 0\n2 0 0 1\n1 1.0 0 0 0\n1 2 3 4 5 6 7 8\n")
    qvf = tmp_path/'cube.qvf'
    import_cube(cube, qvf, kind='volume.density')
    with pytest.raises(ValueError, match='periodic on all three axes|spans'):
        export_chgcar(qvf, tmp_path/'CHGCAR')


def test_independent_ase_reads_and_writes(tmp_path):
    vasp = pytest.importorskip('ase.calculators.vasp')
    text = HEAD + grid_text() + AUGMENTATION + grid_text(-0.5)
    qvf = tmp_path/'spin.qvf'
    import_chgcar(write(tmp_path, text), qvf)
    out = tmp_path/'CHGCAR.out'
    export_chgcar(qvf, out)
    density = vasp.VaspChargeDensity(str(out))
    # ASE divides by the cell volume: e / angstrom^3, indexed [x, y, z].
    assert density.chg[0].shape == SHAPE
    assert density.chg[0][1, 2, 3] == pytest.approx(field(1, 2, 3) / 60)
    assert density.chgdiff[0][1, 2, 3] == pytest.approx(-0.5 * field(1, 2, 3) / 60)
    written = tmp_path/'ase_CHGCAR'
    density.write(str(written), format='chgcar')
    report = import_chgcar(written, tmp_path/'ase.qvf')
    assert report['spin'] == 'collinear'
    (_, ours), (_, theirs) = read(qvf, 'density'), read(tmp_path/'ase.qvf', 'density')
    assert theirs[1][2][3] == pytest.approx(ours[1][2][3], rel=1e-6)


def test_cli_chgcar(tmp_path, capsys):
    from qvf.cli import main
    src = write(tmp_path, HEAD + grid_text())
    qvf = tmp_path/'cli.qvf'
    assert main(['convert', str(src), '-o', str(qvf), '--from', 'chgcar', '--to', 'qvf']) == 0
    report, _ = json.JSONDecoder().raw_decode(capsys.readouterr().out)
    # The mean of 1 + x + 10 y + 100 z over the grid.
    assert math.isclose(report['electrons'], 1 + 0.5 + 10 + 150, rel_tol=1e-12)
    assert main(['convert', str(qvf), '-o', str(tmp_path/'CHGCAR.out'), '--from', 'qvf',
                 '--to', 'chgcar']) == 0
