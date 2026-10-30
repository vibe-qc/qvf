"""Molden ordering, normalization, strict refusal and independent orbital values."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qvf import Reader, Writer
from qvf.convert import import_molden, export_molden
from qvf._legacy_writer import BOHR_PER_ANGSTROM, primitive_norm
from qvf.validate import run


SIMPLE = ("[Molden Format]\n[Atoms] AU\nHe 1 2 0 0 0\n[GTO]\n1 0\n"
          "s 1 1.00\n1.2 1.0\n[MO]\nSym= A\nEne= -0.5\nSpin= Alpha\nOccup= 2\n1 1.0\n")


def source(tmp_path, text=SIMPLE):
    path = tmp_path / 'input.molden'; path.write_text(text)
    return path


def clean(path):
    report = run(path)
    assert report['ok'] and not report['findings'], report


def test_units_spin_labels_and_omission_reports(tmp_path):
    text = SIMPLE.replace('[Atoms]', '# comment\n[Title]\nsynthetic test\n[Atoms]')
    text = text.replace('He 1 2 0 0 0', 'He 1 2 1.0D+00 0 0').replace('Occup= 2', 'Occup= 1')
    path = tmp_path / 'import.qvf'
    report = import_molden(source(tmp_path, text), path, spin='restricted_open')
    clean(path)
    assert report['omitted_comments'] == 1 and report['omitted_text_lines'] == 1
    with Reader(path) as reader:
        assert reader.json('structure', 'structure')['atoms'][0]['position'][0] == pytest.approx(1 / BOHR_PER_ANGSTROM)
        metadata = reader.json('wavefunction', 'mo_metadata')
        assert metadata == dict(spin='restricted_open', orbital_kind='custom', n_ao=1,
                                n_mo=1, energies=[-.5], occupations=[1], symmetry_labels=['A'])
        assert 'n_electrons' not in reader.json('wavefunction', 'basis')
        assert reader.tensor('wavefunction', 'mo_coefficients').tolist() == [[1.0]]
    exported = tmp_path / 'export.molden'; report = export_molden(path, exported)
    assert report['spin'] == 'restricted_open' and report['omitted_sections'] == []
    assert report['omitted_members'] == [] and report['generated_symmetry_labels'] == 0
    clean_again = tmp_path / 'again.qvf'; import_molden(exported, clean_again, spin=report['spin']); clean(clean_again)


@pytest.mark.parametrize('pure,expected', [
    (False, [1, 4*math.sqrt(3), 5*math.sqrt(3), 2, 6*math.sqrt(3), 3]),
    (True, [5, 3, 1, 2, 4]),
])
def test_explicit_d_components_and_scales(tmp_path, pure, expected):
    size = 5 if pure else 6
    text = SIMPLE.replace('s 1 1.00', 'd 1 1.00').replace('[MO]', ('[5D]' if pure else '[6D]') + '\n[MO]')
    text = text.replace('1 1.0\n', ''.join(f'{i} {i}\n' for i in range(1, size + 1)))
    path = tmp_path / 'd.qvf'; import_molden(source(tmp_path, text), path, spin='restricted'); clean(path)
    with Reader(path) as reader:
        assert reader.tensor('wavefunction', 'mo_coefficients').tolist()[0] == pytest.approx(expected)
        assert reader.json('wavefunction', 'basis')['shells'][0]['pure'] is pure
    output = tmp_path / 'd.molden'; export_molden(path, output)
    for i in range(1, size + 1):
        assert f'\n{i} {i}\n' in output.read_text()


def test_sp_split_and_gto_atom_order(tmp_path):
    text = ('[Molden Format]\n[Atoms] Angs\nHe 1 2 0 0 0\nHe 2 2 1 0 0\n'
            '[GTO]\n2 0\nsp 1 1\n1.3 1 -1\n1 0\ns 1\n.7 1\n'
            '[MO]\nSym= A\nEne= -.4\nSpin= Alpha\nOccup= 2\n'
            '5 5\n3 3\n1 1\n4 4\n2 2\n')
    path = tmp_path / 'sp.qvf'; import_molden(source(tmp_path, text), path, spin='restricted')
    with Reader(path) as reader:
        shells = reader.json('wavefunction', 'basis')['shells']
        assert [(s['center'], s['l']) for s in shells] == [(1, 0), (1, 1), (0, 0)]
        assert shells[1]['coefficients'] == [-1]
        assert reader.tensor('wavefunction', 'mo_coefficients').tolist() == [[1, 2, 3, 4, 5]]
    output = tmp_path / 'sp.molden'; export_molden(path, output)
    assert output.read_text().index('\n2 0\n') < output.read_text().index('\n1 0\n')


def test_unrestricted_channels_keep_distinct_row_counts(tmp_path):
    text = SIMPLE.replace('Occup= 2', 'Occup= 1')
    text += 'Sym= B\nEne= -.3\nSpin= Beta\nOccup= .5\n1 -.7\n'
    text += 'Sym= B2\nEne= .3\nSpin= Beta\nOccup= 0\n1 .4\n'
    path = tmp_path / 'uhf.qvf'; import_molden(source(tmp_path, text), path, spin='unrestricted'); clean(path)
    with Reader(path) as reader:
        metadata = reader.json('wavefunction', 'mo_metadata')
        assert 'energies' not in metadata
        assert metadata['alpha']['occupations'] == [1]
        assert metadata['beta']['occupations'] == [.5, 0]
        assert reader.tensor('wavefunction', 'mo_coefficients_beta').tolist() == [[-.7], [.4]]
    output = tmp_path / 'uhf.molden'; report = export_molden(path, output)
    assert report['spin'] == 'unrestricted'
    again = tmp_path / 'again.qvf'; import_molden(output, again, spin='unrestricted'); clean(again)


@pytest.mark.parametrize('text', [
    '', SIMPLE.replace('[Molden Format]', '[Atoms] AU'), SIMPLE + '[GTO]\n',
    SIMPLE.replace('[Atoms] AU', '[Atoms]'), SIMPLE.replace('[Atoms] AU', '[Atoms] NM'),
    SIMPLE.replace('He 1 2', 'He 2 2'), SIMPLE.replace('He 1 2', 'He 1 1'),
    SIMPLE.replace('He 1 2', 'X 1 0'), SIMPLE.replace('He 1 2 0 0 0', 'He 1 2 nan 0 0'),
    SIMPLE + '[core]\n1: 2\n', SIMPLE + '[STO]\n', SIMPLE + '[SCFCONV]\n',
    SIMPLE.replace('s 1 1.00', 'f 1 1.00'), SIMPLE.replace('s 1 1.00', 's 1 .5'),
    SIMPLE.replace('s 1 1.00', 's 513 1.00'), SIMPLE.replace('1.2 1.0', '1.2 .4'),
    SIMPLE.replace('1.2 1.0', '-1.2 1.0'), SIMPLE.replace('1.2 1.0', '1.2 0'),
    SIMPLE.replace('1.2 1.0', '1.2 inf'), SIMPLE.replace('1.2 1.0', '1.2 1.0 1.0'),
    SIMPLE.replace('1 0\ns', '2 0\ns'), SIMPLE.replace('1 0\ns', '1 2\ns'),
    SIMPLE.replace('[MO]', '[5D]\n[6D]\n[MO]'), SIMPLE.replace('[MO]', '[5D]\npayload\n[MO]'),
    SIMPLE.replace('1 1.0\n', ''), SIMPLE + '1 1.0\n', SIMPLE.replace('1 1.0\n', '2 1.0\n'),
    SIMPLE.replace('Ene= -0.5', 'Ene= nan'), SIMPLE.replace('Spin= Alpha', 'Spin= Gamma'),
    SIMPLE.replace('Spin= Alpha', 'Spin= Beta'), SIMPLE.replace('Occup= 2', 'Occup= 3'),
    SIMPLE.replace('Sym= A\n', ''), SIMPLE.replace('Ene= -0.5', 'Unknown= -0.5'),
    SIMPLE.replace('Spin= Alpha', 'Spin= Alpha\nSpin= Alpha'), SIMPLE + 'Ene= .3\n',
])
def test_refusal_is_atomic(tmp_path, text):
    src = source(tmp_path, text)
    with pytest.raises((ValueError, OverflowError)):
        import_molden(src, tmp_path / 'invalid.qvf', spin='restricted')
    assert [p.name for p in tmp_path.iterdir()] == ['input.molden']


@pytest.mark.parametrize('spin', [None, 'generalized', 'unrestricted'])
def test_spin_must_be_explicit_and_consistent(tmp_path, spin):
    with pytest.raises(ValueError):
        import_molden(source(tmp_path), tmp_path / 'invalid.qvf', spin=spin)


def qvf_wavefunction(tmp_path, shells, metadata=None, geometry=None, extra=False):
    """A synthetic QVF wavefunction independent of the Molden importer."""
    from qvf.convert import _binary
    nao = sum(2*s['l']+1 if s.get('pure', True) else (s['l']+1)*(s['l']+2)//2 for s in shells)
    metadata = metadata or dict(spin='restricted', energies=[-.5], occupations=[2])
    path = tmp_path / 'source.qvf'
    with Writer(path, 'synthetic', '1') as writer:
        writer.add_section({'id':'structure','kind':'structure'})
        writer.add_json('structure','structure', geometry or {'atoms':[{'symbol':'He','atomic_number':2,'position':[0,0,0]}], 'pbc':[False]*3})
        writer.add_section({'id':'wf','kind':'wavefunction.gto','structure_ref':'structure'})
        writer.add_json('wf','basis',{'structure_ref':'structure','shells':shells,'n_ao':nao})
        writer.add_json('wf','mo_metadata',metadata)
        _binary(writer,'wf','mo_coefficients',range(1,nao+1),[1,nao])
        if extra:
            _binary(writer,'wf','density_matrix',[0]*(nao*nao),[nao,nao])
            writer.add_section({'id':'extra','kind':'x_demo.data'})
            writer.add_json('extra','data',{'synthetic':True})
    return path


def test_export_normalizes_basis_preserving_orbitals_and_reports(tmp_path):
    shells = [dict(center=0,l=1,pure=True,exponents=[1.2],coefficients=[.7])]
    path = qvf_wavefunction(tmp_path, shells, extra=True); clean(path)
    output = tmp_path / 'p.molden'; report = export_molden(path, output)
    assert report['contraction_norms'] == [.7]
    assert report['omitted_members'] == ['density_matrix'] and report['omitted_sections'] == ['extra']
    assert report['generated_symmetry_labels'] == 1
    again = tmp_path / 'again.qvf'; import_molden(output, again, spin='restricted'); clean(again)
    with Reader(again) as reader:
        # QVF spherical p is y,z,x. Molden and Cartesian p are x,y,z.
        assert reader.tensor('wavefunction','mo_coefficients').tolist()[0] == pytest.approx([2.1,.7,1.4])
        assert reader.json('wavefunction','basis')['shells'][0]['coefficients'] == [1]


@pytest.mark.parametrize('shells', [
    [dict(center=0,l=5,pure=True,exponents=[1],coefficients=[1])],
    [dict(center=0,l=3,pure=p,exponents=[1],coefficients=[1]) for p in [True,False]],
    [dict(center=0,l=2,pure=p,exponents=[1],coefficients=[1]) for p in [True,False]],
    [dict(center=0,l=0,pure=True,exponents=[1],coefficients=[0])],
])
def test_export_refuses_unsupported_basis(tmp_path, shells):
    path = qvf_wavefunction(tmp_path, shells)
    with pytest.raises(ValueError):
        export_molden(path, tmp_path / 'invalid.molden')
    assert not (tmp_path / 'invalid.molden').exists()


@pytest.mark.parametrize('separator', ['\n', '\r', '\x85', '\u2028', '\u2029'])
def test_export_refuses_multiline_symmetry_labels(tmp_path, separator):
    shells = [dict(center=0, l=0, pure=True, exponents=[1], coefficients=[1])]
    metadata = dict(spin='restricted', energies=[-.5], occupations=[2],
                    symmetry_labels=['A' + separator + 'B'])
    path = qvf_wavefunction(tmp_path, shells, metadata=metadata)
    clean(path)
    with pytest.raises(ValueError, match='single-line'):
        export_molden(path, tmp_path / 'invalid.molden')
    assert not (tmp_path / 'invalid.molden').exists()


def test_cli_no_overwrite_and_no_optional_dependencies(tmp_path, capsys):
    from qvf.cli import main
    src = source(tmp_path); path = tmp_path / 'cli.qvf'
    command = ['convert',str(src),'--from','molden','--to','qvf','-o',str(path)]
    assert main(command) == 2
    assert not path.exists()
    assert main(command + ['--spin','restricted']) == 0
    assert json.loads(capsys.readouterr().out)['n_ao'] == 1
    with pytest.raises(FileExistsError):
        import_molden(src,path,spin='restricted')
    output = tmp_path / 'cli.molden'
    assert main(['convert',str(path),'--from','qvf','--to','molden','-o',str(output)]) == 0
    with pytest.raises(FileExistsError):
        export_molden(path,output)
    result = subprocess.run([sys.executable,'-S','-m','qvf','convert',str(src),'--from','molden','--to','qvf',
                             '--spin','restricted','-o',str(tmp_path/'stdlib.qvf')],
                            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1])),
                            text=True,capture_output=True)
    assert result.returncode == 0, result.stderr
    clean(tmp_path/'stdlib.qvf')


def qvf_orbitals(path, points):
    """Independent direct evaluation of Appendix A for s to g: Cartesian
    monomials in lexicographic order, and spherical S_lm from the Legendre
    definition (no Condon-Shortley phase) for l >= 3."""
    np = pytest.importorskip('numpy')
    with Reader(path) as reader:
        atoms = reader.json('structure','structure')['atoms']
        basis = reader.json('wavefunction','basis'); columns = []
        for shell in basis['shells']:
            delta = points - np.array(atoms[shell['center']]['position']) * BOHR_PER_ANGSTROM
            x,y,z = delta.T; r2 = (delta*delta).sum(axis=1)
            l = shell['l']
            radial = sum(c * primitive_norm(a,l) * np.exp(-a*r2) for a,c in zip(shell['exponents'],shell['coefficients']))
            if l == 0:
                angular = [np.ones(len(points))]
            elif l == 1:
                angular = [y,z,x] if shell['pure'] else [x,y,z]
            elif l == 2 and shell['pure']:
                angular = [math.sqrt(3)*x*y,math.sqrt(3)*y*z,z*z-(x*x+y*y)/2,
                           math.sqrt(3)*x*z,math.sqrt(3)*(x*x-y*y)/2]
            elif shell['pure']:
                r = np.sqrt(r2); t = z/r; phi = np.arctan2(y,x)
                legendre = np.polynomial.legendre.Legendre.basis(l)
                angular = []
                for m in range(-l,l+1):
                    k = abs(m)
                    p = (1-t*t)**(k/2) * legendre.deriv(k)(t) if k else legendre(t)
                    scale = math.sqrt(2*math.factorial(l-k)/math.factorial(l+k)) if k else 1
                    trig = 1 if m == 0 else (np.cos(k*phi) if m > 0 else np.sin(k*phi))
                    angular.append(r**l * scale * p * trig)
            else:
                angular = [x**lx * y**ly * z**(l-lx-ly) for lx in range(l,-1,-1)
                           for ly in range(l-lx,-1,-1)]
            columns.extend(v*radial for v in angular)
        ao = np.array(columns).T
        channels = ['alpha','beta'] if reader.json('wavefunction','mo_metadata')['spin'] == 'unrestricted' else [None]
        return [ao @ np.array(reader.tensor('wavefunction','mo_coefficients'+('_'+ch if ch else '')).tolist()).T for ch in channels]


@pytest.mark.parametrize('cart', [True,False])
@pytest.mark.parametrize('spin', ['restricted','unrestricted'])
def test_pyscf_independent_import_export_orbital_values(tmp_path, cart, spin):
    """PySCF generates and reads files; direct QVF polynomials test each AO.

    No SCF calculation or orbital orthogonality claim: synthetic coefficients
    deliberately excite each component, at off-axis points on two centers.
    """
    np = pytest.importorskip('numpy'); pytest.importorskip('pyscf')
    from pyscf import gto, lib
    from pyscf.tools import molden
    lib.num_threads(1)
    mol = gto.M(atom='He 0 .2 -.1; He .7 -.3 1.1',unit='Bohr',cart=cart,verbose=0,
                basis={'He':[[0,[2.3,.4],[.7,.6]],[1,[1.9,.6],[.5,.4]],[2,[1.3,.7],[.3,.4]],
                             [3,[1.1,.8],[.4,.3]],[4,[.9,1.]]]})
    nao = mol.nao_nr(); coeff = np.eye(nao) + np.arange(nao*nao).reshape(nao,nao)*.001
    points = np.array([[.2,.3,.4],[-.7,.2,.5],[1.1,-.3,-.8],[-.6,-.5,.9]])
    source_file = tmp_path / 'pyscf.molden'
    with source_file.open('w') as stream:
        molden.header(mol,stream)
        molden.orbital_coeff(mol,stream,coeff,spin='Alpha',ene=np.arange(nao)*.2,occ=np.zeros(nao))
        if spin == 'unrestricted':
            molden.orbital_coeff(mol,stream,-.3*coeff,spin='Beta',ene=np.arange(nao)*.3,occ=np.zeros(nao))
    path = tmp_path / 'import.qvf'; import_molden(source_file,path,spin=spin); clean(path)
    ao = mol.eval_gto('GTOval_cart' if cart else 'GTOval_sph',points)
    expected = [ao @ coeff] + ([ao @ (-.3*coeff)] if spin == 'unrestricted' else [])
    actual = qvf_orbitals(path,points)
    for a,b in zip(actual,expected):
        np.testing.assert_allclose(a,b,rtol=3e-12,atol=3e-13)
    output = tmp_path / 'export.molden'; export_molden(path,output)
    independent,energies,matrices,occupations,labels,spins = molden.load(str(output))
    ao2 = independent.eval_gto('GTOval_cart' if cart else 'GTOval_sph',points)
    for matrix,reference in zip(matrices if spin == 'unrestricted' else [matrices],expected):
        np.testing.assert_allclose(ao2 @ matrix,reference,rtol=3e-12,atol=3e-13)


@pytest.mark.parametrize('flags, expected', [
    ('', {2: False, 3: False, 4: False}),
    ('[5D]\n', {2: True, 3: True, 4: False}),
    ('[5D10F]\n', {2: True, 3: False, 4: False}),
    ('[7F]\n', {2: False, 3: True, 4: False}),
    ('[5D7F]\n[9G]\n', {2: True, 3: True, 4: True}),
    ('[6D]\n[15G]\n', {2: False, 3: False, 4: False}),
    ('[5D]\n[10F]\n', None), ('[5D]\n[6D]\n', None), ('[9G]\n[15G]\n', None),
])
def test_shell_convention_flags(flags, expected):
    from qvf._molden import _sections
    text = '[Molden Format]\n[Atoms] AU\n[GTO]\n[MO]\n' + flags
    if expected is None:
        with pytest.raises(ValueError, match='conflicting'):
            _sections(text)
    else:
        assert _sections(text)[1] == expected
