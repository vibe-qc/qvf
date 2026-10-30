"""mmCIF (PDBx) import/export (qvf.convert, issue #37)."""
import pytest

from qvf import Reader
from qvf.convert import export_mmcif, import_mmcif, import_pdb
from qvf.validate import run

MMCIF = """data_1ABC
_cell.length_a 40.000
_cell.length_b 50.000
_cell.length_c 60.000
_cell.angle_alpha 90.00
_cell.angle_beta 90.00
_cell.angle_gamma 90.00
_symmetry.space_group_name_H-M 'P 21 21 21'
loop_
_struct_conf.conf_type_id
_struct_conf.id
_struct_conf.beg_auth_asym_id
_struct_conf.beg_auth_seq_id
_struct_conf.pdbx_beg_PDB_ins_code
_struct_conf.end_auth_asym_id
_struct_conf.end_auth_seq_id
_struct_conf.pdbx_end_PDB_ins_code
_struct_conf.pdbx_PDB_helix_class
HELX_P HELX_P1 A 1 ? A 2 A 1
TURN_P TURN_P1 A 1 ? A 2 ? ?
_struct_sheet_range.sheet_id S1
_struct_sheet_range.id 1
_struct_sheet_range.beg_auth_asym_id A
_struct_sheet_range.beg_auth_seq_id 1
_struct_sheet_range.end_auth_asym_id A
_struct_sheet_range.end_auth_seq_id 2
loop_
_struct_conn.id
_struct_conn.conn_type_id
_struct_conn.ptnr1_auth_asym_id
_struct_conn.ptnr1_auth_comp_id
_struct_conn.ptnr1_auth_seq_id
_struct_conn.ptnr1_label_atom_id
_struct_conn.pdbx_ptnr1_PDB_ins_code
_struct_conn.ptnr1_symmetry
_struct_conn.ptnr2_auth_asym_id
_struct_conn.ptnr2_auth_comp_id
_struct_conn.ptnr2_auth_seq_id
_struct_conn.ptnr2_label_atom_id
_struct_conn.pdbx_ptnr2_PDB_ins_code
_struct_conn.ptnr2_symmetry
disulf1 disulf A CYS 1 SG ? 1_555 A CYS 2 SG A 1_555
metalc1 metalc A CYS 2 SG A 1_555 B ZN 101 ZN ? 1_555
hydrog1 hydrog A CYS 1 N ? 1_555 A CYS 2 O A 1_555
covale1 covale A CYS 1 SG ? 1_555 A CYS 2 SG A 2_655
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_atom_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . CYS A 1 ? 1.000 2.000 3.000 1.00 10.00 1 CYS A CA 1
ATOM 2 S SG . CYS A 1 ? 2.000 2.000 3.000 1.00 11.00 1 CYS A SG 1
ATOM 3 S SG A CYS A 2 A 4.000 2.000 3.000 0.60 12.00 2 CYS A SG 1
ATOM 4 S SG B CYS A 2 A 4.100 2.000 3.000 0.40 12.00 2 CYS A SG 1
HETATM 5 ZN ZN . ZN B . ? 6.000 2.000 3.000 1.00 20.00 101 ZN B ZN 1
"""


def write(tmp_path, text, name='in.cif'):
    path = tmp_path/name
    path.write_text(text)
    return path


def test_atom_sites_identity_cell_ranges_and_bonds(tmp_path):
    out = tmp_path/'m.qvf'
    report = import_mmcif(write(tmp_path, MMCIF), out)
    assert run(out)['ok']
    assert report['block'] == '1ABC' and report['atoms'] == 5
    assert report['sections'] == ['structure', 'symmetry']
    assert report['cell'] == {'space_group': 'P 21 21 21', 'expanded': False}
    assert report['bonds'] == {'ssbond': 2, 'link': 2}
    assert report['hydrogen_bonds_omitted'] == 1 and report['symmetry_mate_bonds_skipped'] == 1
    assert report['secondary_structure_ranges'] == 2 and report['other_struct_conf_omitted'] == 1
    assert report['alternate_location_atoms'] == 2
    with Reader(out) as reader:
        geometry = reader.json('structure', 'structure')
        raw = reader.raw_manifest['sections'][0]
        bonds = reader.json('structure', 'bonds')['pairs']
        assert reader.json('symmetry', 'data') == {'space_group_symbol': 'P 21 21 21'}
    assert geometry['pbc'] == [True] * 3
    assert geometry['atoms'][2] == {
        'symbol': 'S', 'atomic_number': 16, 'position': [4, 2, 3], 'atom_name': 'SG',
        'residue_name': 'CYS', 'residue_seq': 2, 'chain_id': 'A', 'insertion_code': 'A',
        'alt_loc': 'A', 'occupancy': 0.6, 'b_factor': 12, 'hetero': False}
    assert geometry['atoms'][4]['hetero'] is True and geometry['atoms'][4]['residue_seq'] == 101
    assert raw['secondary_structure'] == [
        {'type': 'helix', 'chain': 'A', 'start_seq': 1, 'end_seq': 2,
         'end_insertion_code': 'A', 'helix_class': 1},
        {'type': 'sheet', 'chain': 'A', 'start_seq': 1, 'end_seq': 2, 'sheet_id': 'S1',
         'strand': 1}]
    # No alternate location is named, so the disulfide joins SG 1 with both
    # alternates of SG 2A, and the zinc binds both as well.
    assert bonds == [{'i': 1, 'j': 2}, {'i': 1, 'j': 3}, {'i': 2, 'j': 4}, {'i': 3, 'j': 4}]


def test_models_follow_the_pdb_ensemble_rules(tmp_path):
    head, sites = MMCIF.split('loop_\n_struct_conf.conf_type_id')[0], MMCIF.split('loop_\n_atom_site.')
    lines = ('loop_\n_atom_site.' + sites[1]).strip().splitlines()
    loop = '\n'.join(lines[:20])
    rows = lines[20:]
    second = [r.replace(' 3.000 ', ' 3.500 ').rsplit(' ', 1)[0] + ' 2' for r in rows]
    out = tmp_path/'traj.qvf'
    report = import_mmcif(write(tmp_path, head + loop + '\n' + '\n'.join(rows + second) + '\n'),
                          out)
    assert report['ensemble'] == 'trajectory' and report['models'] == [1, 2]
    with Reader(out) as reader:
        assert reader.tensor('trajectory', 'coords').shape == (2, 5, 3)
    differing = [r.replace(' 12.00 ', ' 13.00 ') for r in second]
    report = import_mmcif(write(tmp_path, head + loop + '\n' + '\n'.join(rows + differing)
                                + '\n', 'b.cif'), tmp_path/'models.qvf')
    assert report['ensemble'] == 'structures'
    assert report['sections'][:2] == ['model_1', 'model_2']


@pytest.mark.parametrize('change, message', [
    (lambda t: t.replace('HETATM 5 ZN ZN', 'HETATM 5 Qq ZN'), 'type_symbol'),
    (lambda t: t.replace('6.000 2.000 3.000', '6.000 ? 3.000'), 'Cartesian'),
    (lambda t: t.replace('B ZN 101 ZN ? 1_555', 'B ZN 102 ZN ? 1_555'), 'not an atom'),
    (lambda t: t.replace('_cell.length_a 40.000\n', ''), 'six values'),
    (lambda t: t.replace('HELX_P HELX_P1 A 1 ? A 2', 'HELX_P HELX_P1 A 1 ? B 2'), 'one chain'),
    (lambda t: t.replace('HETATM 5', 'OTHER 5'), 'ATOM or HETATM'),
    (lambda t: t + t.replace('data_1ABC', 'data_2ABC'), 'select an mmCIF data block'),
])
def test_refusals(tmp_path, change, message):
    with pytest.raises(ValueError, match=message):
        import_mmcif(write(tmp_path, change(MMCIF)), tmp_path/'bad.qvf')
    assert not (tmp_path/'bad.qvf').exists()


def test_export_round_trip_and_gemmi(tmp_path):
    gemmi = pytest.importorskip('gemmi')
    qvf = tmp_path/'m.qvf'
    import_mmcif(write(tmp_path, MMCIF), qvf)
    out = tmp_path/'out.cif'
    report = export_mmcif(qvf, out)
    assert report['space_group'] == 'P 21 21 21' and report['max_rounding_error_angstrom'] == 0
    again = tmp_path/'again.qvf'
    import_mmcif(out, again)
    with Reader(qvf) as a, Reader(again) as b:
        assert a.json('structure', 'structure') == b.json('structure', 'structure')
    st = gemmi.read_structure(str(out))
    assert st.spacegroup_hm == 'P 21 21 21' and st.cell.a == pytest.approx(40)
    atoms = [(r.seqid.num, r.seqid.icode, a.name, a.altloc, r.het_flag)
             for ch in st[0] for r in ch for a in r]
    assert atoms == [(1, ' ', 'CA', '\0', 'A'), (1, ' ', 'SG', '\0', 'A'),
                     (2, 'A', 'SG', 'A', 'A'), (2, 'A', 'SG', 'B', 'A'),
                     (101, ' ', 'ZN', '\0', 'H')]


def test_gemmi_written_mmcif_matches_the_pdb_import(tmp_path):
    gemmi = pytest.importorskip('gemmi')
    import sys
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
    from test_convert_pdb import atom, cryst1
    pdb = tmp_path/'in.pdb'
    pdb.write_text(cryst1(40, 50, 60, 90, 90, 90, group='P 21 21 21', z=4)
                   + 'HELIX    1   1 ALA A    1  ALA A    2  1                                  \n'
                   + atom(1) + atom(2, name=' CB ', alt='A', xyz=(2, 2, 3))
                   + atom(3, name=' CB ', alt='B', xyz=(2.1, 2, 3), occupancy='  0.50')
                   + atom(4, seq=2, code='A', xyz=(4, 1, 0))
                   + atom(5, symbol='ZN', name='ZN  ', residue='ZN', chain='B', seq=101,
                          record='HETATM', xyz=(7, 1, 1)) + 'END\n')
    from_pdb = tmp_path/'pdb.qvf'; import_pdb(pdb, from_pdb)
    st = gemmi.read_structure(str(pdb))
    st.setup_entities()
    doc = st.make_mmcif_document()
    cif = tmp_path/'gemmi.cif'; doc.write_file(str(cif))
    from_cif = tmp_path/'cif.qvf'
    import_mmcif(cif, from_cif)
    with Reader(from_pdb) as a, Reader(from_cif) as b:
        assert b.json('structure', 'structure') == a.json('structure', 'structure')
        assert b.json('symmetry', 'data') == a.json('symmetry', 'data')
        ra = next(s for s in a.raw_manifest['sections'] if s['id'] == 'structure')
        rb = next(s for s in b.raw_manifest['sections'] if s['id'] == 'structure')
        assert rb['residues'] == ra['residues'] and rb['chains'] == ra['chains']


def test_cli_mmcif(tmp_path):
    from qvf.cli import main
    src = write(tmp_path, MMCIF)
    qvf = tmp_path/'cli.qvf'
    assert main(['convert', str(src), '-o', str(qvf), '--from', 'mmcif', '--to', 'qvf',
                 '--block', '1abc']) == 0
    assert main(['convert', str(qvf), '-o', str(tmp_path/'cli.cif'), '--from', 'qvf',
                 '--to', 'mmcif']) == 0
