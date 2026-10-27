"""A geometry and its drawing survive explicit preparation for one QC job."""
import builtins
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from qvf import Reader, Writer
from qvf.cli import main
from qvf.jobs import prepare_job
from test_reference_writer import _tiny_png


OPTIONS = dict(job_type="molecular", method="rhf", task="single_point")


def drawing(path, *, identity=None, pbc=None, extra=False, result=None):
    with Writer(path, "example", "1") as writer:
        writer.add_section({"id": "molecule", "kind": "structure", **(identity or {})})
        writer.add_json("molecule", "structure", {
            "atoms": [{"symbol": "H", "atomic_number": 1, "position": [0., 0., z]}
                      for z in (0., .74)],
            "pbc": pbc or [False] * 3,
            "lattice_vectors": [[4., 0., 0.], [0., 4., 0.], [0., 0., 4.]] if pbc else None})
        writer.add_bonds([{"i": 0, "j": 1, "order": 1.0}], structure_ref="molecule")
        writer.add_preview(_tiny_png(), image="<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'/>")
        writer.add_section({"id": "drawing", "kind": "x_example.document"})
        writer.add_json("drawing", "document", {"label": "H2", "color": "blue"})
        writer.add_opaque("drawing", "opaque", b"\xff\x00unchanged drawing bytes", media_type="application/octet-stream")
        if extra:
            writer.add_section({"id": "other", "kind": "structure"})
            writer.add_json("other", "structure", {"atoms": [], "pbc": [False] * 3})
        if result == "run":
            writer.add_run_record(program="example", log_text="complete")
        elif result == "energy":
            writer.set_provenance(scf_energy_eh=-1.0)
    return path


def rewrite(source, destination, change):
    with zipfile.ZipFile(source) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files["manifest.json"])
    change(manifest, files)
    files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(destination, "w") as output:
        for name, data in files.items():
            output.writestr(name, data)
    return destination


def spec(path):
    with Reader(path) as reader:
        return reader.json(reader.sections_of("job.spec")[0], "spec")


def test_preparation_preserves_drawing_sections_bytes_and_source(tmp_path):
    source = drawing(tmp_path / "drawing.qvf", identity={"charge": 0, "multiplicity": 1})
    before = source.read_bytes()
    output = tmp_path / "pending.qvf"
    report = prepare_job(source, output, basis="sto-3g", functional=None, **OPTIONS)
    assert report["findings"] == []
    assert source.read_bytes() == before
    with Reader(source) as original, Reader(output) as pending:
        assert pending.validate()["ok"]
        assert pending.raw_manifest["sections"][:-1] == original.raw_manifest["sections"]
        assert pending.raw_manifest["source"] == original.raw_manifest["source"]
        assert pending.raw_manifest["provenance"] == {"run_status": "pending", "charge": 0, "multiplicity": 1}
        assert pending.raw_manifest["metadata"]["uuid"] != original.raw_manifest["metadata"]["uuid"]
        assert original.raw_manifest["metadata"]["uuid"] in pending.raw_manifest["metadata"]["derived_from"]
        for section in original.sections:
            for member in section.members.values():
                raw = pending.read_member(member)
                assert raw == original.read_member(member)
                assert hashlib.sha256(raw).hexdigest() == member.sha256
    assert spec(output) == {"job_type": "molecular", "method": "rhf", "basis": "sto-3g",
                            "functional": None, "charge": 0, "multiplicity": 1,
                            "tasks": ["single_point"], "structure_ref": "molecule"}


@pytest.mark.parametrize("changes,match", [
    ({"method": ""}, "method"), ({"method": 5}, "method"),
    ({"method": " rhf"}, "method"), ({"method": "rhf\n"}, "method"),
    ({"basis": ""}, "basis"), ({"functional": False}, "functional"),
    ({"task": "frequency"}, "task"), ({"charge": True}, "charge"),
    ({"multiplicity": 0}, "multiplicity"), ({"multiplicity": 2}, "multiplicity"),
    ({"charge": 3}, "electrons"), ({"kpoints": [1, 1, 1]}, "kpoints"),
    ({"job_type": "periodic"}, "periodicity"), ({"job_type": "guess"}, "job_type"),
    ({"options": {"unknown": True}}, "options"),
])
def test_invalid_options_never_publish(tmp_path, changes, match):
    source = drawing(tmp_path / "source.qvf")
    with pytest.raises((ValueError, TypeError), match=match):
        prepare_job(source, tmp_path / "out.qvf", **(OPTIONS | changes))
    assert not (tmp_path / "out.qvf").exists()
    assert not list(tmp_path.glob(".qvf-output-*"))


def test_identity_is_not_inferred(tmp_path):
    source = drawing(tmp_path / "source.qvf", identity={"charge": 1, "multiplicity": 2})
    with pytest.raises(ValueError, match="conflicts"):
        prepare_job(source, tmp_path / "bad.qvf", **OPTIONS)
    prepare_job(source, tmp_path / "ion.qvf", charge=1, multiplicity=2, **OPTIONS)
    assert spec(tmp_path / "ion.qvf")["charge"] == 1
    assert not (tmp_path / "bad.qvf").exists()


def test_periodic_request_and_mesh(tmp_path):
    source = drawing(tmp_path / "cell.qvf", pbc=[True, True, True])
    prepare_job(source, tmp_path / "job.qvf", job_type="periodic", method="rks",
                task="optimize", kpoints=[2, 2, 2], functional="pbe")
    assert spec(tmp_path / "job.qvf")["kpoints"] == [2, 2, 2]


def test_legacy_input_is_preserved_but_new_job_writes_v1(tmp_path):
    source = drawing(tmp_path / "source.qvf")
    legacy = rewrite(source, tmp_path / "legacy.qvf", lambda m, f: m.update(qvf_version=2))
    original = legacy.read_bytes()
    result = prepare_job(legacy, tmp_path / "job.qvf", **OPTIONS)
    assert legacy.read_bytes() == original
    assert result["source_findings"]
    assert not result["findings"]
    with Reader(tmp_path / "job.qvf") as reader:
        assert reader.raw_manifest["qvf_version"] == 1


def test_multiple_structures_and_existing_job_are_refused(tmp_path):
    source = drawing(tmp_path / "many.qvf", extra=True)
    with pytest.raises(ValueError, match="exactly one"):
        prepare_job(source, tmp_path / "bad.qvf", **OPTIONS)
    source = drawing(tmp_path / "one.qvf")
    prepare_job(source, tmp_path / "job.qvf", **OPTIONS)
    with pytest.raises(ValueError, match="existing jobs"):
        prepare_job(tmp_path / "job.qvf", tmp_path / "bad.qvf", **OPTIONS)
    assert not (tmp_path / "bad.qvf").exists()


@pytest.mark.parametrize("change,match", [
    (lambda m, f: m.update(provenance={"run_status": "failed"}), "lifecycle"),
    (lambda m, f: m.update(provenance={"method": "rhf"}), "calculation"),
    (lambda m, f: f.update({"molecule/structure.json": b"{}"}), "validation"),
    (lambda m, f: m.update(byte_order="big"), "E_SCHEMA"),
    (lambda m, f: m["sections"][0].update(charge="0"), "validation"),
])
def test_corrupt_or_calculated_source_is_refused(tmp_path, change, match):
    source = drawing(tmp_path / "good.qvf")
    bad = rewrite(source, tmp_path / "bad.qvf", change)
    with pytest.raises(ValueError, match=match):
        prepare_job(bad, tmp_path / "out.qvf", **OPTIONS)
    assert not (tmp_path / "out.qvf").exists()


@pytest.mark.parametrize("result", ["run", "energy"])
def test_result_archive_is_refused_without_silent_loss(tmp_path, result):
    source = drawing(tmp_path / "source.qvf", result=result)
    with Reader(source) as reader:
        assert reader.validate()["ok"]
    with pytest.raises(ValueError, match="refuses"):
        prepare_job(source, tmp_path / "out.qvf", **OPTIONS)
    assert not (tmp_path / "out.qvf").exists()


def test_collision_orphans_and_destination_protection(tmp_path):
    source = drawing(tmp_path / "source.qvf")
    source = rewrite(source, tmp_path / "orphan.qvf", lambda m, f: f.update({"job/spec.json": b"retained orphan"}))
    output = tmp_path / "output.qvf"
    report = prepare_job(source, output, **OPTIONS)
    assert report["job_ref"] == "job_1"
    with zipfile.ZipFile(output) as archive:
        assert archive.read("job/spec.json") == b"retained orphan"
    original = source.read_bytes()
    for destination in (source, output):
        with pytest.raises(FileExistsError):
            prepare_job(source, destination, **OPTIONS)
    link = tmp_path / "link.qvf"
    link.symlink_to(tmp_path / "absent.qvf")
    with pytest.raises(FileExistsError):
        prepare_job(source, link, **OPTIONS)
    assert source.read_bytes() == original


def test_final_validation_failure_is_atomic(tmp_path, monkeypatch):
    source = drawing(tmp_path / "source.qvf")
    from qvf import jobs
    original = jobs._validated
    def fail_output(reader, label):
        if label == "prepared job":
            raise ValueError("injected final validation failure")
        return original(reader, label)
    monkeypatch.setattr(jobs, "_validated", fail_output)
    with pytest.raises(ValueError, match="final validation"):
        prepare_job(source, tmp_path / "out.qvf", **OPTIONS)
    assert not (tmp_path / "out.qvf").exists()
    assert not list(tmp_path.glob(".qvf-output-*"))


def test_concurrent_destination_is_not_replaced(tmp_path, monkeypatch):
    source = drawing(tmp_path / "source.qvf")
    output = tmp_path / "out.qvf"
    link = os.link
    def claim_destination(temporary, destination):
        Path(destination).write_bytes(b"concurrent owner")
        link(temporary, destination)
    monkeypatch.setattr(os, "link", claim_destination)
    with pytest.raises(FileExistsError):
        prepare_job(source, output, **OPTIONS)
    assert output.read_bytes() == b"concurrent owner"
    assert not list(tmp_path.glob(".qvf-output-*"))


def test_no_numpy_and_missing_schema_engine(tmp_path, monkeypatch):
    source = drawing(tmp_path / "source.qvf")
    original = builtins.__import__
    def no_numpy(name, *args, **kwargs):
        if name == "numpy" or name.startswith("numpy."):
            raise ImportError("NumPy deliberately unavailable")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_numpy)
    prepare_job(source, tmp_path / "out.qvf", **OPTIONS)
    from qvf import validate
    monkeypatch.setattr(validate, "_load_schema_validator", lambda: None)
    with pytest.raises(RuntimeError, match="qvf-writer\\[validate\\]"):
        prepare_job(source, tmp_path / "no-schema.qvf", **OPTIONS)
    assert not (tmp_path / "no-schema.qvf").exists()


def test_import_and_preparation_in_fresh_process_without_numpy(tmp_path):
    source = drawing(tmp_path / "source.qvf")
    script = '''
import builtins, sys
original = builtins.__import__
def no_numpy(name, *args, **kwargs):
    if name == "numpy" or name.startswith("numpy."):
        raise ImportError("NumPy deliberately unavailable")
    return original(name, *args, **kwargs)
builtins.__import__ = no_numpy
from qvf.jobs import prepare_job
prepare_job(sys.argv[1], sys.argv[2], job_type="molecular", method="rhf", task="single_point")
assert "numpy" not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", script, str(source), str(tmp_path / "out.qvf")],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("flags,fields", [([], {}), (["--no-basis", "--no-functional"], {"basis": None, "functional": None}),
    (["--basis", "sto-3g", "--functional", "pbe"], {"basis": "sto-3g", "functional": "pbe"})])
def test_cli_preserves_omission_and_explicit_null(tmp_path, flags, fields, capsys):
    source = drawing(tmp_path / "source.qvf")
    output = tmp_path / "job.qvf"
    arguments = ["prepare-job", str(source), "-o", str(output), "--job-type", "molecular",
                 "--method", "rhf", "--task", "hessian"]
    assert main(arguments + flags) == 0
    assert json.loads(capsys.readouterr().out)["output"] == str(output)
    actual = spec(output)
    assert {key: actual[key] for key in ("basis", "functional") if key in actual} == fields
    with pytest.raises(SystemExit) as error:
        main(arguments + ["--basis", "sto-3g", "--no-basis"])
    assert error.value.code == 2
