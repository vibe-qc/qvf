"""PDB conversion: fixed columns, atom-site identity, ensembles, explicit losses."""
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
         alt=" ", record="ATOM  ", charge="  ", residue="ALA", chain="A", seq=1,
         code=" ", occupancy="  0.50", b_factor=" 12.34"):
    return (f"{record}{serial:5d} {name}{alt}{residue:>3s} {chain}{seq:4d}{code}   "
            + ''.join(f"{v:8.3f}" for v in xyz)
            + f"{occupancy}{b_factor}          {symbol:>2s}{charge}\n")


CA = {'atom_name': 'CA', 'residue_name': 'ALA', 'residue_seq': 1, 'chain_id': 'A',
      'occupancy': 0.5, 'b_factor': 12.34}


def make_pdb(tmp_path, text):
    path = tmp_path/'input.pdb'
    path.write_text(text)
    return path


def structure(path, *, section=False):
    assert run(path)['ok']
    with Reader(path) as reader:
        assert [s.kind for s in reader.sections] == ['structure']
        assert 'provenance' not in reader.raw_manifest
        payload = reader.json('structure', 'structure')
        if not section:
            return payload
        raw = next(s for s in reader.raw_manifest['sections'] if s['id'] == 'structure')
        return payload, {k: raw[k] for k in ('chains', 'residues') if k in raw}


def test_fixed_columns_elements_and_reported_losses(tmp_path):
    src = make_pdb(tmp_path, 'HEADER    synthetic coordinate example\n'
                   + 'ORIGX1      1.000000  0.000000  0.000000        0.00000\n'
                   + atom(charge='1+') + atom(2, symbol='FE', record='HETATM')
                   + 'CONECT    1    2\nEND\n')
    output = tmp_path/'geometry.qvf'
    report = import_pdb(src, output)
    assert report['omitted_records'] == {'HEADER': 1, 'ORIGX1': 1}
    assert report['bonds'] == 1
    assert report['atom_charge_fields_omitted'] == 1
    geometry = structure(output)
    assert geometry['atoms'] == [
        {'symbol': 'C', 'atomic_number': 6, 'position': [1.25, -2.5, 3.75], **CA,
         'hetero': False},
        {'symbol': 'Fe', 'atomic_number': 26, 'position': [1.25, -2.5, 3.75], **CA,
         'hetero': True}]
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
    assert report['atom_site_identity'] is True
    assert records[1][12:16] == ' CA ' and records[2][12:16] == 'CL  '
    assert records[2][76:78] == 'CL'
    again = tmp_path/'again.qvf'
    import_pdb(output, again)
    assert structure(again) == structure(first)



def test_insertion_codes_alternate_locations_and_residues(tmp_path):
    # Residues 10 and 10A stay two residues; the alternate locations of SER
    # OG are two atoms, in source order, each with its occupancy; and the
    # microheterogeneous site 11 (ALA/GLY under altlocs) is one residue.
    src = make_pdb(tmp_path, atom(1, name=' N  ', symbol='N', residue='SER', seq=10)
                   + atom(2, name=' OG ', symbol='O', residue='SER', seq=10, alt='A',
                          occupancy='  0.60')
                   + atom(3, name=' OG ', symbol='O', residue='SER', seq=10, alt='B',
                          occupancy='  0.40')
                   + atom(4, name=' N  ', symbol='N', residue='GLY', seq=10, code='A')
                   + atom(5, name=' CA ', residue='ALA', seq=11, alt='A')
                   + atom(6, name=' CA ', residue='GLY', seq=11, alt='B')
                   + atom(7, name='ZN  ', symbol='ZN', residue=' ZN', chain='B', seq=-1,
                          record='HETATM', occupancy='      ', b_factor='      '))
    qvf = tmp_path/'site.qvf'
    report = import_pdb(src, qvf)
    assert report['alternate_location_atoms'] == 4 and report['residues_listed']
    payload, fields = structure(qvf, section=True)
    atoms = payload['atoms']
    assert [a.get('alt_loc') for a in atoms] == [None, 'A', 'B', None, 'A', 'B', None]
    assert [a.get('occupancy') for a in atoms[:3]] == [0.5, 0.6, 0.4]
    assert atoms[3]['insertion_code'] == 'A'
    assert atoms[6] == {'symbol': 'Zn', 'atomic_number': 30, 'position': [1.25, -2.5, 3.75],
                        'atom_name': 'ZN', 'residue_name': 'ZN', 'residue_seq': -1,
                        'chain_id': 'B', 'hetero': True}
    assert fields['chains'] == ['A', 'B']
    assert fields['residues'] == [
        {'name': 'SER', 'seq': 10, 'chain': 'A', 'atom_indices': [0, 1, 2]},
        {'name': 'GLY', 'seq': 10, 'chain': 'A', 'insertion_code': 'A', 'atom_indices': [3]},
        {'name': 'ALA', 'seq': 11, 'chain': 'A', 'atom_indices': [4, 5]},
        {'name': 'ZN', 'seq': -1, 'chain': 'B', 'atom_indices': [6]}]
    out = tmp_path/'site.pdb'
    assert export_pdb(qvf, out)['atom_site_identity'] is True
    records = out.read_text().splitlines()
    assert records[2][16] == 'A' and records[4][26] == 'A' and records[7][:6] == 'HETATM'
    assert records[7][54:66] == ' ' * 12 and records[7][12:16] == 'ZN  '
    again = tmp_path/'again.qvf'; import_pdb(out, again)
    assert structure(again, section=True) == (payload, fields)


def test_blank_columns_are_absent_not_placeholders(tmp_path):
    src = make_pdb(tmp_path, atom(chain=' ', occupancy='      ', b_factor='      ')
                   + atom(2, residue='   ', seq=2))
    qvf = tmp_path/'blank.qvf'
    assert import_pdb(src, qvf)['residues_listed'] is False
    payload, fields = structure(qvf, section=True)
    assert payload['atoms'][0].keys() == {'symbol', 'atomic_number', 'position', 'atom_name',
                                          'residue_name', 'residue_seq', 'hetero'}
    assert 'residue_name' not in payload['atoms'][1] and fields == {}
    # Without a residue name on every atom, export keeps synthetic residues.
    out = tmp_path/'blank.pdb'
    assert export_pdb(qvf, out)['atom_site_identity'] is False
    assert 'UNL' in out.read_text()


def models(*bodies, serials=None):
    return ''.join(f'MODEL     {n:4d}\n{body}ENDMDL\n'
                   for n, body in zip(serials or range(1, len(bodies) + 1), bodies)) + 'END\n'


def test_ensemble_with_shared_atoms_is_structure_plus_trajectory(tmp_path):
    body = lambda dx: atom(xyz=(1 + dx, 2, 3)) + atom(2, name=' CB ', xyz=(2 + dx, 2, 3))
    src = make_pdb(tmp_path, 'NUMMDL       3\n' + models(body(0), body(.5), body(1),
                                                         serials=(1, 2, 5)))
    qvf = tmp_path/'nmr.qvf'
    report = import_pdb(src, qvf)
    assert report['ensemble'] == 'trajectory' and report['models'] == [1, 2, 5]
    assert report['sections'] == ['structure', 'trajectory'] and report['model'] is None
    assert run(qvf)['ok']
    with Reader(qvf) as reader:
        assert [s.kind for s in reader.sections] == ['structure', 'trajectory']
        meta = reader.json('trajectory', 'metadata')
        assert meta['model_serials'] == [1, 2, 5] and meta['symbols'] == ['C', 'C']
        coords = reader.tensor('trajectory', 'coords')
        assert coords.shape == (3, 2, 3)
        assert coords.tolist()[2][1] == [3.0, 2.0, 3.0]
        assert reader.json('structure', 'structure')['atoms'][1]['atom_name'] == 'CB'
    # Export still writes one selected structure: model 1.
    out = tmp_path/'model1.pdb'
    assert export_pdb(qvf, out, section='structure')['omitted_sections'] == ['trajectory']


def test_ensemble_with_differing_atoms_is_one_structure_per_model(tmp_path):
    src = make_pdb(tmp_path, models(atom(), atom(b_factor=' 20.00'), atom() + atom(2)))
    qvf = tmp_path/'ensemble.qvf'
    report = import_pdb(src, qvf)
    assert report['ensemble'] == 'structures'
    assert report['sections'] == ['model_1', 'model_2', 'model_3']
    assert run(qvf)['ok']
    with Reader(qvf) as reader:
        raw = {s['id']: s for s in reader.raw_manifest['sections']}
        assert [raw[i]['label'] for i in report['sections']] == ['MODEL 1', 'MODEL 2', 'MODEL 3']
        assert reader.json('model_2', 'structure')['atoms'][0]['b_factor'] == 20.0
        assert len(reader.json('model_3', 'structure')['atoms']) == 2
        assert raw['model_3']['residues'][0]['atom_indices'] == [0, 1]
    with pytest.raises(ValueError, match='select a section'):
        export_pdb(qvf, tmp_path/'out.pdb')
    assert export_pdb(qvf, tmp_path/'out.pdb', section='model_2')['atoms'] == 1


@pytest.mark.parametrize('change,reason', [
    ({'residue_seq': 10000}, '-999..9999'),
    ({'residue_seq': 1.5}, '-999..9999'),
    ({'atom_name': 'CAXYZ'}, 'fixed columns'),
    ({'residue_name': 'ALAX'}, 'fixed columns'),
    ({'chain_id': 'AB'}, 'fixed columns'),
    ({'b_factor': 1000.0}, 'temperature factor overflows'),
])
def test_identity_export_refusals_are_atomic(tmp_path, change, reason):
    path = tmp_path/'identity.qvf'
    with Writer(path, 'qvf-test', '1') as writer:
        writer.add_section({'id': 'structure', 'kind': 'structure'})
        writer.add_json('structure', 'structure', {'atoms': [
            {'symbol': 'C', 'atomic_number': 6, 'position': [0, 0, 0], **CA, **change}],
            'pbc': [False] * 3, 'lattice_vectors': None})
    with pytest.raises(ValueError, match=reason):
        export_pdb(path, tmp_path/'output.pdb')
    assert [p.name for p in tmp_path.iterdir()] == ['identity.qvf']


def helix(serial, start, end, *, chain='A', cls=' 1', start_code=' ', end_code=' ',
          residue='ALA'):
    return (f"HELIX  {serial:3d} {serial:>3d} {residue} {chain} {start:4d}{start_code} "
            f"{residue} {chain} {end:4d}{end_code}{cls}\n")


def sheet(strand, sheet_id, count, start, end, *, chain='A', start_code=' ', end_code=' ',
          residue='ALA', sense=' 0'):
    return (f"SHEET  {strand:3d} {sheet_id:>3s}{count:2d} {residue} {chain}{start:4d}"
            f"{start_code} {residue} {chain}{end:4d}{end_code}{sense}\n")


def trace(*residues):
    return ''.join(atom(i, seq=seq, code=code) for i, (seq, code) in enumerate(residues, 1))


def test_helix_and_sheet_records_become_typed_ranges(tmp_path):
    src = make_pdb(tmp_path, helix(1, 10, 11, start_code='A', cls=' 5')
                   + helix(2, 12, 13, cls='  ')
                   + sheet(1, 'S1', 2, 12, 14, sense=' 0') + sheet(2, 'S1', 2, 20, 21, sense='-1')
                   + trace((10, ' '), (10, 'A'), (11, ' '), (12, ' '), (13, ' ')) + 'END\n')
    qvf = tmp_path/'ranges.qvf'
    report = import_pdb(src, qvf)
    assert report['secondary_structure_ranges'] == 4
    # Residue 14 and the second strand's residues 20-21 are not in the file.
    assert report['secondary_structure_unresolved'] == 2
    assert 'HELIX' not in report['omitted_records']
    payload, _ = structure(qvf, section=True)
    with Reader(qvf) as reader:
        ranges = reader.raw_manifest['sections'][0]['secondary_structure']
    assert ranges == [
        {'type': 'helix', 'chain': 'A', 'start_seq': 10, 'start_insertion_code': 'A',
         'end_seq': 11, 'helix_class': 5},
        {'type': 'helix', 'chain': 'A', 'start_seq': 12, 'end_seq': 13},
        {'type': 'sheet', 'chain': 'A', 'start_seq': 12, 'end_seq': 14, 'sheet_id': 'S1',
         'strand': 1},
        {'type': 'sheet', 'chain': 'A', 'start_seq': 20, 'end_seq': 21, 'sheet_id': 'S1',
         'strand': 2}]
    out = tmp_path/'ranges.pdb'
    assert export_pdb(qvf, out)['coil_ranges_omitted'] == 0
    records = out.read_text().splitlines()
    assert records[1][:6] == 'HELIX ' and records[1][25] == 'A' and records[1][38:40] == ' 5'
    assert records[3][:6] == 'SHEET ' and records[3][11:16] == ' S1 2'
    again = tmp_path/'again.qvf'; import_pdb(out, again)
    with Reader(again) as reader:
        assert reader.raw_manifest['sections'][0]['secondary_structure'] == ranges
    assert structure(again) == payload


def test_ranges_apply_to_every_model_section(tmp_path):
    src = make_pdb(tmp_path, helix(1, 1, 2) + models(atom() + atom(2, seq=2),
                                                     atom(b_factor=' 20.00') + atom(2, seq=2)))
    qvf = tmp_path/'ensemble.qvf'
    assert import_pdb(src, qvf)['sections'] == ['model_1', 'model_2']
    with Reader(qvf) as reader:
        assert all(s['secondary_structure'][0]['helix_class'] == 1
                   for s in reader.raw_manifest['sections'])


def test_coil_ranges_are_counted_not_written(tmp_path):
    path = tmp_path/'coil.qvf'
    with Writer(path, 'qvf-test', '1') as writer:
        writer.add_section({'id': 'structure', 'kind': 'structure', 'secondary_structure': [
            {'type': 'coil', 'chain': 'A', 'start_seq': 1, 'end_seq': 1},
            {'type': 'sheet', 'chain': 'A', 'start_seq': 1, 'end_seq': 1}]})
        writer.add_json('structure', 'structure', {'atoms': [
            {'symbol': 'C', 'atomic_number': 6, 'position': [0, 0, 0], **CA}],
            'pbc': [False] * 3, 'lattice_vectors': None})
    out = tmp_path/'coil.pdb'
    assert export_pdb(path, out)['coil_ranges_omitted'] == 1
    records = [r for r in out.read_text().splitlines() if r[:6] in ('HELIX ', 'SHEET ')]
    assert records == ['SHEET    1  S2 1 ALA A   1  ALA A   1  0'.ljust(80)]


def conect(serial, *partners, extra=''):
    return f"CONECT{serial:5d}" + ''.join(f"{p:5d}" for p in partners) + extra + "\n"


def bonds_of(path, sid='structure'):
    with Reader(path) as reader:
        return reader.json(sid, 'bonds')['pairs']


def test_conect_records_become_the_structure_bonds_member(tmp_path):
    # Serials 10, 20, 30, 40: CONECT addresses serials, bonds address 0-based
    # positions. 10-20 is listed from both atoms (normal) and 10-30 twice from
    # atom 10 (a nonstandard double-bond hint, counted, not read as order).
    body = (atom(10) + atom(20, name=' CB ') + atom(30, name=' O  ', symbol='O')
            + atom(40, name=' N  ', symbol='N'))
    src = make_pdb(tmp_path, body + conect(10, 20, 30, 30) + conect(20, 10)
                   + conect(30, 10, 10, extra=' ' * 10 + '   40') + conect(40, 20) + 'END\n')
    qvf = tmp_path/'bonds.qvf'
    report = import_pdb(src, qvf)
    assert report['bonds'] == 3 and report['conect_repeated_listings'] == 2
    assert report['conect_hydrogen_bond_fields_omitted'] == 1
    assert 'CONECT' not in report['omitted_records']
    assert bonds_of(qvf) == [{'i': 0, 'j': 1}, {'i': 0, 'j': 2}, {'i': 1, 'j': 3}]
    out = tmp_path/'bonds.pdb'
    exported = export_pdb(qvf, out)
    assert exported['bonds'] == 3 and exported['bond_orders_not_written'] == 0
    records = [r.rstrip() for r in out.read_text().splitlines() if r.startswith('CONECT')]
    assert records == ['CONECT    1    2    3', 'CONECT    2    1    4',
                       'CONECT    3    1', 'CONECT    4    2']
    again = tmp_path/'again.qvf'; import_pdb(out, again)
    assert bonds_of(again) == bonds_of(qvf)
    assert structure(again) == structure(qvf)


def test_conect_wraps_at_four_partners_and_reports_orders(tmp_path):
    path = tmp_path/'hub.qvf'
    hub = [{'symbol': 'C', 'atomic_number': 6, 'position': [i, 0, 0]} for i in range(6)]
    with Writer(path, 'qvf-test', '1') as writer:
        writer.add_section({'id': 'structure', 'kind': 'structure'})
        writer.add_json('structure', 'structure', {'atoms': hub, 'pbc': [False] * 3,
                                                   'lattice_vectors': None})
        writer.add_section({'id': 'bonds', 'kind': 'bonds', 'structure_ref': 'structure'})
        writer.add_json('bonds', 'bonds', {'pairs': [
            {'i': 0, 'j': k, 'order': 2 if k == 1 else 1} for k in range(1, 6)]})
    out = tmp_path/'hub.pdb'
    report = export_pdb(path, out)
    assert report['bonds'] == 5 and report['bond_orders_not_written'] == 1
    assert report['omitted_sections'] == []
    records = [r.rstrip() for r in out.read_text().splitlines() if r.startswith('CONECT')]
    assert records[:2] == ['CONECT    1    2    3    4    5', 'CONECT    1    6']
    assert 'CONECT, NO BOND ORDERS' in out.read_text()


def test_conect_resolves_serials_within_each_model(tmp_path):
    one = atom(1) + atom(2, name=' CB ')
    differing = atom(1) + atom(2, name=' CB ', b_factor=' 20.00')
    src = make_pdb(tmp_path, models(one, differing).replace('END\n', '') + conect(1, 2)
                   + 'END\n')
    qvf = tmp_path/'models.qvf'
    assert import_pdb(src, qvf)['sections'] == ['model_1', 'model_2']
    assert bonds_of(qvf, 'model_1') == bonds_of(qvf, 'model_2') == [{'i': 0, 'j': 1}]
    shared = make_pdb(tmp_path, models(one, one).replace('END\n', '') + conect(1, 2))
    traj = tmp_path/'traj.qvf'
    assert import_pdb(shared, traj)['ensemble'] == 'trajectory'
    assert bonds_of(traj) == [{'i': 0, 'j': 1}]


def test_independent_rdkit_reads_conect(tmp_path):
    chem = pytest.importorskip('rdkit.Chem')
    src = make_pdb(tmp_path, atom(1, record='HETATM', residue='LIG') +
                   atom(2, name=' O  ', symbol='O', record='HETATM', residue='LIG')
                   + atom(3, name=' N  ', symbol='N', record='HETATM', residue='LIG')
                   + conect(1, 2, 3))
    qvf = tmp_path/'lig.qvf'; import_pdb(src, qvf)
    out = tmp_path/'lig.pdb'; export_pdb(qvf, out)
    molecule = chem.MolFromPDBFile(str(out), sanitize=False, removeHs=False,
                                   proximityBonding=False)
    assert sorted(tuple(sorted((b.GetBeginAtomIdx(), b.GetEndAtomIdx())))
                  for b in molecule.GetBonds()) == [(0, 1), (0, 2)]


def ssbond(serial, first, second, ops=('', ''), length=2.04):
    """wwPDB SSBOND columns; ``first``/``second`` are (chain, seq, icode)."""
    (c1, s1, i1), (c2, s2, i2) = first, second
    return (f"SSBOND{serial:4d} CYS {c1}{s1:5d}{i1}   CYS {c2}{s2:5d}{i2}" + ' ' * 23
            + f"{ops[0]:>6s} {ops[1]:>6s} {length:5.2f}\n")


def link(first, second, ops=('', ''), length=2.30):
    """wwPDB LINK columns; an end is (name, altloc, residue, chain, seq, icode)."""
    def end(name, alt, residue, chain, seq, code):
        return f"{name}{alt}{residue:>3s} {chain}{seq:4d}{code}"
    return ("LINK" + ' ' * 8 + end(*first) + ' ' * 15 + end(*second) + '  '
            + f"{ops[0]:>6s} {ops[1]:>6s} {length:5.2f}\n")


def cysteines(alternates=False):
    """CYS A1 and A5 (CA, SG) and a zinc ion A101; SG atoms optionally in
    alternate locations A and B."""
    rows, serial = [], 1
    for seq, x in ((1, 0.0), (5, 4.0)):
        rows.append(atom(serial, residue='CYS', seq=seq, xyz=(x, 0, 0))); serial += 1
        for alt in ('A', 'B') if alternates else (' ',):
            rows.append(atom(serial, symbol='S', name=' SG ', residue='CYS', seq=seq, alt=alt,
                             xyz=(x + 1, 1 if alt != 'B' else 1.2, 0)))
            serial += 1
    rows.append(atom(serial, symbol='ZN', name='ZN  ', residue='ZN', seq=101, record='HETATM',
                     xyz=(5, 3, 0)))
    return ''.join(rows)


SG5, ZN = (' SG ', ' ', 'CYS', 'A', 5, ' '), ('ZN  ', ' ', ' ZN', 'A', 101, ' ')


def test_ssbond_and_link_become_bonds(tmp_path):
    # Atoms: 0 CA1, 1 SG1, 2 CA5, 3 SG5, 4 ZN. The disulfide is also listed
    # by CONECT (as wwPDB files do); a disulfide to a symmetry mate is skipped.
    src = make_pdb(tmp_path, ssbond(1, ('A', 1, ' '), ('A', 5, ' '))
                   + ssbond(2, ('A', 5, ' '), ('A', 5, ' '), ops=('1555', '2655'))
                   + link(ZN, SG5) + cysteines() + conect(2, 4) + conect(4, 2)
                   + conect(1, 3) + 'END\n')
    qvf = tmp_path/'links.qvf'
    report = import_pdb(src, qvf)
    assert report['ssbond'] == {'records': 2, 'bonds': 1, 'also_conect': 1}
    assert report['link'] == {'records': 1, 'bonds': 1, 'also_conect': 0}
    assert report['symmetry_mate_bonds_skipped'] == {'records': 1,
                                                     'operators': ['1555 2655']}
    assert report['bonds'] == 3 and 'SSBOND' not in report['omitted_records']
    assert bonds_of(qvf) == [{'i': 0, 'j': 2}, {'i': 1, 'j': 3}, {'i': 3, 'j': 4}]
    out = tmp_path/'links.pdb'
    exported = export_pdb(qvf, out)
    # CA1-CA5 joins two standard residues without SG: CONECT only.
    assert exported['ssbond_records'] == 1 and exported['link_records'] == 1
    records = out.read_text().splitlines()
    kinds = [r[:6].strip() for r in records]
    assert kinds.index('SSBOND') < kinds.index('LINK') < kinds.index('ATOM')
    ss = records[kinds.index('SSBOND')]
    assert (ss[11:14], ss[15], ss[17:21], ss[25:28], ss[29], ss[31:35]) == \
        ('CYS', 'A', '   1', 'CYS', 'A', '   5')
    assert (ss[59:65], ss[66:72], ss[73:78]) == ('  1555', '  1555', ' 4.00')
    ln = records[kinds.index('LINK')]
    assert (ln[12:16], ln[17:20], ln[22:26], ln[42:46], ln[47:50], ln[52:56]) == \
        (' SG ', 'CYS', '   5', 'ZN  ', ' ZN', ' 101')
    assert ln[73:78] == ' 2.00'
    again = tmp_path/'again.qvf'
    second = import_pdb(out, again)
    assert bonds_of(again) == bonds_of(qvf)
    assert second['ssbond']['also_conect'] == 1 and second['link']['also_conect'] == 1


def test_ssbond_and_link_follow_alternate_locations(tmp_path):
    # Atoms: 0 CA1, 1 SG1 A, 2 SG1 B, 3 CA5, 4 SG5 A, 5 SG5 B, 6 ZN.
    src = make_pdb(tmp_path, ssbond(1, ('A', 1, ' '), ('A', 5, ' '))
                   + link(ZN[:1] + ('A',) + ZN[2:], (' SG ', 'A') + SG5[2:])
                   + cysteines(alternates=True))
    qvf = tmp_path/'alt.qvf'
    report = import_pdb(src, qvf)
    # A blank altloc names both alternates, each paired with its own; the
    # zinc has no alternates, so altloc A names it as well.
    assert bonds_of(qvf) == [{'i': 1, 'j': 4}, {'i': 2, 'j': 5}, {'i': 4, 'j': 6}]
    assert report['ssbond']['bonds'] == 2 and report['link']['bonds'] == 1
    out = tmp_path/'alt.pdb'
    exported = export_pdb(qvf, out)
    assert exported['ssbond_records'] == 1 and exported['link_records'] == 1
    ln = next(r for r in out.read_text().splitlines() if r.startswith('LINK'))
    assert (ln[16], ln[46]) == ('A', ' ')
    again = tmp_path/'again.qvf'; import_pdb(out, again)
    assert bonds_of(again) == bonds_of(qvf)


@pytest.mark.parametrize('records, message', [
    (link(ZN, (' SG ', ' ', 'CYS', 'A', 7, ' ')), 'not an atom'),
    (link(ZN, (' SG ', ' ', 'ALA', 'A', 5, ' ')), 'not an atom'),
    (link(ZN, ZN), 'itself'),
    (ssbond(1, ('A', 1, ' '), ('A', 5, ' '), ops=('1555', 'x555')), 'symmetry operators'),
    (link(ZN, ('    ',) + SG5[1:]), 'residue and atom names'),
    (ssbond(1, ('A', 1, ' '), ('B', 5, ' ')), 'not an atom'),
])
def test_ssbond_and_link_refuse_unresolvable_atoms(tmp_path, records, message):
    src = make_pdb(tmp_path, records + cysteines())
    with pytest.raises(ValueError, match=message):
        import_pdb(src, tmp_path/'bad.qvf')
    assert not (tmp_path/'bad.qvf').exists()


def test_link_refuses_ambiguous_and_incompatible_alternates(tmp_path):
    twice = cysteines() + atom(9, symbol='ZN', name='ZN  ', residue='ZN', seq=101,
                               record='HETATM', xyz=(6, 3, 0))
    with pytest.raises(ValueError, match='ambiguous'):
        import_pdb(make_pdb(tmp_path, link(ZN, SG5) + twice), tmp_path/'a.qvf')
    apart = (atom(1, symbol='S', name=' SG ', residue='CYS', seq=1, alt='A')
             + atom(2, symbol='S', name=' SG ', residue='CYS', seq=5, alt='B',
                    xyz=(3, 0, 0)))
    with pytest.raises(ValueError, match='no common alternate'):
        import_pdb(make_pdb(tmp_path, ssbond(1, ('A', 1, ' '), ('A', 5, ' ')) + apart),
                   tmp_path/'b.qvf')


def test_link_resolves_within_each_model(tmp_path):
    one = cysteines()
    differing = cysteines().replace(' 12.34', ' 20.00')
    src = make_pdb(tmp_path, link(ZN, SG5) + models(one, differing))
    qvf = tmp_path/'models.qvf'
    assert import_pdb(src, qvf)['sections'] == ['model_1', 'model_2']
    assert bonds_of(qvf, 'model_1') == bonds_of(qvf, 'model_2') == [{'i': 3, 'j': 4}]


def test_independent_gemmi_reads_ssbond_and_link(tmp_path):
    gemmi = pytest.importorskip('gemmi')
    src = make_pdb(tmp_path, ssbond(1, ('A', 1, ' '), ('A', 5, ' ')) + link(ZN, SG5)
                   + cysteines())
    qvf = tmp_path/'links.qvf'; import_pdb(src, qvf)
    out = tmp_path/'links.pdb'; export_pdb(qvf, out)
    st = gemmi.read_structure(str(out))
    found = sorted((c.type.name, c.partner1.res_id.seqid.num, c.partner1.atom_name,
                    c.partner2.res_id.seqid.num, c.partner2.atom_name)
                   for c in st.connections)
    assert len(found) == 2
    assert ('Disulf', 1, 'SG', 5, 'SG') in found
    assert any(f[0] in ('Covale', 'MetalC') and f[1:] == (5, 'SG', 101, 'ZN') for f in found)


def biomt(serial, rotation, shift):
    return ''.join(f"REMARK 350   BIOMT{n}{serial:4d}" + ''.join(f"{v:10.6f}" for v in row)
                   + f"{t:15.5f}\n" for n, (row, t) in enumerate(zip(rotation, shift), 1))


def remark350(ident, blocks):
    """REMARK 350 in the wwPDB layout; blocks are (chain lines, operators)."""
    text = (f"REMARK 350 BIOMOLECULE: {ident}\n"
            "REMARK 350 AUTHOR DETERMINED BIOLOGICAL UNIT: DIMERIC\n")
    for lines, operators in blocks:
        text += f"REMARK 350 APPLY THE FOLLOWING TO CHAINS: {lines[0]}\n"
        text += ''.join(f"REMARK 350                    AND CHAINS: {c}\n" for c in lines[1:])
        text += ''.join(biomt(*op) for op in operators)
    return text


IDENTITY = (1, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0])
TWOFOLD = (2, [[-1, 0, 0], [0, -1, 0], [0, 0, 1]], [10, 0, 0])


def dimer_atoms():
    # Chain A: CA, CB of ALA 1 (bonded); chain B: a zinc ion.
    return (atom(1, xyz=(1, 2, 3)) + atom(2, name=' CB ', xyz=(1.5, 2, 3))
            + atom(3, symbol='ZN', name='ZN  ', residue='ZN', chain='B', seq=101,
                   record='HETATM', xyz=(4, 0, -1)) + conect(1, 2) + conect(2, 1))


def section_of(path, sid):
    with Reader(path) as reader:
        raw = next(s for s in reader.raw_manifest['sections'] if s['id'] == sid)
        return raw, reader.json(sid, 'structure'), \
            reader.json(sid, 'bonds')['pairs'] if 'bonds' in raw['members'] else []


def test_remark_350_assemblies_become_structures(tmp_path):
    src = make_pdb(tmp_path, remark350(1, [(['A,', 'B'], [IDENTITY, TWOFOLD])])
                   + remark350(2, [(['A'], [IDENTITY]), (['B'], [(3, IDENTITY[1], [0, 0, 5])])])
                   + 'HELIX    1   1 ALA A    1  ALA A    1  1\n' + dimer_atoms())
    qvf = tmp_path/'assembly.qvf'
    report = import_pdb(src, qvf)
    assert run(qvf)['ok']
    assert report['sections'] == ['structure', 'assembly_1', 'assembly_2']
    assert 'REMARK' not in report['omitted_records']
    assert [(a['section'], a['atoms'], [c['chains'] for c in a['copies']])
            for a in report['assemblies']] == [
        ('assembly_1', 6, [['A', 'B'], ['A-2', 'B-2']]),
        ('assembly_2', 3, [['A'], ['B-3']])]
    assert report['assemblies'][0]['copies'][1]['matrix'] == [
        [-1, 0, 0, 10], [0, -1, 0, 0], [0, 0, 1, 0]]
    assert report['assemblies_not_built'] is None
    raw, geometry, bonds = section_of(qvf, 'assembly_1')
    assert raw['label'] == 'Biological assembly 1'
    assert raw['chains'] == ['A', 'B', 'A-2', 'B-2']
    assert [r['chain'] for r in raw['secondary_structure']] == ['A', 'A-2']
    assert [(a['chain_id'], a['position']) for a in geometry['atoms']] == [
        ('A', [1, 2, 3]), ('A', [1.5, 2, 3]), ('B', [4, 0, -1]),
        ('A-2', [9, -2, 3]), ('A-2', [8.5, -2, 3]), ('B-2', [6, 0, -1])]
    assert geometry['atoms'][3]['atom_name'] == 'CA' and geometry['pbc'] == [False] * 3
    assert bonds == [{'i': 0, 'j': 1}, {'i': 3, 'j': 4}]
    raw, geometry, bonds = section_of(qvf, 'assembly_2')
    assert raw['chains'] == ['A', 'B-3'] and bonds == [{'i': 0, 'j': 1}]
    assert geometry['atoms'][2]['position'] == [4, 0, 4]
    # The deposited structure is unchanged; a renamed chain cannot go to PDB.
    assert [a['chain_id'] for a in section_of(qvf, 'structure')[1]['atoms']] == ['A', 'A', 'B']
    export_pdb(qvf, tmp_path/'deposited.pdb', section='structure')
    with pytest.raises(ValueError, match='fixed columns'):
        export_pdb(qvf, tmp_path/'dimer.pdb', section='assembly_1')


def mtrix(serial, given, rotation=IDENTITY[1], shift=(0, 0, 0)):
    return ''.join(f"MTRIX{n}{serial:4d}" + ''.join(f"{v:10.6f}" for v in row)
                   + f"     {t:10.5f}    {given}\n"
                   for n, (row, t) in enumerate(zip(rotation, shift), 1))


def test_mtrix_given_counts_and_missing_copies_block_assemblies(tmp_path):
    body = remark350(1, [(['A'], [IDENTITY])]) + dimer_atoms()
    given = import_pdb(make_pdb(tmp_path, mtrix(1, '1') + mtrix(2, '1', TWOFOLD[1], TWOFOLD[2])
                                + body), tmp_path/'given.qvf')
    assert given['mtrix'] == {'operators': 2, 'given': 2, 'not_given': 0}
    assert [a['section'] for a in given['assemblies']] == ['assembly_1']
    missing = import_pdb(make_pdb(tmp_path, mtrix(1, '1') + mtrix(2, ' ', TWOFOLD[1], TWOFOLD[2])
                                  + body), tmp_path/'missing.qvf')
    assert missing['mtrix'] == {'operators': 2, 'given': 1, 'not_given': 1}
    assert missing['assemblies'] == [] and missing['sections'] == ['structure']
    assert 'not given' in missing['assemblies_not_built']
    assert 'MTRIX1' not in missing['omitted_records']


@pytest.mark.parametrize('records, message', [
    (remark350(1, [(['A', 'C'], [IDENTITY])]), 'chain C, which has no atoms'),
    (remark350(1, [(['A'], [(2, [[2, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0])])]),
     'not a proper rotation'),
    (remark350(1, [(['A'], [(2, [[-1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0])])]),
     'not a proper rotation'),
    (remark350(1, [(['A'], [IDENTITY])]).rsplit('REMARK', 1)[0], 'rows 1, 2 and 3'),
    (biomt(*IDENTITY), 'must follow a chain list'),
    ('REMARK 350 APPLY THE FOLLOWING TO CHAINS: A\n', 'before BIOMOLECULE'),
    ('REMARK 350 BIOMOLECULE: 1\nREMARK 350                    AND CHAINS: A\n',
     'continue a chain list'),
    (remark350(1, [(['A'], [IDENTITY])]) * 2, 'distinct decimal numbers'),
    (remark350(1, [(['A'], [IDENTITY, (5, IDENTITY[1], [0, 0, 0])])]), 'copies a chain twice'),
    (remark350(1, [(['A'], [])]), 'needs chains and BIOMT'),
    (mtrix(1, '1').splitlines(True)[0] + ''.join(mtrix(1, ' ').splitlines(True)[1:]),
     'disagree on iGiven'),
    (mtrix(1, 'X'), 'iGiven 1 or blank'),
])
def test_assembly_and_mtrix_refusals(tmp_path, records, message):
    with pytest.raises(ValueError, match=message):
        import_pdb(make_pdb(tmp_path, records + dimer_atoms()), tmp_path/'bad.qvf')


def test_assembly_matches_independent_gemmi(tmp_path):
    gemmi = pytest.importorskip('gemmi')
    rotation = [[0.5, -0.866025, 0], [0.866025, 0.5, 0], [0, 0, 1]]
    src = make_pdb(tmp_path, remark350(1, [(['A, B'], [IDENTITY, (2, rotation, [3, -4, 7.5])])])
                   + dimer_atoms())
    qvf = tmp_path/'assembly.qvf'; import_pdb(src, qvf)
    ours = sorted((a['chain_id'], *a['position']) for a in section_of(qvf, 'assembly_1')[1]['atoms'])
    st = gemmi.read_structure(str(src))
    built = gemmi.make_assembly(st.assemblies[0], st[0], gemmi.HowToNameCopiedChain.AddNumber)
    theirs = sorted((ch.name, a.pos.x, a.pos.y, a.pos.z) for ch in built
                    for r in ch for a in r)
    assert len(ours) == len(theirs) == 6
    for o, t in zip(ours, theirs):
        assert o[1:] == pytest.approx(t[1:], abs=1e-6)


def cryst1(a, b, c, alpha, beta, gamma, group='P 21 21 21', z=4):
    return (f"CRYST1{a:9.3f}{b:9.3f}{c:9.3f}{alpha:7.2f}{beta:7.2f}{gamma:7.2f} "
            f"{group:<11s}{'' if z is None else f'{z:4d}'}\n")


def scale(n, row, shift=0.0):
    return f"SCALE{n}    " + ''.join(f"{v:10.6f}" for v in row) + f"     {shift:10.5f}\n"


def reference_cell(a, b, c, alpha, beta, gamma):
    """Independent textbook form: rows from the metric tensor (Cholesky)."""
    import math
    ca, cb, cg = (math.cos(math.radians(x)) for x in (alpha, beta, gamma))
    g = [[a * a, a * b * cg, a * c * cb], [a * b * cg, b * b, b * c * ca],
         [a * c * cb, b * c * ca, c * c]]
    l00 = math.sqrt(g[0][0]); l10 = g[1][0] / l00; l20 = g[2][0] / l00
    l11 = math.sqrt(g[1][1] - l10 ** 2); l21 = (g[2][1] - l20 * l10) / l11
    l22 = math.sqrt(g[2][2] - l20 ** 2 - l21 ** 2)
    return [[l00, 0, 0], [l10, l11, 0], [l20, l21, l22]]


def test_cryst1_cell_space_group_and_scale(tmp_path):
    params = (52.1, 61.7, 73.25, 80.5, 95.25, 101.0)
    from qvf.convert import _pdb_cell_vectors, _pdb_scale
    lattice = _pdb_cell_vectors(*params)
    rows = _pdb_scale(lattice)
    src = make_pdb(tmp_path, cryst1(*params, group='P 1 21 1', z=2)
                   + ''.join(scale(n, row) for n, row in enumerate(rows, 1)) + atom())
    qvf = tmp_path/'crystal.qvf'
    report = import_pdb(src, qvf)
    assert report['cell'] == {'space_group': 'P 1 21 1', 'z': 2,
                              'symmetry_sections': ['symmetry'], 'expanded': False,
                              'note': report['cell']['note']}
    assert run(qvf)['ok']
    with Reader(qvf) as reader:
        geometry = reader.json('structure', 'structure')
        sym = reader.raw_manifest['sections'][1]
        assert sym['kind'] == 'structure.symmetry' and sym['structure_ref'] == 'structure'
        assert reader.json('symmetry', 'data') == {'space_group_symbol': 'P 1 21 1'}
    assert geometry['pbc'] == [True] * 3
    for got, want in zip(geometry['lattice_vectors'], reference_cell(*params)):
        assert got == pytest.approx(want, abs=1e-9)
    out = tmp_path/'crystal.pdb'
    exported = export_pdb(qvf, out)
    assert exported['space_group'] == 'P 1 21 1'
    assert exported['max_cell_rounding_error_angstrom'] < 1e-9
    assert exported['omitted_sections'] == ['symmetry']
    text = out.read_text().splitlines()
    assert text[1].startswith('CRYST1   52.100   61.700   73.250  80.50  95.25 101.00 P 1 21 1')
    assert [r[:6] for r in text[2:5]] == ['SCALE1', 'SCALE2', 'SCALE3']
    again = tmp_path/'again.qvf'; import_pdb(out, again)
    with Reader(again) as reader:
        assert reader.json('structure', 'structure') == geometry


def test_placeholder_cell_means_no_cell(tmp_path):
    src = make_pdb(tmp_path, cryst1(1, 1, 1, 90, 90, 90, 'P 1', 1)
                   + scale(1, (1, 0, 0)) + scale(2, (0, 1, 0)) + scale(3, (0, 0, 1)) + atom())
    qvf = tmp_path/'nmr.qvf'
    report = import_pdb(src, qvf)
    assert report['placeholder_cell'] is True and report['cell'] is None
    geometry = structure(qvf)
    assert geometry['pbc'] == [False] * 3 and geometry['lattice_vectors'] is None


def test_cell_applies_to_ensembles(tmp_path):
    cell = cryst1(30, 30, 30, 90, 90, 90, 'P 1', 1)
    shared = make_pdb(tmp_path, cell + models(atom(), atom(xyz=(2, 2, 2))))
    traj = tmp_path/'traj.qvf'
    assert import_pdb(shared, traj)['cell']['symmetry_sections'] == ['symmetry']
    with Reader(traj) as reader:
        assert reader.json('trajectory', 'metadata')['pbc'] == [True] * 3
        assert reader.tensor('trajectory', 'lattice').shape == (2, 3, 3)
    assert run(traj)['ok']
    differing = make_pdb(tmp_path, cell + models(atom(), atom(b_factor=' 20.00')))
    per_model = tmp_path/'models.qvf'
    report = import_pdb(differing, per_model)
    assert report['cell']['symmetry_sections'] == ['symmetry_model_1', 'symmetry_model_2']
    assert run(per_model)['ok']


@pytest.mark.parametrize('change,reason', [
    ({'cell': [[10, 0, 0], [0, 10, 0], [0, 0, 10]], 'pbc': [True, True, False]},
     'all three axes'),
    ({'cell': [[0, 10, 0], [-10, 0, 0], [0, 0, 10]], 'pbc': [True] * 3}, 'PDB orientation'),
    ({'cell': [[10, 0, 0], [0, 10, 0], [0, 0, -10]], 'pbc': [True] * 3}, 'PDB orientation'),
    ({'cell': [[1e6, 0, 0], [0, 10, 0], [0, 0, 10]], 'pbc': [True] * 3}, 'overflows'),
])
def test_cell_export_refusals_are_atomic(tmp_path, change, reason):
    path = tmp_path/'cell.qvf'
    with Writer(path, 'qvf-test', '1') as writer:
        writer.add_section({'id': 'structure', 'kind': 'structure'})
        writer.add_json('structure', 'structure', {'atoms': [
            {'symbol': 'C', 'atomic_number': 6, 'position': [0, 0, 0], **CA}],
            'pbc': change['pbc'], 'lattice_vectors': change['cell']})
    with pytest.raises(ValueError, match=reason):
        export_pdb(path, tmp_path/'output.pdb')
    assert [p.name for p in tmp_path.iterdir()] == ['cell.qvf']


def test_independent_gemmi_reads_cell(tmp_path):
    gemmi = pytest.importorskip('gemmi')
    src = make_pdb(tmp_path, cryst1(52.1, 61.7, 73.25, 80.5, 95.25, 101.0, 'P 21 21 21', 4)
                   + atom(xyz=(10, 20, 30)))
    qvf = tmp_path/'crystal.qvf'; import_pdb(src, qvf)
    out = tmp_path/'crystal.pdb'; export_pdb(qvf, out)
    st = gemmi.read_structure(str(out))
    cell = st.cell
    assert (cell.a, cell.b, cell.c) == pytest.approx((52.1, 61.7, 73.25))
    assert (cell.alpha, cell.beta, cell.gamma) == pytest.approx((80.5, 95.25, 101.0))
    assert st.spacegroup_hm == 'P 21 21 21'
    # gemmi's own orthogonalization agrees with the archive's lattice.
    with Reader(qvf) as reader:
        lattice = reader.json('structure', 'structure')['lattice_vectors']
    frac = cell.fractionalize(gemmi.Position(10, 20, 30))
    back = [sum(f * lattice[k][i] for k, f in enumerate((frac.x, frac.y, frac.z)))
            for i in range(3)]
    assert back == pytest.approx([10, 20, 30], abs=1e-6)

@pytest.mark.parametrize('text,reason', [
    ('', 'no atoms'),
    ('MODEL        1\n' + atom() + 'ENDMDL\nMODEL        1\n' + atom() + 'ENDMDL\n',
     'serials must be unique'),
    ('NUMMDL       2\n' + atom(), 'NUMMDL disagrees'),
    ('NUMMDL       1\nNUMMDL       1\n' + atom(), 'one NUMMDL'),
    ('MODEL        1\n' + atom() + 'MODEL        2\n', 'missing ENDMDL'),
    (atom(seq=0).replace('   0    ', '  A0    ', 1), 'hybrid-36'),
    (atom(occupancy='  1.50'), 'occupancy must lie'),
    (atom(occupancy='  half'), 'fixed-point decimal'),
    (atom(b_factor='  x.yz'), 'fixed-point decimal'),
    (cryst1(10, 10, 10, 90, 90, 90) * 2 + atom(), 'one CRYST1'),
    (cryst1(10, 10, 10, 90, 90, 200) + atom(), 'angles in'),
    (cryst1(10, 10, 10, 60, 60, 170) + atom(), 'do not describe a cell'),
    (cryst1(10, 10, 10, 90, 90, 90, group='') + atom(), 'space group'),
    (scale(1, (0.1, 0, 0)) + atom(), 'require a CRYST1'),
    (cryst1(10, 10, 10, 90, 90, 90) + scale(1, (0.1, 0, 0)) + atom(), 'exactly SCALE1'),
    (cryst1(10, 10, 10, 90, 90, 90) + scale(1, (0.1, 0, 0)) + scale(2, (0, 0.1, 0))
     + scale(3, (0, 0, 0.05)) + atom(), 'another frame'),
    (cryst1(10, 10, 10, 90, 90, 90) + scale(1, (0.1, 0, 0), 0.5) + scale(2, (0, 0.1, 0))
     + scale(3, (0, 0, 0.1)) + atom(), 'another frame'),
    (atom() + atom(2) + conect(1, 3), 'serial 3, which is not an atom of the file'),
    (atom() + conect(1, 1), 'to itself'),
    (atom() + 'CONECT    1\n', 'names no bonded atom'),
    (atom() + atom(2) + conect(1, 0), 'positive decimal'),
    (models(atom() + atom(2), atom()).replace('END\n', '') + conect(1, 2),
     'not an atom of MODEL 2'),
    (helix(1, 1, 2, cls='11') + atom(), 'helix class must lie'),
    (helix(1, 1, 2).replace('ALA A    2', 'ALA B    2') + atom(), 'one chain'),
    (sheet(0, 'S1', 1, 1, 2) + atom(), 'SHEET strand'),
    (helix(1, 1, 2).replace('ALA A    1 ', 'ALA A   1A ', 1) + atom(), 'decimal residue number'),
    ('MODEL     10000\n' + atom() + 'ENDMDL\n', 'columns 11-14'),
    ('NUMMDL    10000\n' + atom(), 'columns 11-14'),
    ('MODEL        1\n' + atom(), 'missing ENDMDL'),
    ('ENDMDL\n' + atom(), 'nonempty MODEL'),
    ('MODEL        1\nENDMDL\n', 'nonempty MODEL'),
    ('MODEL        1\n' + atom() + 'ENDMDL\n' + atom(2), 'outside MODEL'),
    (atom() + 'MODEL        1\n' + atom(2) + 'ENDMDL\n', 'inside MODEL/ENDMDL'),
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
    ({'cell': [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}, 'all three axes or no cell'),
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


def test_independent_gemmi_reads_atom_site_identity(tmp_path):
    gemmi = pytest.importorskip('gemmi')
    src = make_pdb(tmp_path, atom(1, name=' OG ', symbol='O', residue='SER', seq=10, alt='A',
                                  occupancy='  0.60')
                   + atom(2, name=' OG ', symbol='O', residue='SER', seq=10, alt='B',
                          occupancy='  0.40')
                   + atom(3, name=' N  ', symbol='N', residue='GLY', seq=10, code='A')
                   + atom(4, name='ZN  ', symbol='ZN', residue=' ZN', chain='B', seq=1,
                          record='HETATM'))
    qvf = tmp_path/'site.qvf'; import_pdb(src, qvf)
    out = tmp_path/'site.pdb'; export_pdb(qvf, out)
    model = gemmi.read_structure(str(out))[0]
    residues = [(c.name, r.name, r.seqid.num, r.seqid.icode, r.het_flag)
                for c in model for r in c]
    assert residues == [('A', 'SER', 10, ' ', 'A'), ('A', 'GLY', 10, 'A', 'A'),
                        ('B', 'ZN', 1, ' ', 'H')]
    og = list(model['A'][0])
    assert [(a.name, a.altloc, a.occ) for a in og] == [
        ('OG', 'A', pytest.approx(.6)), ('OG', 'B', pytest.approx(.4))]
    assert model['B'][0][0].element.name == 'Zn'


def test_independent_gemmi_reads_helix_and_sheet(tmp_path):
    gemmi = pytest.importorskip('gemmi')
    src = make_pdb(tmp_path, helix(1, 10, 11, start_code='A', cls=' 5')
                   + sheet(1, 'S1', 1, 12, 13)
                   + trace((10, ' '), (10, 'A'), (11, ' '), (12, ' '), (13, ' ')))
    qvf = tmp_path/'ranges.qvf'; import_pdb(src, qvf)
    out = tmp_path/'ranges.pdb'; export_pdb(qvf, out)
    st = gemmi.read_structure(str(out))
    (h,) = st.helices
    assert (h.start.chain_name, h.start.res_id.seqid.num, h.start.res_id.seqid.icode,
            h.end.res_id.seqid.num) == ('A', 10, 'A', 11)
    assert h.pdb_helix_class == gemmi.Helix.HelixClass.R310    # class 5: 3-10
    (s,) = st.sheets
    assert s.name == 'S1' and len(s.strands) == 1
    assert (s.strands[0].start.res_id.seqid.num, s.strands[0].end.res_id.seqid.num) == (12, 13)


def expanded(tmp_path, body, group, cell=(20, 30, 40, 90, 90, 90), **kw):
    src = make_pdb(tmp_path, cryst1(*cell, group=group, z=None) + body)
    qvf = tmp_path/'cell.qvf'
    report = import_pdb(src, qvf, expand_symmetry=True, **kw)
    assert run(qvf)['ok']
    return report, qvf


def test_symmetry_expansion_writes_the_unit_cell(tmp_path):
    body = ('HELIX    1   1 ALA A    1  ALA A    1  1\n'
            + atom(1, xyz=(2, 3, 4)) + atom(2, name=' CB ', xyz=(3.5, 3, 4))
            + conect(1, 2) + conect(2, 1))
    report, qvf = expanded(tmp_path, body, 'P 21 21 21')
    assert report['sections'] == ['structure', 'unit_cell']
    assert report['cell']['expanded'] is True
    summary = report['symmetry_expansion']
    assert summary == {'space_group': 'P 21 21 21', 'hall_symbol': 'P 2ac 2ab',
                       'operators': 4, 'atoms': 8, 'special_position_atoms_merged': 0,
                       'bonds_dropped': 0, 'section': 'unit_cell',
                       'source_section': 'structure'}
    raw, geometry, bonds = section_of(qvf, 'unit_cell')
    deposited = section_of(qvf, 'structure')[1]
    assert raw['label'] == 'Unit cell (P 21 21 21 expanded)'
    assert raw['chains'] == ['A', 'A-2', 'A-3', 'A-4']
    assert [r['chain'] for r in raw['secondary_structure']] == ['A', 'A-2', 'A-3', 'A-4']
    assert geometry['pbc'] == [True] * 3
    assert geometry['lattice_vectors'] == deposited['lattice_vectors']
    assert geometry['atoms'][:2] == deposited['atoms']
    assert bonds == [{'i': 2 * k, 'j': 2 * k + 1} for k in range(4)]
    for k in range(4):
        a, b = geometry['atoms'][2 * k:2 * k + 2]
        assert a['atom_name'] == 'CA' and a['residue_seq'] == 1
        # Each copy's centre lies inside the cell; molecules stay intact.
        centre = [(p + q) / 2 / L for p, q, L in zip(a['position'], b['position'], (20, 30, 40))]
        assert all(0 <= c < 1 for c in centre)
        assert abs(sum((p - q) ** 2 for p, q in zip(a['position'], b['position'])) - 2.25) < 1e-9
    with Reader(qvf) as reader:
        sym = next(s for s in reader.raw_manifest['sections'] if s['id'] == 'symmetry_unit_cell')
        assert sym['structure_ref'] == 'unit_cell'
        assert reader.json('symmetry_unit_cell', 'data') == {'space_group_symbol': 'P 1'}


def test_symmetry_expansion_merges_special_positions(tmp_path):
    # A zinc on the two-fold axis along c of P 2 2 2 and a general atom bonded
    # to it: four zinc images, two distinct.
    body = (atom(1, symbol='ZN', name='ZN  ', residue='ZN', seq=101, record='HETATM',
                 xyz=(0, 0, 12)) + atom(2, symbol='S', name=' SG ', residue='CYS', xyz=(1.5, 1, 12))
            + conect(1, 2) + conect(2, 1))
    report, qvf = expanded(tmp_path, body, 'P 2 2 2')
    summary = report['symmetry_expansion']
    assert summary['operators'] == 4 and summary['special_position_atoms_merged'] == 2
    _, geometry, bonds = section_of(qvf, 'unit_cell')
    assert summary['atoms'] == len(geometry['atoms']) == 6
    assert sum(a['symbol'] == 'Zn' for a in geometry['atoms']) == 2
    assert len(bonds) + summary['bonds_dropped'] == 4 and bonds
    for pair in bonds:
        p, q = (geometry['atoms'][pair[k]]['position'] for k in 'ij')
        assert abs(sum((x - y) ** 2 for x, y in zip(p, q)) - 3.25) < 1e-9


def test_symmetry_expansion_matches_gemmi(tmp_path):
    gemmi = pytest.importorskip('gemmi')
    body = atom(1, xyz=(2, 3, 4)) + atom(2, name=' CB ', xyz=(-7.25, 13.5, 21))
    cell = (61.2, 61.2, 97.4, 90, 90, 120)
    report, qvf = expanded(tmp_path, body, 'P 61 2 2', cell=cell)
    assert report['symmetry_expansion']['operators'] == 12
    ours = sorted(tuple(round(v % 1, 5) % 1 for v in gemmi.UnitCell(*cell).fractionalize(
        gemmi.Position(*a['position'])).tolist()) for a in section_of(qvf, 'unit_cell')[1]['atoms'])
    uc = gemmi.UnitCell(*cell)
    theirs = sorted(tuple(round(v % 1, 5) % 1 for v in op.apply_to_xyz(
        uc.fractionalize(gemmi.Position(*xyz)).tolist()))
        for op in gemmi.find_spacegroup_by_name('P 61 2 2').operations()
        for xyz in ((2, 3, 4), (-7.25, 13.5, 21)))
    assert len(ours) == len(theirs) == 24
    for o, t in zip(ours, theirs):
        assert o == pytest.approx(t, abs=2e-5)


def test_hall_operators_match_gemmi_for_every_supported_group():
    gemmi = pytest.importorskip('gemmi')
    from fractions import Fraction
    from qvf._spacegroups import PDB_HALL, operators
    for name, hall in PDB_HALL.items():
        ours = operators(hall)
        assert ours[0] == (((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0, 0, 0))
        theirs = {(tuple(tuple(v // op.DEN for v in row) for row in op.rot),
                   tuple(Fraction(v, op.DEN) % 1 for v in op.tran))
                  for op in gemmi.find_spacegroup_by_name(
                      {'H 3': 'R 3:H', 'R 3': 'R 3:R', 'H 3 2': 'R 3 2:H',
                       'R 3 2': 'R 3 2:R'}.get(name, name)).operations()}
        assert len(set(ours)) == len(ours) and set(ours) == theirs, name


@pytest.mark.parametrize('body, message', [
    (cryst1(20, 30, 40, 90, 90, 90, group='P 1 21/c 1', z=None) + atom(), 'does not support'),
    (atom(), 'requires a CRYST1 cell'),
    (cryst1(1, 1, 1, 90, 90, 90, group='P 1', z=1) + atom(), 'requires a CRYST1 cell'),
    (cryst1(20, 30, 40, 90, 90, 90, group='P 1', z=None) + mtrix(1, '1')
     + mtrix(2, ' ', TWOFOLD[1], TWOFOLD[2]) + atom(), 'every MTRIX copy'),
])
def test_symmetry_expansion_refusals(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        import_pdb(make_pdb(tmp_path, body), tmp_path/'bad.qvf', expand_symmetry=True)


def test_cli_expand_symmetry(tmp_path, capsys):
    from qvf.cli import main
    src = make_pdb(tmp_path, cryst1(20, 30, 40, 90, 90, 90, group='P 1 21 1', z=None) + atom())
    qvf = tmp_path/'cell.qvf'
    assert main(['convert', str(src), '-o', str(qvf), '--from', 'pdb', '--to', 'qvf',
                 '--expand-symmetry']) == 0
    assert len(section_of(qvf, 'unit_cell')[1]['atoms']) == 2
    assert main(['convert', str(src), '-o', str(tmp_path/'x.qvf'), '--from', 'xyz', '--to',
                 'qvf', '--expand-symmetry']) == 2
    assert '--expand-symmetry and --expand-ncs apply only to PDB import' in capsys.readouterr().err


def test_expand_ncs_generates_missing_mtrix_copies(tmp_path):
    body = (cryst1(40, 50, 60, 90, 90, 90, group='P 21 21 21', z=None) + mtrix(1, '1')
            + mtrix(2, ' ', TWOFOLD[1], TWOFOLD[2])
            + 'HELIX    1   1 ALA A    1  ALA A    1  1\n'
            + remark350(1, [(['A', 'B'], [IDENTITY])]) + dimer_atoms())
    src = make_pdb(tmp_path, body)
    plain = import_pdb(src, tmp_path/'plain.qvf')
    assert plain['ncs_expansion'] is None and plain['assemblies'] == []
    qvf = tmp_path/'ncs.qvf'
    report = import_pdb(src, qvf, expand_ncs=True, expand_symmetry=True)
    assert run(qvf)['ok']
    assert report['ncs_expansion']['atoms'] == 6
    assert [c['operator'] for c in report['ncs_expansion']['copies']] == [2]
    assert report['sections'] == ['structure', 'asymmetric_unit', 'assembly_1', 'unit_cell']
    assert report['cell']['symmetry_sections'] == ['symmetry', 'symmetry_asymmetric_unit']
    assert report['assemblies_not_built'] is None
    assert report['assemblies'][0]['source_section'] == 'asymmetric_unit'
    assert report['symmetry_expansion']['source_section'] == 'asymmetric_unit'
    assert report['symmetry_expansion']['atoms'] == 24
    raw, geometry, bonds = section_of(qvf, 'asymmetric_unit')
    assert raw['chains'] == ['A', 'B', 'A-2', 'B-2']
    assert [r['chain'] for r in raw['secondary_structure']] == ['A', 'A-2']
    assert [a['position'] for a in geometry['atoms'][3:]] == [[9, -2, 3], [8.5, -2, 3],
                                                             [6, 0, -1]]
    assert bonds == [{'i': 0, 'j': 1}, {'i': 3, 'j': 4}]
    assert len(section_of(qvf, 'structure')[1]['atoms']) == 3


def test_expand_ncs_matches_gemmi(tmp_path):
    gemmi = pytest.importorskip('gemmi')
    rotation = [[0.5, -0.866025, 0], [0.866025, 0.5, 0], [0, 0, 1]]
    src = make_pdb(tmp_path, mtrix(1, '1') + mtrix(2, ' ', rotation, (3, -4, 7.5))
                   + mtrix(3, ' ', TWOFOLD[1], TWOFOLD[2]) + dimer_atoms())
    qvf = tmp_path/'ncs.qvf'
    import_pdb(src, qvf, expand_ncs=True)
    ours = sorted(tuple(a['position']) for a in section_of(qvf, 'asymmetric_unit')[1]['atoms'])
    st = gemmi.read_structure(str(src))
    st.expand_ncs(gemmi.HowToNameCopiedChain.AddNumber)
    theirs = sorted((a.pos.x, a.pos.y, a.pos.z) for ch in st[0] for r in ch for a in r)
    assert len(ours) == len(theirs) == 9
    for o, t in zip(ours, theirs):
        assert o == pytest.approx(t, abs=1e-5)
