"""In-place update, repack and forced ZIP64 for the Python reference writer.

Spec § 2.3: an update appends members and writes a new ``manifest.json``
last; the previous manifest stays as a superseded entry (``W_ORPHAN_MEMBER``)
and readers use the last one; no other entry name is reused; ``repack``
removes orphans and superseded manifests. The forced-ZIP64 archive and an
updated archive are also read by the C++ reader (``read_qvf``) when a build of
it is found (``QVF_READ_QVF`` names the binary, else ``build*/`` and
``cpp/build*/`` are searched); otherwise that test is skipped.
"""

import glob
import io
import os
import shutil
import struct
import subprocess
import sys
import zipfile

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
PYDIR = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, PYDIR)
CORPUS = os.path.join(ROOT, "conformance", "corpus")

from qvf_reader import QvfReader, validate_qvf  # noqa: E402
from qvf_writer import QvfWriter, repack  # noqa: E402


def _water(calculation="water"):
    w = QvfWriter("update-test", "1.0", calculation, auto_metadata=False)
    w.add_structure([
        {"symbol": "O", "position": [0.0, 0.0, 0.1173], "atomic_number": 8},
        {"symbol": "H", "position": [0.0, 0.7572, -0.4692], "atomic_number": 1},
        {"symbol": "H", "position": [0.0, -0.7572, -0.4692], "atomic_number": 1}])
    w.add_atom_properties(mulliken_charge=[-0.70, 0.35, 0.35])
    w.set_metadata(title="update test", x_note="kept")
    return w


def _codes(report):
    return [f["code"] for f in report["findings"]]


def _no_findings(report):
    """Valid, with no finding except a skipped schema check."""
    return report["ok"] and set(_codes(report)) <= {"W_SCHEMA_SKIPPED"}


def _orphans(report):
    return _codes(report).count("W_ORPHAN_MEMBER")


def test_manifest_is_stored_and_last(tmp_path):
    path = _water().write(str(tmp_path / "plain"))
    assert path.endswith("plain.qvf")
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
    assert infos[-1].filename == "manifest.json"
    assert infos[-1].compress_type == zipfile.ZIP_STORED
    assert _no_findings(validate_qvf(path))


def test_append_then_validate(tmp_path):
    path = _water().write(str(tmp_path / "a.qvf"))
    before = open(path, "rb").read()

    w = QvfWriter.open_for_update(path)
    w.add_spectrum("spectra.ir", frequencies=[1595.0, 3657.0],
                   intensities=[67.0, 3.0], section_id="ir")
    with pytest.raises(ValueError, match="duplicate"):
        w.add_spectrum("spectra.ir", frequencies=[1.0], intensities=[1.0],
                       section_id="ir")
    preview = w.to_bytes()
    assert open(path, "rb").read() == before, "to_bytes() must not touch the file"
    (tmp_path / "preview.qvf").write_bytes(preview)
    report = validate_qvf(str(tmp_path / "preview.qvf"))
    assert report["ok"] and _orphans(report) == 1
    assert w.write() == path

    after = open(path, "rb").read()
    with zipfile.ZipFile(io.BytesIO(before)) as zf:
        old_directory = zf.start_dir
    assert after[:old_directory] == before[:old_directory], "old entries untouched"
    report = validate_qvf(path)
    assert report["ok"], report["findings"]
    assert _orphans(report) == 1, "the superseded manifest is an orphan"
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        last = zf.infolist()[-1]
    assert names.count("manifest.json") == 2
    assert [n for n in names if names.count(n) > 1] == ["manifest.json"] * 2
    assert last.filename == "manifest.json" and last.compress_type == zipfile.ZIP_STORED
    with QvfReader(path) as r:
        ids = [s["id"] for s in r.sections]
        assert ids == ["structure", "atom_properties", "ir"]
        assert r.manifest["source"]["calculation"] == "water"
        meta = r.manifest["metadata"]
        assert meta["title"] == "update test" and meta["x_note"] == "kept"
        assert len(meta["modified_utc"]) == 20 and meta["modified_utc"].endswith("Z")
        charges = r.read_array(r.sections[1]["members"]["mulliken_charge"])
        assert np.allclose(charges, [-0.70, 0.35, 0.35])
        spectrum = r.read_json(r.sections[2]["members"]["spectrum"])
        assert spectrum["frequencies"] == [1595.0, 3657.0]

    # A second update through the same writer appends again.
    w.add_vendor_section("x_upd.note", json_members={"note": {"step": 2}})
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"] and _orphans(report) == 2
    with QvfReader(path) as r:
        assert [s["id"] for s in r.sections][-1] == "x_upd_note"

    # An explicit modified_utc is kept.
    w2 = QvfWriter.open_for_update(path)
    w2.set_metadata(modified_utc="2026-01-02T03:04:05Z")
    w2.write()
    with QvfReader(path) as r:
        assert r.manifest["metadata"]["modified_utc"] == "2026-01-02T03:04:05Z"


def test_update_never_reuses_an_entry_name(tmp_path):
    path = _water().write(str(tmp_path / "n.qvf"))
    with zipfile.ZipFile(path) as zf:
        before = {i.filename: zf.read(i) for i in zf.infolist()}
    w = QvfWriter.open_for_update(path)
    # atom_properties members live at fixed paths that already exist, so the
    # new members get fresh names and the existing entries stay as they are.
    w.add_atom_properties(mulliken_charge=[0.0, 0.0, 0.0], section_id="other")
    w.write()
    with zipfile.ZipFile(path) as zf:
        names = [i.filename for i in zf.infolist()]
        assert names.count("manifest.json") == 2
        assert len(set(names)) == len(names) - 1
        for name, data in before.items():
            if name != "manifest.json":
                assert zf.read(name) == data
    other = [s for s in QvfReader(path).sections if s["id"] == "other"][0]
    assert other["members"]["mulliken_charge"]["path"] not in before
    report = validate_qvf(path)
    assert report["ok"], report["findings"]


def test_orphan_warning_then_repack(tmp_path):
    path = _water().write(str(tmp_path / "o.qvf"))
    w = QvfWriter.open_for_update(path)
    w.add_spectrum("spectra.ir", frequencies=[1595.0], intensities=[67.0],
                   section_id="ir")
    w.write()
    # An entry no member references, e.g. a member a later update replaced.
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("stale/old.bin", b"\x07" * 5000)
    report = validate_qvf(path)
    assert report["ok"]
    assert _orphans(report) == 2      # the stale entry and the superseded manifest

    out = repack(path, str(tmp_path / "packed.qvf"))
    report = validate_qvf(out)
    assert _no_findings(report), report["findings"]
    assert os.path.getsize(out) < os.path.getsize(path)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "stale/old.bin" not in names and names.count("manifest.json") == 1
        assert zf.infolist()[-1].filename == "manifest.json"
        assert zf.infolist()[-1].compress_type == zipfile.ZIP_STORED
    with QvfReader(out) as r:
        assert r.read_json(r.sections[2]["members"]["spectrum"])["frequencies"] == [1595.0]

    # In place.
    repack(path, path)
    assert _no_findings(validate_qvf(path))


def test_update_refusals(tmp_path):
    path = _water().write(str(tmp_path / "r.qvf"))
    w = QvfWriter.open_for_update(path)
    with pytest.raises(ValueError, match="updates"):
        w.write(str(tmp_path / "elsewhere.qvf"))
    with pytest.raises(TypeError):
        _water().write()
    dup = tmp_path / "dup.qvf"
    with zipfile.ZipFile(dup, "w") as zf, pytest.warns(UserWarning):
        zf.writestr("manifest.json", b'{"qvf_version": 1}')
        zf.writestr("a.json", b"{}")
        zf.writestr("a.json", b"{}")
    with pytest.raises(ValueError, match="E_ZIP_DUPLICATE_ENTRY"):
        QvfWriter.open_for_update(str(dup))
    v3 = tmp_path / "v3.qvf"
    with zipfile.ZipFile(v3, "w") as zf:
        zf.writestr("manifest.json", b'{"qvf_version": 3, "source": {}, "sections": []}')
    with pytest.raises(ValueError, match="qvf_version 1"):
        QvfWriter.open_for_update(str(v3))


@pytest.mark.skipif(not os.path.isdir(CORPUS), reason="conformance corpus not present")
@pytest.mark.parametrize("name", ["zip64.qvf", "data_descriptor.qvf", "updated_in_place.qvf"])
def test_update_exotic_containers(tmp_path, name):
    """Appending works on ZIP64, data-descriptor and already updated archives."""
    source = os.path.join(CORPUS, name)
    if not os.path.exists(source):
        pytest.skip(f"{name} not in this corpus")
    path = str(tmp_path / name)
    shutil.copyfile(source, path)
    orphans_before = _orphans(validate_qvf(path))
    w = QvfWriter.open_for_update(path)
    w.add_vendor_section("x_upd.note", json_members={"note": {"container": name}})
    w.write()
    report = validate_qvf(path)
    assert report["ok"], report["findings"]
    assert _orphans(report) == orphans_before + 1
    repack(path, path)
    assert _no_findings(validate_qvf(path))


def _local_zip64_extras(data):
    """For each local header, whether its extra field has a ZIP64 (0x0001) block."""
    out = []
    pos = 0
    while True:
        pos = data.find(b"PK\x03\x04", pos)
        if pos < 0:
            return out
        name_len, extra_len = struct.unpack_from("<HH", data, pos + 26)
        extra = data[pos + 30 + name_len:pos + 30 + name_len + extra_len]
        found, q = False, 0
        while q + 4 <= len(extra):
            ident, size = struct.unpack_from("<HH", extra, q)
            found = found or ident == 1
            q += 4 + size
        out.append(found)
        pos += 4


def test_force_zip64_python(tmp_path):
    w = _water()
    data = w.to_bytes(force_zip64=True)
    flags = _local_zip64_extras(data)
    assert flags and all(flags), "every local header carries a ZIP64 extra field"
    path = tmp_path / "z64.qvf"
    path.write_bytes(data)
    assert _no_findings(validate_qvf(str(path)))
    w.write(str(tmp_path / "z64_file.qvf"), force_zip64=True)
    assert all(_local_zip64_extras((tmp_path / "z64_file.qvf").read_bytes()))


def _read_qvf_binary():
    env = os.environ.get("QVF_READ_QVF")
    if env:
        return env if os.path.isfile(env) else None
    patterns = ["build*/read_qvf", "build*/Release/read_qvf.exe", "build*/read_qvf.exe",
                "cpp/build*/read_qvf", "cpp/build*/Release/read_qvf.exe"]
    for pattern in patterns:
        for candidate in sorted(glob.glob(os.path.join(ROOT, pattern))):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


@pytest.mark.skipif(_read_qvf_binary() is None,
                    reason="no C++ read_qvf build found (set QVF_READ_QVF)")
def test_cpp_reader_reads_python_zip64_and_updates(tmp_path):
    """Cross-language: the C++ reader opens what the Python writer forced to
    ZIP64, and an archive the Python writer updated in place."""
    binary = _read_qvf_binary()
    forced = tmp_path / "py_zip64.qvf"
    forced.write_bytes(_water().to_bytes(force_zip64=True))
    updated = _water().write(str(tmp_path / "py_update.qvf"))
    w = QvfWriter.open_for_update(updated)
    w.add_spectrum("spectra.ir", frequencies=[1595.0], intensities=[67.0],
                   section_id="ir")
    w.write()
    for archive in (str(forced), updated):
        result = subprocess.run([binary, archive], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout
    result = subprocess.run([binary, updated], capture_output=True, text=True)
    assert "W_ORPHAN_MEMBER" in result.stdout and "ir" in result.stdout
