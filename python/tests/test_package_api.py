"""Public package API: streaming, lazy reads, bounded edits and compatibility."""
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

import pytest

from qvf import Editor, GridSpec, Lattice, Limits, Manifest, Reader, Section, Writer
from qvf import validate
from qvf.kinds import Structure, Volume


def write_raw(target, *, compression=zipfile.ZIP_DEFLATED):
    with Writer(target, program="example", version="1", auto_metadata=False,
                compression=compression) as writer:
        writer.add_section(Section(id="rho", kind="volume.density", members={}))
        writer.add_json("rho", "grid", {"origin": [0, 0, 0], "voxel_vectors":
                        [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "shape": [1, 2, 2]})
        with writer.begin_binary("rho", "data", "float64", [1, 2, 2]) as sink:
            sink.write(struct.pack("<2d", 1, 2))
            sink.write(struct.pack("<2d", 3, 4))
    return target


def test_members_stream_before_finish_and_manifest_last():
    target = io.BytesIO()
    writer = Writer(target, program="example", version="1", auto_metadata=False)
    start = target.tell()
    writer.add_section(Section(id="raw", kind="x_demo.tensor", members={}))
    writer.add_binary("raw", "data", struct.pack("<2d", 2, 3), "float64", [2])
    assert target.tell() > start
    assert all(value is None for value in writer._files.values())
    assert [i.filename for i in writer._zip.infolist()] == ["raw/data.bin"]
    writer.finish()
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["raw/data.bin", "manifest.json"]
        assert archive.getinfo("manifest.json").compress_type == zipfile.ZIP_STORED


def test_typed_reader_numpy_and_memoryview():
    target = write_raw(io.BytesIO())
    with Reader.from_bytes(target.getvalue()) as reader:
        assert isinstance(reader.manifest, Manifest)
        assert reader.manifest.to_json() == reader.raw_manifest
        assert reader.section("rho") == reader.sections_of("volume.density")[0]
        tensor = reader.tensor("rho", "data")
        assert tensor.data.readonly and isinstance(tensor.data, memoryview)
        assert tensor.shape == (1, 2, 2) and tensor.dtype == "float64"
        assert tensor.tolist() == [[[1, 2], [3, 4]]]
        assert tensor.numpy().tolist() == tensor.tolist()
        assert isinstance(reader.get("rho"), Volume)
        chunks = []
        assert reader.tensor_into("rho", "data", chunks.append, chunk_size=3) == 32
        assert max(map(len, chunks)) == 3
        assert b"".join(chunks) == tensor.data
        assert validate.run(reader) == reader.validate()
        assert reader.validate()["ok"]


def test_reader_loads_only_manifest_until_requested(monkeypatch):
    target = write_raw(io.BytesIO())
    reads = []
    original = zipfile.ZipFile.open
    def tracked(self, member, *args, **kwargs):
        reads.append(member.filename if isinstance(member, zipfile.ZipInfo) else member)
        return original(self, member, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, "open", tracked)
    with Reader.from_bytes(target.getvalue()) as reader:
        assert reads == ["manifest.json"]
        reader.get("rho")
        assert reads == ["manifest.json"]
        reader.json("rho", "grid")
        assert reads == ["manifest.json", "rho/grid.json"]


def test_raw_package_path_runs_without_numpy_or_jsonschema(tmp_path):
    script = '''import builtins, io, struct, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in ('numpy', 'jsonschema'):
        raise ImportError('optional dependency blocked by test')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from qvf import Writer, Reader, Section, Lattice, Editor
from qvf import units
assert 'numpy' not in sys.modules
out = io.BytesIO()
with Writer(out, program='example', version='1', auto_metadata=False) as writer:
    writer.add_section(Section(id='raw', kind='x_demo.raw', members={}))
    writer.add_binary('raw', 'values', struct.pack('<d', 2.0), 'float64', [1])
with Reader.from_bytes(out.getvalue()) as reader:
    assert reader.tensor('raw', 'values').tolist() == [2.0]
    assert reader.validate()['ok']
import pathlib, tempfile
with tempfile.TemporaryDirectory() as scratch:
    path = pathlib.Path(scratch) / 'raw.qvf'
    path.write_bytes(out.getvalue())
    with Editor(path, atomic=True) as editor:
        editor.set_run_status('running')
    Editor.repack(path, path)
    with Reader(path) as reader:
        assert reader.validate()['ok']
        assert reader.raw_manifest['provenance']['run_status'] == 'running'
assert units.convert(1.0, 'angstrom', 'bohr') > 1
assert Lattice.from_rows_angstrom([[1,0,0],[0,2,0],[0,0,3]]).volume_angstrom3() == 6
assert 'numpy' not in sys.modules
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, "-S", "-c", script], env=env,
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_compatibility_module_identity_and_cli(tmp_path, monkeypatch):
    import qvf_reader
    import qvf_writer
    import qvf.validate
    import qvf._legacy_writer
    assert qvf_reader is qvf.validate
    assert qvf_writer is qvf._legacy_writer
    sentinel = object()
    monkeypatch.setattr(qvf_reader, "_load_schema_validator", lambda: sentinel)
    assert qvf.validate._load_schema_validator() is sentinel
    monkeypatch.undo()
    path = write_raw(tmp_path / "sample.qvf")
    script = Path(__file__).resolve().parents[1] / "qvf_reader.py"
    result = subprocess.run([sys.executable, str(script), "--json", str(path)],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"]


def test_deprecation_warnings():
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, "-Walways::DeprecationWarning", "-c",
                             "import qvf_reader, qvf_writer"], env=env, text=True,
                            capture_output=True)
    assert result.returncode == 0
    assert "qvf_reader is deprecated" in result.stderr
    assert "qvf_writer is deprecated" in result.stderr


@pytest.mark.parametrize("shape, values", [((), [2]), ((0, 3), []), ((2,), [2, 3])])
def test_big_endian_partial_elements_and_empty_shape(shape, values):
    out = io.BytesIO()
    with Writer(out, program="example", version="1", auto_metadata=False) as writer:
        writer.add_section(Section(id="raw", kind="x_demo.tensor", members={}))
        raw = struct.pack(">" + "d" * len(values), *values)
        with writer.begin_binary("raw", "data", "float64", shape, byte_order="big") as sink:
            for offset in range(0, len(raw), 3):
                sink.write(raw[offset:offset + 3])
    with Reader.from_bytes(out.getvalue()) as reader:
        tensor = reader.tensor("raw", "data")
        assert tensor.data == struct.pack("<" + "d" * len(values), *values)
        assert tensor.tolist() == (2 if shape == () else [] if shape == (0, 3) else [2, 3])


@pytest.mark.parametrize("data", [b"x", b"x" * 9])
def test_sink_size_failure_prevents_manifest(data):
    out = io.BytesIO()
    writer = Writer(out, program="example", version="1", auto_metadata=False)
    writer.add_section(Section(id="raw", kind="x_demo.tensor", members={}))
    with pytest.raises(ValueError, match="E_BINARY_SIZE"):
        with writer.begin_binary("raw", "data", "float64", [1]) as sink:
            sink.write(data)
    with pytest.raises(ValueError, match="failed"):
        writer.finish()
    writer.abort()
    with zipfile.ZipFile(out) as archive:
        assert "manifest.json" not in archive.namelist()


def test_role_and_shape_rejected_before_writing():
    out = io.BytesIO()
    with Writer(out, program="example", version="1", auto_metadata=False) as writer:
        writer.add_section(Section(id="rho", kind="volume.density", members={}))
        before = out.tell()
        for role, dtype, shape in [("absent", "float64", [1,1,1]),
                                   ("data", "int32", [1,1,1]),
                                   ("data", "float64", [1])]:
            with pytest.raises(ValueError):
                writer.begin_binary("rho", role, dtype, shape)
            assert out.tell() == before
        with pytest.raises(ValueError):
            writer.add_section(Section(id="rho", kind="volume.density", members={}))
        assert out.tell() == before


def test_nonseekable_and_zip64():
    class Sink:
        def __init__(self): self.data = bytearray()
        def write(self, data): self.data.extend(data); return len(data)
        def flush(self): pass
    sink = Sink()
    with Writer(sink, program="example", version="1", auto_metadata=False,
                force_zip64=True) as writer:
        writer.add_section(Section(id="raw", kind="x_demo.tensor", members={}))
        writer.add_binary("raw", "data", struct.pack("<d", 4), "float64", [1])
    with zipfile.ZipFile(io.BytesIO(sink.data)) as archive:
        assert archive.getinfo("raw/data.bin").flag_bits & 8
    with Reader.from_bytes(sink.data) as reader:
        assert reader.tensor("raw", "data").tolist() == [4]


def test_streaming_and_legacy_member_bytes_equal():
    import numpy as np
    from qvf_writer import QvfWriter
    legacy = QvfWriter("example", "1", auto_metadata=False)
    out = io.BytesIO()
    with Writer(out, program="example", version="1", auto_metadata=False) as streaming:
        for writer in (legacy, streaming):
            writer.add_structure([{"symbol": "H", "position": [0, 0, 0]}])
            writer.add_density(np.arange(8).reshape(2,2,2), [0,0,0],
                               [[1,0,0],[0,1,0],[0,0,1]], section_id="rho")
    with zipfile.ZipFile(io.BytesIO(legacy.to_bytes())) as left, zipfile.ZipFile(out) as right:
        assert left.namelist() == right.namelist()
        for name in left.namelist():
            assert left.read(name) == right.read(name)
    with Reader.from_bytes(out.getvalue()) as reader:
        assert isinstance(reader.get("structure", Structure), Structure)
        assert reader.get("structure").atoms[0]["symbol"] == "H"


def test_reader_caps_precede_decompression(monkeypatch):
    out = write_raw(io.BytesIO())
    def forbidden(*args, **kwargs):
        raise AssertionError("payload decompression before caps")
    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden)
    with pytest.raises(ValueError, match="E_TOTAL_TOO_LARGE"):
        Reader.from_bytes(out.getvalue(), limits=Limits(max_total_bytes=1))


def test_reader_checksum_and_binary_shape():
    original = write_raw(io.BytesIO())
    for mutation, code in [(lambda m: m.update(sha256="0" * 64), "E_SHA256_MISMATCH"),
                            (lambda m: m.update(shape=[1,1,1]), "E_BINARY_SIZE")]:
        out = io.BytesIO()
        with zipfile.ZipFile(original) as zin, zipfile.ZipFile(out, "w") as zout:
            for info in zin.infolist():
                raw = zin.read(info)
                if info.filename == "manifest.json":
                    manifest = json.loads(raw)
                    mutation(manifest["sections"][0]["members"]["data"])
                    raw = json.dumps(manifest).encode()
                zout.writestr(info, raw)
        with Reader.from_bytes(out.getvalue()) as reader:
            with pytest.raises(ValueError, match=code):
                reader.tensor("rho", "data")


def test_editor_append_remove_repack_and_atomic_abort(tmp_path):
    path = write_raw(tmp_path / "edit.qvf")
    baseline = path.read_bytes()
    with pytest.raises(RuntimeError):
        with Editor(path, atomic=True) as editor:
            editor.remove_section("rho")
            raise RuntimeError("cancel")
    assert path.read_bytes() == baseline
    with Editor(path) as editor:
        editor.remove_section("rho")
        editor.writer.add_section(Section(id="raw", kind="x_demo.tensor", members={}))
        editor.writer.add_binary("raw", "data", struct.pack("<d", 9), "float64", [1])
        editor.set_run_status("running")
    report = validate.run(path)
    assert report["ok"] and any(f["code"] == "W_ORPHAN_MEMBER" for f in report["findings"])
    with Reader(path) as reader:
        assert reader.raw_manifest["provenance"]["run_status"] == "running"
        assert "modified_utc" in reader.raw_manifest["metadata"]
    Editor.repack(path, path, compression=zipfile.ZIP_STORED)
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["raw/data.bin", "manifest.json"]
    assert validate.run(path)["ok"]
    assert not list(tmp_path.glob(".qvf-*"))


def test_editor_replacement_uses_fresh_names(tmp_path):
    path = write_raw(tmp_path / "replace.qvf")
    with Editor(path, atomic=True) as editor:
        editor.remove_section("rho")
        editor.writer.add_section(Section(id="rho", kind="volume.density", members={}))
        editor.writer.add_json("rho", "grid", {"origin": [0,0,0], "shape": [1,1,1],
                              "voxel_vectors": [[1,0,0],[0,1,0],[0,0,1]]})
        editor.writer.add_binary("rho", "data", struct.pack("<d", 8), "float64", [1,1,1])
    with Reader(path) as reader:
        assert reader.section("rho").member("data").path == "rho/data.2.bin"
        assert reader.tensor("rho", "data").tolist() == [[[8]]]
        assert reader.validate()["ok"]


def test_editor_preserves_job_spec(tmp_path):
    path = tmp_path / "job.qvf"
    with Writer(path, program="example", version="1", auto_metadata=False) as writer:
        writer.add_structure([{"symbol": "H", "position": [0,0,0]}])
        writer.add_job_spec(job_type="molecular", section_id="job")
    with Reader(path) as reader:
        section = reader.section("job").to_json()
        job = reader.json("job", "spec")
    with Editor(path) as editor:
        with pytest.raises(ValueError, match="preserve"):
            editor.remove_section("job")
        editor.set_run_status("running")
    with Reader(path) as reader:
        assert reader.section("job").to_json() == section
        assert reader.json("job", "spec") == job


def test_copy_lazy_kind_to_streaming_writer():
    original = write_raw(io.BytesIO())
    out = io.BytesIO()
    with Reader.from_bytes(original.getvalue()) as reader:
        with Writer(out, program="example", version="1", auto_metadata=False) as writer:
            writer.add(reader.get("rho"))
    with Reader.from_bytes(out.getvalue()) as reader:
        assert reader.tensor("rho", "data").tolist() == [[[1,2],[3,4]]]
        assert reader.validate()["ok"]


def test_model_geometry_and_package_schema():
    lattice = Lattice.from_rows_angstrom([[1,2,0],[0,3,0],[0,0,4]])
    restored = Lattice.from_columns_bohr(lattice.columns_bohr())
    for left, right in zip(lattice.rows_angstrom(), restored.rows_angstrom()):
        assert left == pytest.approx(right)
    assert lattice.volume_angstrom3() == 12
    grid = GridSpec((0,0,0), ((1,0,0),(0,1,0),(0,0,1)), (1,2,3))
    assert grid.to_json()["shape"] == [1,2,3]
    package_schema = Path(validate._find_schema())
    assert package_schema.is_file()
    assert package_schema.read_bytes() == (Path(__file__).resolve().parents[1] /
                                          "qvf_manifest.schema.json").read_bytes()


def test_package_lattice_works_with_writer():
    target = io.BytesIO()
    cell = Lattice.from_rows_angstrom([[2,0,0],[0,2,0],[0,0,2]])
    with Writer(target, program="example", version="1", auto_metadata=False) as writer:
        writer.add_structure([{"symbol": "H", "position": [0,0,0]}],
                             pbc=[True,True,True], lattice_vectors=cell)
    with Reader.from_bytes(target.getvalue()) as reader:
        assert reader.get("structure").lattice.rows_angstrom() == cell.rows_angstrom()
        assert reader.validate()["ok"]
