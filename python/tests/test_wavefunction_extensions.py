"""wavefunction.gto extensions (spec § 5.3, Appendix A.1).

Effective core potentials and the electron count, two-component and complex
coefficients, symmetry labels, the optional ``overlap`` and density-matrix
members, and the normalization check that ``overlap`` makes possible
(``E_NORMALIZATION``). Archives the reference writer refuses to produce are
assembled here with ``zipfile``.
"""

import hashlib
import io
import json
import math
import os
import sys
import zipfile

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

import qvf_reader  # noqa: E402
from qvf_reader import validate_qvf  # noqa: E402
from qvf_writer import QvfWriter, primitive_norm  # noqa: E402

WATER = [{"symbol": "O", "position": [0.0, 0.0, 0.1173], "atomic_number": 8},
         {"symbol": "H", "position": [0.0, 0.7572, -0.4692], "atomic_number": 1},
         {"symbol": "H", "position": [0.0, -0.7572, -0.4692], "atomic_number": 1}]

# --- one-centre AO overlaps, written out independently of the validator --------

_SQRT3 = math.sqrt(3.0)
_SOLID = {  # real solid harmonics, m = -l..+l, as (weight, powers)
    0: [[(1.0, (0, 0, 0))]],
    1: [[(1.0, (0, 1, 0))], [(1.0, (0, 0, 1))], [(1.0, (1, 0, 0))]],
    2: [[(_SQRT3, (1, 1, 0))], [(_SQRT3, (0, 1, 1))],
        [(1.0, (0, 0, 2)), (-0.5, (2, 0, 0)), (-0.5, (0, 2, 0))],
        [(_SQRT3, (1, 0, 1))],
        [(0.5 * _SQRT3, (2, 0, 0)), (-0.5 * _SQRT3, (0, 2, 0))]],
}


def _terms(l, pure):
    if pure:
        return _SOLID[l]
    return [[(1.0, (lx, ly, l - lx - ly))]
            for lx in range(l, -1, -1) for ly in range(l - lx, -1, -1)]


def _gauss_moment(n, p):
    """int x^n exp(-p x^2) dx."""
    if n % 2:
        return 0.0
    df = 1.0
    for k in range(1, n, 2):
        df *= k
    return df / (2.0 * p) ** (n // 2) * math.sqrt(math.pi / p)


def _one_centre_overlap(shells):
    """AO overlap of basis.json ``shells`` (explicit ``pure``) on one centre."""
    aos = [(sh, t) for sh in shells for t in _terms(sh["l"], sh["pure"])]
    s = np.zeros((len(aos), len(aos)))
    for mu, (sa, ta) in enumerate(aos):
        for nu, (sb, tb) in enumerate(aos):
            for a, ca in zip(sa["exponents"], sa["coefficients"]):
                for b, cb in zip(sb["exponents"], sb["coefficients"]):
                    ang = sum(w1 * w2 * math.prod(
                        _gauss_moment(p1[k] + p2[k], a + b) for k in range(3))
                        for w1, p1 in ta for w2, p2 in tb)
                    s[mu, nu] += (ca * cb * primitive_norm(a, sa["l"])
                                  * primitive_norm(b, sb["l"]) * ang)
    return s


# s (not contraction-normalized), spherical p, spherical d, Cartesian d.
SHELLS = [
    {"center": 0, "l": 0, "exponents": [3.0, 0.7], "coefficients": [0.4, 0.5],
     "pure": True},
    {"center": 0, "l": 1, "exponents": [1.3], "coefficients": [1.0],
     "pure": True},
    {"center": 0, "l": 2, "exponents": [0.9, 0.3], "coefficients": [0.6, 0.5],
     "pure": True},
    {"center": 0, "l": 2, "exponents": [1.6, 0.45], "coefficients": [0.7, 0.4],
     "pure": False},
]
N_AO = 1 + 3 + 5 + 6
DXY = 1 + 3 + 5 + 1          # index of the Cartesian d_xy component


def _writer_archive(tmp_path, overlap, *, shells=SHELLS, name="wf.qvf", **kw):
    w = QvfWriter("test-code", "1.0", "wavefunction")
    w.add_structure(WATER)
    n_ao = overlap.shape[0] if overlap is not None else N_AO
    w.add_wavefunction_gto(shells, mo_coefficients=np.eye(n_ao),
                           overlap=overlap, **kw)
    path = str(tmp_path / name)
    w.write(path)
    return path


def _codes(report):
    return {f["code"] for f in report["findings"]} - {"W_SCHEMA_SKIPPED"}


def _only(report, code):
    found = [f for f in report["findings"] if f["code"] == code]
    assert found, report["findings"]
    return found


# --- the Appendix A.1 arithmetic ------------------------------------------------

@pytest.mark.parametrize("l", range(5))
def test_axial_self_overlap_is_the_n_i_integral(l):
    """The validator's closed form equals sum c_i c_j N_i N_j <x^l|x^l>."""
    exps, coefs = [2.7, 0.9, 0.21], [0.3, 0.6, 0.25]
    explicit = sum(
        ca * cb * primitive_norm(a, l) * primitive_norm(b, l)
        * _gauss_moment(2 * l, a + b) * _gauss_moment(0, a + b) ** 2
        for a, ca in zip(exps, coefs) for b, cb in zip(exps, coefs))
    assert qvf_reader._axial_self_overlap(l, exps, coefs) == pytest.approx(
        explicit, rel=1e-13)


def test_reference_overlap_has_the_appendix_a1_diagonal():
    s = _one_centre_overlap(SHELLS)
    diag = np.diag(s)
    # Spherical p and d: every component has the axial self-overlap.
    assert np.allclose(diag[1:4], diag[1]) and np.allclose(diag[4:9], diag[4])
    # Cartesian d: 1/3 of the axial value for the mixed components.
    axial = diag[DXY - 1]
    assert np.allclose(diag[DXY - 1:DXY + 5],
                       axial * np.array([1, 1 / 3, 1 / 3, 1, 1 / 3, 1]))


# --- E_NORMALIZATION --------------------------------------------------------------

def test_correct_overlap_validates(tmp_path):
    report = validate_qvf(_writer_archive(tmp_path, _one_centre_overlap(SHELLS)))
    assert report["ok"], report["findings"]
    assert "E_NORMALIZATION" not in _codes(report)


def test_dxy_scaled_by_three_is_e_normalization(tmp_path):
    """The per-component-normalization bug: d_xy at 1 instead of 1/3."""
    s = _one_centre_overlap(SHELLS)
    s[DXY, DXY] *= 3.0
    report = validate_qvf(_writer_archive(tmp_path, s))
    assert _codes(report) == {"E_NORMALIZATION"}
    (finding,) = _only(report, "E_NORMALIZATION")
    assert finding["where"] == "/sections/1/members/overlap"
    assert f"AO {DXY}" in finding["message"]


def test_coefficients_not_divided_by_n_i_is_e_normalization(tmp_path):
    """The libint/libcint trap: the overlap is that of the true AOs, but
    basis.json carries the engine's coefficients, pre-multiplied by N_i."""
    s = _one_centre_overlap(SHELLS)
    engine = [dict(sh, coefficients=[c * primitive_norm(a, sh["l"])
                                     for a, c in zip(sh["exponents"],
                                                     sh["coefficients"])])
              for sh in SHELLS]
    report = validate_qvf(_writer_archive(tmp_path, s, shells=engine))
    assert _codes(report) == {"E_NORMALIZATION"}
    assert f"{N_AO} of {N_AO}" in _only(report, "E_NORMALIZATION")[0]["message"]
    # The writer's flag is the fix: it divides the engine coefficients.
    fixed = validate_qvf(_writer_archive(tmp_path, s, shells=engine,
                                         name="fixed.qvf",
                                         coeffs_are_libint_normalized=True))
    assert fixed["ok"], fixed["findings"]


def test_cartesian_order_other_than_a2_is_e_normalization(tmp_path):
    """Cartesian d in xx, yy, zz, xy, xz, yz order instead of Appendix A.2."""
    s = _one_centre_overlap(SHELLS)
    start = DXY - 1
    order = list(range(N_AO))
    order[start:start + 6] = [start + k for k in (0, 3, 5, 1, 2, 4)]
    report = validate_qvf(_writer_archive(tmp_path, s[np.ix_(order, order)]))
    assert _codes(report) == {"E_NORMALIZATION"}


def test_permutation_within_a_spherical_shell_is_not_seen(tmp_path):
    """The check reads the diagonal only (spec Appendix A.1): the components
    of a spherical shell have equal diagonal entries, so permuting m passes."""
    s = _one_centre_overlap(SHELLS)
    order = list(range(N_AO))
    order[4:9] = order[4:9][::-1]
    assert validate_qvf(_writer_archive(tmp_path, s[np.ix_(order, order)]))["ok"]


@pytest.mark.parametrize("scale,ok", [(1 + 5e-7, True), (1 - 5e-7, True),
                                      (1 + 2e-6, False), (1 - 2e-6, False)])
def test_normalization_tolerance_is_relative_1e_6(tmp_path, scale, ok):
    s = _one_centre_overlap(SHELLS)
    s[0, 0] *= scale
    report = validate_qvf(_writer_archive(tmp_path, s))
    assert report["ok"] is ok, report["findings"]


def test_normalization_skips_an_overlap_of_the_wrong_shape(tmp_path):
    """A wrong shape is E_MEMBER_MALFORMED; the diagonal is then not judged."""
    path = _raw_archive(tmp_path, _basis(), _meta(4),
                        {"mo_coefficients": np.eye(4),
                         "overlap": np.eye(3)})
    report = validate_qvf(path)
    assert _codes(report) == {"E_MEMBER_MALFORMED"}
    assert _only(report, "E_MEMBER_MALFORMED")[0]["where"] == \
        "/sections/1/members/overlap"


# --- archives the writer refuses ----------------------------------------------------

def _basis(**extra):
    """s + spherical p on the oxygen: n_ao 4, contraction-normalized."""
    basis = {"structure_ref": "structure", "pure": True, "n_ao": 4,
             "shells": [{"center": 0, "l": 0, "exponents": [1.0],
                         "coefficients": [1.0]},
                        {"center": 0, "l": 1, "exponents": [0.5],
                         "coefficients": [1.0]}]}
    basis.update(extra)
    return basis


def _meta(n_mo, **extra):
    meta = {"n_mo": n_mo, "n_ao": 4, "spin": "restricted",
            "orbital_kind": "canonical", "energies": [0.0] * n_mo,
            "occupations": [2.0] + [0.0] * (n_mo - 1)}
    meta.update(extra)
    return meta


def _uhf_meta(**extra):
    meta = {"n_ao": 4, "spin": "unrestricted", "orbital_kind": "canonical",
            "alpha": {"n_mo": 4, "energies": [0.0] * 4,
                      "occupations": [1.0, 0.0, 0.0, 0.0]},
            "beta": {"n_mo": 4, "energies": [0.0] * 4,
                     "occupations": [1.0, 0.0, 0.0, 0.0]}}
    meta.update(extra)
    return meta


def _raw_archive(tmp_path, basis, meta, binaries, *, provenance=None,
                 name="raw.qvf"):
    """structure + one wavefunction.gto section with these members."""
    files, members = {}, {}

    def add_json(role, path, obj):
        data = json.dumps(obj, indent=1).encode()
        files[path] = data
        return {"path": path, "format": "json",
                "sha256": hashlib.sha256(data).hexdigest()}

    structure = add_json("structure", "structure/structure.json",
                         {"atoms": WATER, "pbc": [False] * 3,
                          "lattice_vectors": None})
    members["basis"] = add_json("basis", "wf/basis.json", basis)
    members["mo_metadata"] = add_json("mo_metadata", "wf/mo_metadata.json", meta)
    for role, array in binaries.items():
        arr = np.ascontiguousarray(np.asarray(array, dtype="<f8"))
        data = arr.tobytes()
        files[f"wf/{role}.dat"] = data
        members[role] = {"path": f"wf/{role}.dat", "format": "binary",
                         "dtype": "float64", "shape": list(arr.shape),
                         "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {"qvf_version": 1,
                "source": {"program": "test-code", "version": "1.0",
                           "calculation": "raw"},
                "sections": [{"id": "structure", "kind": "structure",
                              "members": {"structure": structure}},
                             {"id": "wf", "kind": "wavefunction.gto",
                              "members": members}]}
    if provenance is not None:
        manifest["provenance"] = provenance
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, data in files.items():
            zf.writestr(path, data)
        zf.writestr("manifest.json", json.dumps(manifest, indent=1))
    path = tmp_path / name
    path.write_bytes(buf.getvalue())
    return str(path)


def _report(tmp_path, *args, **kw):
    return validate_qvf(_raw_archive(tmp_path, *args, **kw))


# --- complex coefficients -------------------------------------------------------------

def test_complex_true_with_rank_2_coefficients(tmp_path):
    report = _report(tmp_path, _basis(), _meta(4, complex=True),
                     {"mo_coefficients": np.eye(4)})
    assert _codes(report) == {"E_MEMBER_MALFORMED"}
    assert _only(report, "E_MEMBER_MALFORMED")[0]["where"] == \
        "/sections/1/members/mo_coefficients"


def test_real_with_rank_3_coefficients(tmp_path):
    report = _report(tmp_path, _basis(), _meta(4),
                     {"mo_coefficients": np.zeros((4, 4, 2))})
    assert _codes(report) == {"E_MEMBER_MALFORMED"}


def test_complex_trailing_axis_must_be_two(tmp_path):
    report = _report(tmp_path, _basis(), _meta(4, complex=True),
                     {"mo_coefficients": np.zeros((4, 4, 3))})
    assert _codes(report) == {"E_MEMBER_MALFORMED"}


def test_complex_rank_3_validates(tmp_path):
    assert _report(tmp_path, _basis(), _meta(4, complex=True),
                   {"mo_coefficients": np.zeros((4, 4, 2))})["ok"]


def test_coefficient_encoding_is_read_when_complex_is_absent(tmp_path):
    meta = _meta(4, coefficient_encoding="complex_split_last_axis")
    assert _report(tmp_path, _basis(), meta,
                   {"mo_coefficients": np.zeros((4, 4, 2))})["ok"]
    report = _report(tmp_path, _basis(), meta,
                     {"mo_coefficients": np.eye(4)}, name="b.qvf")
    assert _codes(report) == {"E_MEMBER_MALFORMED"}


def test_unrestricted_complex_checks_both_members(tmp_path):
    report = _report(tmp_path, _basis(), _uhf_meta(complex=True),
                     {"mo_coefficients_alpha": np.zeros((4, 4, 2)),
                      "mo_coefficients_beta": np.eye(4)})
    assert [f["where"] for f in report["findings"]
            if f["code"] == "E_MEMBER_MALFORMED"] == \
        ["/sections/1/members/mo_coefficients_beta"]


def test_generalized_must_be_complex_in_the_schema(tmp_path):
    pytest.importorskip("jsonschema")
    report = _report(tmp_path, _basis(), _meta(8, spin="generalized"),
                     {"mo_coefficients": np.eye(8)})
    assert _codes(report) == {"E_PAYLOAD_SCHEMA"}


# --- symmetry labels ----------------------------------------------------------------------

def test_symmetry_labels_length(tmp_path):
    report = _report(tmp_path, _basis(),
                     _meta(4, symmetry_labels=["a1", "a1", "b1"]),
                     {"mo_coefficients": np.eye(4)})
    assert _codes(report) == {"E_MEMBER_MALFORMED"}
    assert _only(report, "E_MEMBER_MALFORMED")[0]["where"] == \
        "/sections/1/members/mo_metadata"


def test_channel_symmetry_labels_length(tmp_path):
    meta = _uhf_meta()
    meta["beta"]["symmetry_labels"] = ["a1"] * 5
    report = _report(tmp_path, _basis(), meta,
                     {"mo_coefficients_alpha": np.eye(4),
                      "mo_coefficients_beta": np.eye(4)})
    assert _codes(report) == {"E_MEMBER_MALFORMED"}
    assert "beta.symmetry_labels" in _only(report, "E_MEMBER_MALFORMED")[0]["message"]


# --- AO-basis matrices ---------------------------------------------------------------------

@pytest.mark.parametrize("role", ["overlap", "density_matrix"])
def test_ao_matrix_shape(tmp_path, role):
    report = _report(tmp_path, _basis(), _meta(4),
                     {"mo_coefficients": np.eye(4), role: np.eye(5)})
    assert _codes(report) == {"E_MEMBER_MALFORMED"}
    assert _only(report, "E_MEMBER_MALFORMED")[0]["where"] == \
        f"/sections/1/members/{role}"


def test_n_ao_falls_back_to_the_declared_one(tmp_path):
    """With shells that cannot be read the declared n_ao is used."""
    basis = _basis()
    basis["shells"][1]["l"] = "p"
    report = _report(tmp_path, basis, _meta(4),
                     {"mo_coefficients": np.eye(4),
                      "density_matrix": np.eye(3)})
    assert "E_MEMBER_MALFORMED" in _codes(report)


@pytest.mark.parametrize("coeffs,density,bad", [
    (("mo_coefficients_alpha", "mo_coefficients_beta"),
     ("density_matrix",), "density_matrix"),
    (("mo_coefficients",), ("density_matrix_alpha",), "density_matrix_alpha"),
    (("mo_coefficients_alpha", "mo_coefficients_beta"),
     ("density_matrix_beta",), "density_matrix_beta"),
])
def test_density_members_pair_with_the_coefficients(tmp_path, coeffs, density,
                                                    bad):
    meta = _uhf_meta() if len(coeffs) == 2 else _meta(4)
    binaries = {role: np.eye(4) for role in coeffs + density}
    report = _report(tmp_path, _basis(), meta, binaries)
    assert _codes(report) == {"E_MEMBER_MALFORMED"}
    assert [f["where"] for f in report["findings"]
            if f["code"] == "E_MEMBER_MALFORMED"] == [f"/sections/1/members/{bad}"]


def test_unrestricted_density_pair_validates(tmp_path):
    assert _report(tmp_path, _basis(), _uhf_meta(),
                   {"mo_coefficients_alpha": np.eye(4),
                    "mo_coefficients_beta": np.eye(4),
                    "density_matrix_alpha": np.eye(4),
                    "density_matrix_beta": np.eye(4)})["ok"]


# --- n_electrons ------------------------------------------------------------------------------

def test_n_electrons_against_occupations(tmp_path):
    report = _report(tmp_path, _basis(n_electrons=4), _meta(4),
                     {"mo_coefficients": np.eye(4)})
    assert _codes(report) == {"E_MEMBER_MALFORMED"}
    assert _only(report, "E_MEMBER_MALFORMED")[0]["where"] == \
        "/sections/1/members/basis"


def test_n_electrons_sums_both_spin_channels(tmp_path):
    assert _report(tmp_path, _basis(n_electrons=2), _uhf_meta(),
                   {"mo_coefficients_alpha": np.eye(4),
                    "mo_coefficients_beta": np.eye(4)})["ok"]
    report = _report(tmp_path, _basis(n_electrons=1), _uhf_meta(),
                     {"mo_coefficients_alpha": np.eye(4),
                      "mo_coefficients_beta": np.eye(4)}, name="b.qvf")
    assert _codes(report) == {"E_MEMBER_MALFORMED"}


def test_n_electrons_tolerance_and_transition_weights(tmp_path):
    meta = _meta(4)
    meta["occupations"] = [1.9999995, 0.0, 0.0, 0.0]
    assert _report(tmp_path, _basis(n_electrons=2), meta,
                   {"mo_coefficients": np.eye(4)})["ok"]
    # NTO weights are not electrons: not compared.
    meta = _meta(4, occupation_semantics="transition_weight", orbital_kind="nto")
    meta["occupations"] = [0.9, 0.1, 0.0, 0.0]
    assert _report(tmp_path, _basis(n_electrons=2), meta,
                   {"mo_coefficients": np.eye(4)}, name="nto.qvf")["ok"]


def test_provenance_n_electrons_must_agree(tmp_path):
    ok = _report(tmp_path, _basis(n_electrons=2), _meta(4),
                 {"mo_coefficients": np.eye(4)}, provenance={"n_electrons": 2})
    assert ok["ok"], ok["findings"]
    report = _report(tmp_path, _basis(n_electrons=2), _meta(4),
                     {"mo_coefficients": np.eye(4)},
                     provenance={"n_electrons": 10}, name="b.qvf")
    assert _codes(report) == {"E_ROOT_INCONSISTENT"}
    assert _only(report, "E_ROOT_INCONSISTENT")[0]["where"] == \
        "/sections/1/members/basis"


# --- the writer ------------------------------------------------------------------------------

def _w():
    w = QvfWriter("test-code", "1.0", "wavefunction")
    w.add_structure(WATER)
    return w


_SP = [{"center": 0, "l": 0, "exponents": [1.0], "coefficients": [1.0]},
       {"center": 0, "l": 1, "exponents": [0.5], "coefficients": [1.0]}]
_ECP = [{"center": 0, "n_core_electrons": 2, "label": "toy",
         "projectors": [{"l": 1, "exponents": [2.0], "coefficients": [-1.0],
                         "powers": [2], "local": True},
                        {"l": 0, "exponents": [3.0, 1.0],
                         "coefficients": [5.0, -0.5], "powers": [0, 2],
                         "x_note": "s channel"}]}]


def test_writer_round_trip(tmp_path):
    w = _w()
    occ = [2.0, 0.0, 0.0, 0.0]
    w.add_wavefunction_gto(_SP, mo_coefficients=np.eye(4), occupations=occ,
                           ecp=_ECP, n_electrons=2,
                           symmetry_labels=["a1", "b2", "a1", "b1"],
                           overlap=np.eye(4), density_matrix=np.diag(occ))
    w.set_provenance(n_electrons=2)
    path = str(tmp_path / "rt.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["findings"]
    with qvf_reader.QvfReader(path) as r:
        wf = next(s for s in r.sections if s["id"] == "wf")
        basis = r.read_json(wf["members"]["basis"])
        meta = r.read_json(wf["members"]["mo_metadata"])
        assert r.read_array(wf["members"]["overlap"]).shape == (4, 4)
    assert basis["n_electrons"] == 2
    local, s_channel = basis["ecp"][0]["projectors"]
    assert local["local"] is True and "local" not in s_channel
    assert s_channel["powers"] == [0, 2] and s_channel["x_note"] == "s channel"
    assert meta["symmetry_labels"] == ["a1", "b2", "a1", "b1"]
    assert "complex" not in meta
    assert list(wf["members"]) == ["basis", "mo_metadata", "mo_coefficients",
                                   "overlap", "density_matrix"]


def test_writer_generalized_complex(tmp_path):
    w = _w()
    G = np.arange(64.0).reshape(8, 8) + 1j * np.eye(8)
    w.add_wavefunction_gto(_SP, mo_coefficients=G, spin="generalized",
                           complex_coefficients=True,
                           occupations=[1.0] * 2 + [0.0] * 6, n_electrons=2)
    path = str(tmp_path / "ghf.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["findings"]
    with qvf_reader.QvfReader(path) as r:
        wf = next(s for s in r.sections if s["id"] == "wf")
        meta = r.read_json(wf["members"]["mo_metadata"])
        C = r.read_array(wf["members"]["mo_coefficients"])
    assert meta["spin"] == "generalized" and meta["complex"] is True
    assert meta["n_ao"] == 4
    assert C.shape == (8, 8, 2)                       # 2 n_ao AO columns
    assert np.array_equal(C[..., 0], G.real) and np.array_equal(C[..., 1], G.imag)


def test_writer_unrestricted_complex_and_labels(tmp_path):
    w = _w()
    C = np.zeros((4, 4, 2))
    C[..., 0] = np.eye(4)
    w.add_wavefunction_gto(_SP, mo_coefficients_alpha=C, mo_coefficients_beta=C,
                           occupations_alpha=[1, 0, 0, 0],
                           occupations_beta=[1, 0, 0, 0],
                           complex_coefficients=True, n_electrons=2,
                           symmetry_labels={"beta": ["a", "b", "c", "d"]},
                           density_matrix_alpha=np.eye(4),
                           density_matrix_beta=np.eye(4))
    path = str(tmp_path / "uhf.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["findings"]


_BAD_WRITES = {
    "overlap shape": dict(overlap=np.eye(3)),
    "overlap complex": dict(overlap=np.eye(4) * 1j),
    "density with unrestricted": dict(unrestricted=True,
                                      density_matrix=np.eye(4)),
    "alpha density without beta": dict(unrestricted=True,
                                       density_matrix_alpha=np.eye(4)),
    "alpha density with restricted": dict(density_matrix_alpha=np.eye(4),
                                          density_matrix_beta=np.eye(4)),
    "n_electrons vs default zero occupations": dict(n_electrons=2,
                                                    occupations=None),
    "n_electrons vs occupations": dict(n_electrons=3),
    "n_electrons negative": dict(n_electrons=-2),
    "n_electrons bool": dict(n_electrons=True),
    "ecp duplicate centre": dict(ecp=[{"center": 0, "n_core_electrons": 2},
                                      {"center": 0, "n_core_electrons": 2}]),
    "ecp unknown key": dict(ecp=[{"center": 0, "n_core_electrons": 2,
                                  "core": 2}]),
    "ecp n_core missing": dict(ecp=[{"center": 0}]),
    "ecp ragged": dict(ecp=[{"center": 0, "n_core_electrons": 2, "projectors": [
        {"l": 0, "exponents": [1.0, 2.0], "coefficients": [1.0],
         "powers": [2, 2]}]}]),
    "ecp exponent not positive": dict(ecp=[{"center": 0, "n_core_electrons": 2,
                                            "projectors": [
        {"l": 0, "exponents": [0.0], "coefficients": [1.0], "powers": [2]}]}]),
    "ecp powers not integers": dict(ecp=[{"center": 0, "n_core_electrons": 2,
                                          "projectors": [
        {"l": 0, "exponents": [1.0], "coefficients": [1.0], "powers": [2.5]}]}]),
    "ecp two local parts": dict(ecp=[{"center": 0, "n_core_electrons": 2,
                                      "projectors": [
        {"l": 2, "exponents": [1.0], "coefficients": [1.0], "powers": [2],
         "local": True},
        {"l": 3, "exponents": [1.0], "coefficients": [1.0], "powers": [2],
         "local": True}]}]),
    "ecp local not the highest l": dict(ecp=[{"center": 0, "n_core_electrons": 2,
                                              "projectors": [
        {"l": 1, "exponents": [1.0], "coefficients": [1.0], "powers": [2],
         "local": True},
        {"l": 2, "exponents": [1.0], "coefficients": [1.0], "powers": [2]}]}]),
    "ecp not a list": dict(ecp={"center": 0, "n_core_electrons": 2}),
    "generalized without complex": dict(spin="generalized",
                                        mo_coefficients=np.eye(8)),
    "complex array without the flag": dict(mo_coefficients=np.eye(4) * 1j),
    "complex flag with real rank 2": dict(complex_coefficients=True),
    "AO columns": dict(mo_coefficients=np.eye(5)),
    "symmetry labels length": dict(symmetry_labels=["a1"] * 3),
    "symmetry labels not strings": dict(symmetry_labels=[1, 2, 3, 4]),
    "unrestricted symmetry labels as a list": dict(unrestricted=True,
                                                   symmetry_labels=["a"] * 4),
    "unknown spin": dict(spin="ghf"),
    "unrestricted spin with one set": dict(spin="unrestricted"),
    "single-set spin with alpha and beta": dict(unrestricted=True,
                                                spin="restricted_open"),
}


@pytest.mark.parametrize("case", sorted(_BAD_WRITES))
def test_writer_refuses_and_writes_nothing(case):
    kw = dict(_BAD_WRITES[case])
    w = _w()
    args = {"occupations": [2.0, 0.0, 0.0, 0.0]}
    if kw.pop("unrestricted", False):
        args = {"mo_coefficients_alpha": np.eye(4),
                "mo_coefficients_beta": np.eye(4),
                "occupations_alpha": [1, 0, 0, 0],
                "occupations_beta": [1, 0, 0, 0]}
    else:
        args["mo_coefficients"] = np.eye(4)
    args.update(kw)
    if args.get("occupations", 0) is None:
        del args["occupations"]
    if args.get("spin") == "restricted_open":
        args.pop("mo_coefficients", None)
    files_before = dict(w._files)
    with pytest.raises(ValueError):
        w.add_wavefunction_gto(_SP, **args)
    assert w._files == files_before
    assert [s["id"] for s in w._sections] == ["structure"]
