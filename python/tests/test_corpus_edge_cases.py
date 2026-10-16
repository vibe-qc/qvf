"""The edge-case archives of the conformance corpus, checked independently.

``expected.json`` records what a consumer must decode. These tests check the
properties that make each archive an edge case, by parsing the archive here
and not through the generator: the ZIP64 and data-descriptor structures are
read from the raw bytes, and the Appendix A.1 overlaps are integrated
numerically rather than taken from the stored values.
"""

import io
import json
import math
import os
import struct
import sys
import zipfile

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
PYDIR = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, PYDIR)
CORPUS = os.path.join(ROOT, "conformance", "corpus")
LEGACY = os.path.join(ROOT, "conformance", "legacy")

pytestmark = pytest.mark.skipif(
    not os.path.isdir(CORPUS),
    reason="conformance corpus not present (standalone checkout)")

from qvf_reader import Limits, QvfReader, validate_qvf  # noqa: E402

# Codes only a JSON Schema engine can report.
_SCHEMA_CODES = {"E_SCHEMA", "E_PAYLOAD_SCHEMA", "W_SCHEMA_SKIPPED"}


def _path(name, directory=CORPUS):
    return os.path.join(directory, name)


def _raw(name, directory=CORPUS):
    with open(_path(name, directory), "rb") as fh:
        return fh.read()


def _member(reader, section_id, role):
    for s in reader.sections:
        if s["id"] == section_id:
            return s["members"][role]
    raise KeyError(section_id)


# --- container archives ------------------------------------------------------

def test_zip64_archive_carries_every_zip64_structure():
    raw = _raw("zip64.qvf")
    eocd = raw.rfind(b"PK\x05\x06")
    (_sig, disk, cd_disk, n_disk, n_total, cd_size, cd_off,
     comment) = struct.unpack_from("<IHHHHIIH", raw, eocd)
    # The end record defers to ZIP64 for the count, the size and the offset.
    assert (disk, cd_disk, comment) == (0, 0, 0)
    assert (n_disk, n_total) == (0xFFFF, 0xFFFF)
    assert (cd_size, cd_off) == (0xFFFFFFFF, 0xFFFFFFFF)

    # ZIP64 end-of-central-directory locator, immediately before the end record.
    loc_sig, loc_disk, end64_off, n_disks = struct.unpack_from(
        "<IIQI", raw, eocd - 20)
    assert (loc_sig, loc_disk, n_disks) == (0x07064B50, 0, 1)

    # ZIP64 end-of-central-directory record.
    (sig, rec_size, _made, _need, disk64, cd_disk64, n_disk64, n_total64,
     cd_size64, cd_off64) = struct.unpack_from("<IQHHIIQQQQ", raw, end64_off)
    assert sig == 0x06064B50 and rec_size == 44
    assert (disk64, cd_disk64) == (0, 0)
    assert n_disk64 == n_total64 == 5
    assert cd_off64 + cd_size64 == end64_off     # the directory ends at the record

    zf = zipfile.ZipFile(io.BytesIO(raw))
    names = [i.filename for i in zf.infolist()]
    assert len(names) == n_total64

    pos = cd_off64
    for expected_name in names:
        (sig, _made, _need, _flags, method, _t, _d, crc, csize, usize,
         n_len, x_len, c_len, _disk, _iattr, _eattr,
         offset) = struct.unpack_from("<IHHHHHHIIIHHHHHII", raw, pos)
        assert sig == 0x02014B50
        # Every size and the offset are saturated, so the true values live in
        # the ZIP64 extra field, in the order: size, compressed size, offset.
        assert (csize, usize, offset) == (0xFFFFFFFF,) * 3
        name = raw[pos + 46:pos + 46 + n_len].decode()
        assert name == expected_name
        extra = raw[pos + 46 + n_len:pos + 46 + n_len + x_len]
        tag, length = struct.unpack_from("<HH", extra)
        assert (tag, length) == (0x0001, 24)
        usize64, csize64, offset64 = struct.unpack_from("<QQQ", extra, 4)
        info = zf.getinfo(name)
        assert (usize64, csize64) == (info.file_size, info.compress_size)
        assert info.header_offset == offset64

        # The local header has its own ZIP64 extra field with both sizes.
        (lsig, _lver, lflags, lmethod, _lt, _ld, _lcrc, lcsize, lusize,
         ln_len, lx_len) = struct.unpack_from("<IHHHHHIIIHH", raw, offset64)
        assert lsig == 0x04034B50 and lflags & 0x08 == 0
        assert lmethod == method
        assert (lcsize, lusize) == (0xFFFFFFFF, 0xFFFFFFFF)
        lextra = raw[offset64 + 30 + ln_len:offset64 + 30 + ln_len + lx_len]
        assert struct.unpack_from("<HHQQ", lextra) == (
            0x0001, 16, usize64, csize64)
        pos += 46 + n_len + x_len + c_len
    assert pos == cd_off64 + cd_size64

    assert zf.testzip() is None
    assert validate_qvf(_path("zip64.qvf"))["ok"]


def test_zip64_archive_has_small_members():
    """The point is the structures, not the sizes: nothing is anywhere near
    the 32-bit limits."""
    with zipfile.ZipFile(_path("zip64.qvf")) as zf:
        assert max(i.file_size for i in zf.infolist()) < 64 * 1024
    assert len(_raw("zip64.qvf")) < 64 * 1024


def test_data_descriptor_archive_streams_every_member():
    raw = _raw("data_descriptor.qvf")
    zf = zipfile.ZipFile(io.BytesIO(raw))
    for info in zf.infolist():
        (sig, _ver, flags, method, _t, _d, crc, csize, usize, n_len,
         x_len) = struct.unpack_from("<IHHHHHIIIHH", raw, info.header_offset)
        assert sig == 0x04034B50
        assert flags & 0x08, info.filename           # data descriptor present
        assert (crc, csize, usize) == (0, 0, 0), info.filename
        assert method == zipfile.ZIP_DEFLATED
        # Only the central directory knows the sizes ...
        assert info.file_size > 0 and info.compress_size > 0
        # ... and the descriptor after the data repeats them.
        end = info.header_offset + 30 + n_len + x_len + info.compress_size
        dd_sig, dd_crc, dd_csize, dd_usize = struct.unpack_from(
            "<IIII", raw, end)
        assert dd_sig == 0x08074B50
        assert (dd_crc, dd_csize, dd_usize) == (
            info.CRC, info.compress_size, info.file_size)
    assert zf.testzip() is None
    assert validate_qvf(_path("data_descriptor.qvf"))["ok"]


def test_container_archives_hold_the_same_members_as_a_plain_one():
    """zip64.qvf and data_descriptor.qvf differ from an ordinary archive of the
    same calculation in the container only: names, bytes and manifests are
    equal."""
    with zipfile.ZipFile(_path("zip64.qvf")) as a, \
            zipfile.ZipFile(_path("data_descriptor.qvf")) as b:
        assert a.namelist() == b.namelist()
        for name in a.namelist():
            assert a.read(name) == b.read(name), name


# --- wavefunctions ------------------------------------------------------------

def test_uhf_archive_has_distinct_alpha_and_beta_sets():
    with QvfReader(_path("wavefunction_uhf.qvf")) as reader:
        meta = reader.read_json(_member(reader, "wf", "mo_metadata"))
        alpha = reader.read_array(_member(reader, "wf", "mo_coefficients_alpha"))
        beta = reader.read_array(_member(reader, "wf", "mo_coefficients_beta"))
        assert "mo_coefficients" not in next(
            s for s in reader.sections if s["id"] == "wf")["members"]
    assert meta["spin"] == "unrestricted"
    # Unrestricted: orbitals live in alpha / beta, not at the top level.
    for key in ("energies", "occupations", "n_mo"):
        assert key not in meta
    assert alpha.shape == beta.shape == (meta["n_ao"], meta["n_ao"])
    assert not np.array_equal(alpha, beta)
    # A lithium atom: two alpha and one beta electron.
    assert sum(meta["alpha"]["occupations"]) == pytest.approx(2.0)
    assert sum(meta["beta"]["occupations"]) == pytest.approx(1.0)
    assert meta["alpha"]["energies"] != meta["beta"]["energies"]


def _primitive_norm(alpha, l):
    """N_i of spec Appendix A.1, written out here on purpose."""
    double_factorial = 1.0
    for k in range(1, 2 * l, 2):
        double_factorial *= k
    return ((2.0 * alpha / math.pi) ** 0.75 * (4.0 * alpha) ** (l / 2.0)
            / math.sqrt(double_factorial))


def test_cartesian_overlaps_match_numerical_integration():
    """The numbers of the Appendix A.1 trap, integrated on a grid: 1 for an
    axial d component and 1/3 for d_xy, with the stored basis and the format's
    N_i. The stored self_overlap values must agree with the quadrature."""
    path = _path("wavefunction_cartesian.qvf")
    with QvfReader(path) as reader:
        basis = reader.read_json(_member(reader, "wf", "basis"))
        check = reader.read_json(_member(reader, "overlap_check", "payload"))
    assert basis["pure"] is False
    assert all(not sh["pure"] for sh in basis["shells"])

    h = 0.2
    axis = np.arange(-9.0, 9.0 + h / 2, h)
    x, y, z = np.meshgrid(axis, axis, axis, indexing="ij")
    r2 = x * x + y * y + z * z

    def contracted(shell, powers):
        lx, ly, lz = powers
        total = np.zeros_like(r2)
        for a, c in zip(shell["exponents"], shell["coefficients"]):
            total += (c * _primitive_norm(a, shell["l"]) * x ** lx * y ** ly
                      * z ** lz * np.exp(-a * r2))
        return total

    # AO order: the shells in array order, each in A.2 order (decreasing l_x
    # first, then l_y).
    components = []
    for shell in basis["shells"]:
        l = shell["l"]
        for lx in range(l, -1, -1):
            for ly in range(l - lx, -1, -1):
                components.append((shell, (lx, ly, l - lx - ly)))
    assert len(components) == basis["n_ao"] == len(check["self_overlap"])
    assert [list(p) for _, p in components] == check["cartesian_powers"]

    numeric = [float(np.sum(contracted(s, p) ** 2) * h ** 3)
               for s, p in components]
    for got, stored, label in zip(numeric, check["self_overlap"],
                                  check["ao_labels"]):
        assert got == pytest.approx(stored, abs=1e-9), label

    by_label = dict(zip(check["ao_labels"], numeric))
    for axial in ("s", "d_xx", "d_yy", "d_zz"):
        assert by_label[axial] == pytest.approx(1.0, abs=1e-9), axial
    for mixed in ("d_xy", "d_xz", "d_yz"):
        assert by_label[mixed] == pytest.approx(1.0 / 3.0, abs=1e-9), mixed


def test_ecp_archive_counts_its_electrons():
    """n_electrons = sum Z - sum n_core_electrons - charge (spec § 5.3), and
    the occupations and provenance.n_electrons say the same."""
    path = _path("wavefunction_ecp.qvf")
    with QvfReader(path) as reader:
        structure = reader.read_json(_member(reader, "structure", "structure"))
        basis = reader.read_json(_member(reader, "wf", "basis"))
        meta = reader.read_json(_member(reader, "wf", "mo_metadata"))
        overlap = reader.read_array(_member(reader, "wf", "overlap"))
        density = reader.read_array(_member(reader, "wf", "density_matrix"))
        provenance = reader.manifest["provenance"]
    z = sum(a["atomic_number"] for a in structure["atoms"])
    core = sum(e["n_core_electrons"] for e in basis["ecp"])
    assert basis["n_electrons"] == z - core - provenance["charge"] == 2
    assert provenance["n_electrons"] == basis["n_electrons"]
    assert sum(meta["occupations"]) == pytest.approx(basis["n_electrons"])
    assert np.trace(density @ overlap) == pytest.approx(2.0, abs=1e-12)
    # One ECP, on the sodium; its local part has the centre's highest l.
    (ecp,) = basis["ecp"]
    assert structure["atoms"][ecp["center"]]["symbol"] == "Na"
    local = [p for p in ecp["projectors"] if p.get("local")]
    semi = [p for p in ecp["projectors"] if not p.get("local")]
    assert len(local) == 1 and semi
    assert local[0]["l"] > max(p["l"] for p in semi)
    for p in ecp["projectors"]:
        assert len(p["exponents"]) == len(p["coefficients"]) == len(p["powers"])
    assert len(meta["symmetry_labels"]) == len(meta["energies"])
    assert validate_qvf(path)["ok"]


def test_overlap_archive_matches_numerical_integration():
    """The stored overlap matrix of wavefunction_overlap.qvf, integrated on a
    grid from basis.json with the format's N_i and the real solid harmonics
    of Appendix A.2; its diagonal is the Appendix A.1 numbers."""
    path = _path("wavefunction_overlap.qvf")
    with QvfReader(path) as reader:
        structure = reader.read_json(_member(reader, "structure", "structure"))
        basis = reader.read_json(_member(reader, "wf", "basis"))
        stored = reader.read_array(_member(reader, "wf", "overlap"))
        coeffs = reader.read_array(_member(reader, "wf", "mo_coefficients"))
        density = reader.read_array(_member(reader, "wf", "density_matrix"))
    bohr = 1.8897261246
    centres = [np.array(a["position"]) * bohr for a in structure["atoms"]]
    h = 0.2
    x = np.arange(-7.0, 7.0 + h / 2, h)
    z = np.arange(-7.0, 7.0 + centres[1][2] + h / 2, h)
    gx, gy, gz = np.meshgrid(x, x, z, indexing="ij")
    s3 = math.sqrt(3.0)
    harmonics = {0: [[(1.0, (0, 0, 0))]],
                 1: [[(1.0, (0, 1, 0))], [(1.0, (0, 0, 1))], [(1.0, (1, 0, 0))]],
                 2: [[(s3, (1, 1, 0))], [(s3, (0, 1, 1))],
                     [(1.0, (0, 0, 2)), (-0.5, (2, 0, 0)), (-0.5, (0, 2, 0))],
                     [(s3, (1, 0, 1))],
                     [(s3 / 2, (2, 0, 0)), (-s3 / 2, (0, 2, 0))]]}
    aos, kinds = [], []
    for shell in basis["shells"]:
        l, pure = shell["l"], shell.get("pure", basis.get("pure", True))
        c = centres[shell["center"]]
        dx, dy, dz = gx - c[0], gy - c[1], gz - c[2]
        r2 = dx * dx + dy * dy + dz * dz
        radial = sum(co * _primitive_norm(a, l) * np.exp(-a * r2)
                     for a, co in zip(shell["exponents"], shell["coefficients"]))
        terms = harmonics[l] if pure else [
            [(1.0, (lx, ly, l - lx - ly))]
            for lx in range(l, -1, -1) for ly in range(l - lx, -1, -1)]
        for t in terms:
            aos.append((radial * sum(w * dx ** p[0] * dy ** p[1] * dz ** p[2]
                                     for w, p in t)).ravel())
            kinds.append((shell, None if pure else t[0][1]))
    grid = np.array(aos)
    numeric = grid @ grid.T * h ** 3
    assert numeric.shape == stored.shape == (basis["n_ao"], basis["n_ao"])
    assert np.abs(numeric - stored).max() < 1e-8

    # The diagonal is S_axial of the shell, times the Cartesian factor.
    for k, (shell, powers) in enumerate(kinds):
        l, e, co = shell["l"], shell["exponents"], shell["coefficients"]
        s_axial = sum(ci * cj * (2 * math.sqrt(ai * aj) / (ai + aj)) ** (l + 1.5)
                      for ai, ci in zip(e, co) for aj, cj in zip(e, co))
        factor = 1.0
        if powers is not None:
            factor = (_double_factorial(powers) / _double_factorial((l, 0, 0)))
        assert stored[k, k] == pytest.approx(s_axial * factor, rel=1e-12), k
    assert np.allclose(np.diag(stored)[[11, 12, 14]], 1 / 3, atol=1e-12)
    assert not np.isclose(stored[9, 9], 1.0)       # an unnormalized contraction
    # The MOs are orthonormal in this metric, and the density counts 14.
    assert np.allclose(coeffs @ stored @ coeffs.T, np.eye(16), atol=1e-12)
    assert np.trace(density @ stored) == pytest.approx(14.0, abs=1e-10)
    assert validate_qvf(path)["ok"]


def _double_factorial(powers):
    """(2l_x-1)!! (2l_y-1)!! (2l_z-1)!!."""
    out = 1
    for n in powers:
        for k in range(1, 2 * n, 2):
            out *= k
    return out


# --- structures and reaction paths --------------------------------------------

def test_wire_periodic_axis_is_not_the_leading_one():
    with QvfReader(_path("structure_wire_1d.qvf")) as reader:
        payload = reader.read_json(_member(reader, "structure", "structure"))
    assert payload["pbc"] == [False, True, False]
    assert payload["dimensionality"] == sum(payload["pbc"]) == 1
    rows = np.array(payload["lattice_vectors"])
    # The aperiodic rows are synthesized normals of different lengths: neither
    # is a cell edge, and the periodic one is the short middle row.
    lengths = np.linalg.norm(rows, axis=1)
    assert lengths[0] != lengths[2]
    assert lengths[1] < min(lengths[0], lengths[2])


def test_variable_cell_path_lattice_is_per_frame_columns_in_bohr():
    bohr = 1.8897261246
    with QvfReader(_path("reaction_path_variable_cell.qvf")) as reader:
        lattice = reader.read_array(_member(reader, "path", "lattice"))
        coords = reader.read_array(_member(reader, "path", "coords"))
        structure = reader.read_json(_member(reader, "structure", "structure"))
        meta = reader.read_json(_member(reader, "path", "metadata"))
    assert lattice.shape == (coords.shape[0], 3, 3) == (4, 3, 3)
    assert meta["pbc"] == [True, True, True]
    # Every frame has its own cell, and none of them is a symmetric matrix, so
    # reading columns as rows (or the reverse) changes the numbers.
    for f in range(lattice.shape[0]):
        assert not np.allclose(lattice[f], lattice[f].T)
        if f:
            assert not np.allclose(lattice[f], lattice[f - 1])
    # Frame 0 is the structure's cell: columns of L = rows of R, in bohr.
    rows = np.array(structure["lattice_vectors"])
    assert np.allclose(lattice[0], bohr * rows.T, atol=1e-9)


def test_md_periodic_is_a_consistent_npt_run():
    """md_periodic.qvf: float32 coords with precision, one cell per frame in
    rows and Å (the structure convention, not reaction.path's), and per-frame
    members that agree with each other: constant-velocity kinematics, the
    cell volume as the determinant of the rows, binary energies equal to
    metadata.energies (spec § 4.3, § 5.5)."""
    with QvfReader(_path("md_periodic.qvf")) as reader:
        members = next(s for s in reader.sections if s["id"] == "md")["members"]
        meta = reader.read_json(members["metadata"])
        coords = reader.read_array(members["coords"])
        arrays = {role: reader.read_array(members[role])
                  for role in ("lattice", "velocities", "gradient", "times",
                               "energies", "cell_volumes", "temperatures")}
        structure = reader.read_json(_member(reader, "structure", "structure"))
    n_frames, n_atoms = coords.shape[:2]
    assert members["coords"]["dtype"] == "float32" == meta["precision"]
    assert meta["kind"] == "md" and meta["ensemble"] == "npt"
    assert meta["pbc"] == [True, True, True]
    assert arrays["lattice"].shape == (n_frames, 3, 3)
    assert arrays["velocities"].shape == arrays["gradient"].shape == coords.shape
    for role in ("times", "energies", "cell_volumes", "temperatures"):
        assert arrays[role].shape == (n_frames,), role
    # Rows in Å: frame 0 is the structure's lattice_vectors, element for element.
    assert np.allclose(arrays["lattice"][0], structure["lattice_vectors"])
    for f in range(n_frames):
        assert not np.allclose(arrays["lattice"][f], arrays["lattice"][f].T)
        assert arrays["cell_volumes"][f] == pytest.approx(
            abs(np.linalg.det(arrays["lattice"][f])), rel=1e-12)
    assert np.allclose(arrays["times"], meta["timestep_fs"] * np.arange(n_frames))
    expected = coords[0] + arrays["velocities"] * arrays["times"][:, None, None]
    assert np.allclose(coords, expected, atol=1e-5)
    assert np.array_equal(arrays["energies"], np.array(meta["energies"]))


# --- periodic grids (spec § 5.2) -----------------------------------------------

def test_volume_periodic_spans_its_cell_in_both_conventions():
    """Both grids span the hexagonal cell (spec § 5.2), and dropping the
    duplicated plane of the cube-style grid gives the CHGCAR-style one."""
    with QvfReader(_path("volume_periodic.qvf")) as r:
        by_id = {s["id"]: s for s in r.sections}
        rows = np.array(r.read_json(by_id["structure"]["members"]["structure"])
                        ["lattice_vectors"]) * 1.8897261246  # bohr per Å, spec § 4.3
        chg = r.read_json(by_id["rho_chgcar"]["members"]["grid"])
        cube = r.read_json(by_id["rho_cube"]["members"]["grid"])
        for grid, drop in ((chg, 0), (cube, 1)):
            for a in range(3):
                span = np.array(grid["voxel_vectors"][a]) * (grid["shape"][a] - drop)
                assert np.allclose(span, rows[a], rtol=0, atol=1e-9)
        assert chg["includes_endpoint"] is False and cube["includes_endpoint"] is True
        rho = r.read_array(by_id["rho_chgcar"]["members"]["data"])
        tiled = r.read_array(by_id["rho_cube"]["members"]["data"])
        # Dropping the duplicated plane of the cube grid gives the CHGCAR grid,
        # and the dropped plane is plane 0 again.
        assert np.array_equal(tiled[:-1, :-1, :-1], rho)
        assert np.array_equal(tiled[-1], tiled[0])
        assert np.array_equal(tiled[:, -1], tiled[:, 0])
        assert np.array_equal(tiled[:, :, -1], tiled[:, :, 0])


# --- legacy -------------------------------------------------------------------

def test_legacy_archive_is_stamped_version_2_and_valid_with_a_warning():
    """Spec § 3.1: a validator reads the withdrawn version 2 as 1, the JSON
    Schema check included, and reports W_VERSION_WITHDRAWN."""
    path = _path("reaction_path_v2.qvf", LEGACY)
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["qvf_version"] == 2
    assert any(s["kind"] == "reaction.path" and "lattice" in s["members"]
               for s in manifest["sections"])
    report = validate_qvf(path)
    assert report["ok"], report["findings"]
    assert [(f["code"], f["severity"], f["where"]) for f in report["findings"]] == [
        ("W_VERSION_WITHDRAWN", "warning", "/qvf_version")]


def test_legacy_archive_is_otherwise_a_valid_v1_archive(tmp_path):
    """Restamped as version 1 it validates clean, so the version stamp is the
    only thing standing between it and a positive test."""
    src = _path("reaction_path_v2.qvf", LEGACY)
    dst = tmp_path / "restamped.qvf"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info)
            if info.filename == "manifest.json":
                manifest = json.loads(data)
                manifest["qvf_version"] = 1
                data = json.dumps(manifest, indent=2).encode()
            zout.writestr(info, data)
    report = validate_qvf(str(dst), limits=Limits())
    assert report["ok"], report["findings"]
