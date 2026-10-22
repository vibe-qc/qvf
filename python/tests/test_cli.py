"""CLI acceptance: real stage boundaries, useful commands and safe outputs."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

import pytest

from qvf import Reader, Section, Writer, validate
from qvf.cli import main
from qvf import operations


ROOT = Path(__file__).resolve().parents[1]


def archive(path, values=(1.0, 2.0), *, dtype="float64", run=False):
    with Writer(path, program="example", version="1", auto_metadata=False) as writer:
        writer.add_section(Section(id="data", kind="x_example.numeric", members={}))
        writer.add_json("data", "description", {"label": "example", "value": 1.0})
        writer.add_binary("data", "values", struct.pack("<2d" if dtype == "float64" else "<2q", *values), dtype, [2])
        if run:
            writer.set_provenance(allow_hostname=True, hostname="compute.example")
            writer.set_metadata(uuid="00000000-0000-4000-8000-000000000001",
                                authors=[{"name": "Example", "email": "person@example.org", "affiliation": "Example lab"}])
            writer.add_job_spec(job_type="molecular", method="HF", basis="sto-3g")
            writer.add_run_record(program="example", job_ref="job_spec", input_text="owner=demo path=/scratch/demo/input",
                                  log_text="owner=demo", command="run /scratch/demo/input",
                                  attachments={"text": b"owner=demo", "binary": b"\xff\x00"},
                                  files={"input": {"filename": "/scratch/demo/input"}})
    return path


def rewrite(source, output, change):
    with zipfile.ZipFile(source) as reader:
        files = {name: reader.read(name) for name in reader.namelist()}
    manifest = json.loads(files["manifest.json"])
    change(manifest, files)
    files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(output, "w") as writer:
        for name, data in files.items():
            writer.writestr(name, data)
    return output


def test_levels_do_not_read_later_payloads(tmp_path, monkeypatch):
    source = archive(tmp_path / "input.qvf")
    reads = []
    original = zipfile.ZipFile.open
    def tracked(self, member, *args, **kwargs):
        reads.append(member.filename if isinstance(member, zipfile.ZipInfo) else member)
        return original(self, member, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, "open", tracked)
    assert validate.run(source, level="container")["ok"]
    assert reads == []
    assert validate.run(source, level="manifest")["ok"]
    assert reads == ["manifest.json"]
    with Reader(source) as reader:
        reads.clear()
        assert validate.run(reader, level=validate.Level.Manifest)["ok"]
        assert reads == ["manifest.json"]
    def unexpected(*args):
        raise AssertionError("semantic rule executed too early")
    monkeypatch.setattr(validate, "_root_consistency_errors", unexpected)
    monkeypatch.setattr(validate, "_volume_errors", unexpected)
    assert validate.run(source, level="payloads")["ok"]
    with pytest.raises(AssertionError):
        validate.run(source, level="semantics")


def test_levels_expose_semantics_then_references():
    negative = ROOT.parent / "conformance" / "negative"
    semantic = negative / "bloch_weights_sum.qvf"
    assert validate.run(semantic, level="payloads")["ok"]
    assert "E_MEMBER_MALFORMED" in {f["code"] for f in validate.run(semantic, level="semantics")["findings"]}
    reference = negative / "bonds_structure_ref_unresolved.qvf"
    assert "E_REF_UNRESOLVED" not in {f["code"] for f in validate.run(reference, level="semantics")["findings"]}
    assert "E_REF_UNRESOLVED" in {f["code"] for f in validate.run(reference, level="references")["findings"]}
    assert validate.run(reference) == validate.run(reference, level="all")


def test_inspect_cat_schema_validate_and_usage(tmp_path, capsys):
    source = archive(tmp_path / "input.qvf")
    assert main(["info", str(source)]) == 0
    assert "data [x_example.numeric]" in capsys.readouterr().out
    assert main(["info", str(source), "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["sections"][0]["members"][1]["size"] == 16
    assert main(["cat", str(source), "data", "description"]) == 0
    assert json.loads(capsys.readouterr().out)["label"] == "example"
    assert main(["cat", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["qvf_version"] == 1
    assert main(["cat", str(source), "data"]) == 2
    assert "both SECTION" in capsys.readouterr().err
    assert main(["validate", str(source), "--json", "--level", "manifest"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert main(["validate", str(tmp_path / "missing"), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["findings"][0]["code"] == "E_ZIP_UNREADABLE"
    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads(Path(validate._SCHEMA_PATH).read_text())


def test_extract_and_repack_verified_new_outputs(tmp_path, capsys):
    source = archive(tmp_path / "input.qvf")
    output = tmp_path / "values.bin"
    assert main(["extract", str(source), "data", "values", "-o", str(output)]) == 0
    assert output.read_bytes() == struct.pack("<2d", 1, 2)
    assert main(["extract", str(source), "data", "values", "-o", str(output)]) == 2
    repacked = tmp_path / "repacked.qvf"
    with zipfile.ZipFile(source, "a") as writer:
        writer.writestr("orphan", b"discard me")
    assert main(["repack", str(source), "-o", str(repacked), "--compression", "store"]) == 0
    assert operations.diff(source, repacked)["equal"]
    with zipfile.ZipFile(repacked) as reader:
        assert "orphan" not in reader.namelist()
        assert all(info.compress_type == zipfile.ZIP_STORED for info in reader.infolist())
    assert main(["repack", str(repacked), "-o", str(repacked)]) == 2
    corrupt = rewrite(source, tmp_path / "corrupt.qvf", lambda m, files: files.update({"data/values.bin": b"x" * 16}))
    bad_output = tmp_path / "bad.bin"
    assert main(["extract", str(corrupt), "data", "values", "-o", str(bad_output)]) == 2
    assert "E_SHA256_MISMATCH" in capsys.readouterr().err
    assert not bad_output.exists()
    assert not list(tmp_path.glob(".qvf-*"))
    # Existing destinations, including symlinks, are always preserved.
    link = tmp_path / "linked.bin"
    link.symlink_to(output)
    assert main(["extract", str(source), "data", "values", "-o", str(link)]) == 2
    assert output.read_bytes() == struct.pack("<2d", 1, 2)


def test_diff_numeric_tolerance_large_integers_and_corruption(tmp_path, capsys):
    a = archive(tmp_path / "a.qvf")
    b = archive(tmp_path / "b.qvf", (1.00001, 2))
    assert main(["diff", str(a), str(b), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["difference_count"] == 1
    assert main(["diff", str(a), str(b), "--atol", "0.001"]) == 0
    assert main(["diff", str(a), str(b), "--rtol", "nan"]) == 2
    assert main(["diff", str(a), str(b), "--max-differences", "0"]) == 2
    c = archive(tmp_path / "c.qvf", (2**60, 2), dtype="int64")
    d = archive(tmp_path / "d.qvf", (2**60 + 1, 2), dtype="int64")
    assert not operations.diff(c, d, atol=100)["equal"]
    broken = rewrite(a, tmp_path / "broken.qvf", lambda m, files: files.update({"data/values.bin": b"x" * 16}))
    assert main(["diff", str(a), str(broken)]) == 2
    assert "E_SHA256_MISMATCH" in capsys.readouterr().err


def test_scrub_reports_and_preserves_source(tmp_path, capsys):
    source = archive(tmp_path / "input.qvf", run=True)
    with zipfile.ZipFile(source, "a") as container:
        current = container.read("manifest.json")
        container.writestr("old-log.txt", b"owner=demo")
        with pytest.warns(UserWarning, match="Duplicate name"):
            container.writestr("manifest.json", current)
    original = source.read_bytes()
    assert main(["scrub", str(source)]) == 2
    assert main(["scrub", str(source), "--dry-run", "--path-pattern", "/scratch/demo", "--user-pattern", "owner=demo"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["dry_run"] and any(item["action"] == "redact" for item in dry["changes"])
    assert any(item["reason"] == "non-UTF-8 attachment" for item in dry["skipped"])
    assert list(tmp_path.iterdir()) == [source]
    output = tmp_path / "scrubbed.qvf"
    assert main(["scrub", str(source), "-o", str(output), "--path-pattern", "/scratch/demo", "--user-pattern", "owner=demo"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert not report["dry_run"]
    assert source.read_bytes() == original
    assert validate.run(output)["ok"]
    with Reader(output) as reader:
        assert "hostname" not in reader.raw_manifest["provenance"]
        meta = reader.raw_manifest["metadata"]
        assert meta["authors"] == [{"name": "Example"}]
        assert meta["uuid"] != meta["derived_from"][-1]
        assert reader.read_member(reader._member("run_record", "input")) == b"[redacted] path=[redacted]/input"
        assert reader.json("run_record", "files")["input"]["filename"] == "[redacted]/input"
        assert reader.read_member(reader._member("run_record", "attachment.binary")) == b"\xff\x00"
        # Scrubbing creates one manifest and drops superseded/orphan content.
        assert reader._zip.namelist().count("manifest.json") == 1
        with Reader(source) as before:
            assert reader.read_member(reader._member("job_spec", "spec")) == before.read_member(before._member("job_spec", "spec"))
        assert "old-log.txt" not in reader._zip.namelist()
        for name in reader._zip.namelist():
            assert b"owner=demo" not in reader._zip.read(name)
    assert main(["scrub", str(source), "-o", str(source)]) == 2
    assert source.read_bytes() == original


def test_cli_and_corpus_without_optional_dependencies(tmp_path):
    source = archive(tmp_path / "input.qvf")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    script = '''import builtins, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in ('numpy', 'jsonschema'):
        raise ImportError('optional dependency disabled for test')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from qvf.cli import main
assert main(['diff', sys.argv[1], sys.argv[1]]) == 0
assert main(['conformance', sys.argv[2]]) == 0
assert 'numpy' not in sys.modules
'''
    result = subprocess.run([sys.executable, "-S", "-c", script, str(source), str(ROOT.parent / "conformance" / "corpus")],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    for args in (["-m", "qvf", "--version"], [str(ROOT / "qvf_reader.py"), "--json", str(source)]):
        result = subprocess.run([sys.executable, "-S", *args], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_invalid_pattern_and_corpus_escape_report_clean_error(tmp_path, capsys):
    source = archive(tmp_path / "input.qvf")
    assert main(["scrub", str(source), "--dry-run", "--user-pattern", "["]) == 2
    assert "Traceback" not in capsys.readouterr().err
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "escape.expected.json").write_text(json.dumps({"archive": "../input.qvf"}))
    assert main(["conformance", str(corpus)]) == 2
    assert "within the corpus" in capsys.readouterr().err


def test_diff_json_tolerance_metadata_and_chunked_payloads(tmp_path):
    source = archive(tmp_path / "input.qvf")
    def change(manifest, files):
        raw = json.dumps({"label": "example", "value": 1.00001}).encode()
        files["data/description.json"] = raw
        member = manifest["sections"][0]["members"]["description"]
        import hashlib
        member.update(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
        manifest["metadata"] = {"title": "Different metadata"}
    other = rewrite(source, tmp_path / "other.qvf", change)
    assert not operations.diff(source, other, atol=0.01)["equal"]
    assert operations.diff(source, other, atol=0.01, ignore_metadata=True)["equal"]
    large = tmp_path / "large.qvf"
    with Writer(large, program="example", version="1", auto_metadata=False) as writer:
        writer.add_section(Section(id="raw", kind="x_example.raw", members={}))
        with writer.begin_binary("raw", "values", "float64", [131073]) as member:
            member.write(struct.pack("<d", 1) * 131073)
    assert operations.diff(large, large)["equal"]
