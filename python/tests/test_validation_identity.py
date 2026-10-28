"""Null optional job metadata is valid; validator identity never relaxes checks."""
import hashlib
import json
from pathlib import Path
import zipfile

from qvf import __version__, validate
from qvf.cli import main


def test_null_job_metadata_and_validation_identity(tmp_path, capsys):
    # Reuse the existing job fixture; do not copy or rerun paper calculations.
    fixture = Path(__file__).resolve().parents[2] / "conformance/corpus/job_spec.qvf"
    with zipfile.ZipFile(fixture) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["manifest.json"])
    member = next(s for s in manifest["sections"] if s["kind"] == "job.spec")["members"]["spec"]
    spec = json.loads(entries[member["path"]])
    spec.update(basis=None, functional=None)
    path = tmp_path / "null-optional-metadata.qvf"

    def write():
        raw = json.dumps(spec).encode()
        member.update(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
        entries[member["path"]] = raw
        entries["manifest.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)

    write()
    before = path.read_bytes()
    report = validate.run(path)
    assert report["ok"], report
    context = report["validation_context"]
    assert context["archive_format_version"] == 1
    assert context["reader_version"] == context["schema_toolkit_version"] == __version__
    assert context["schema_sha256"] == hashlib.sha256(Path(validate._SCHEMA_PATH).read_bytes()).hexdigest()
    assert context["schema_checked"] is True
    assert context["unsupported_format_version"] is False
    assert context["scientific_validity"] == "not_assessed"
    assert main(["validate", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["validation_context"] == context
    assert validate._main(["qvf-validate", "--json", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["validation_context"] == context
    assert main(["validate", str(path)]) == 0
    output = capsys.readouterr().out
    assert __version__ in output and context["schema_sha256"] in output
    assert "electronic stability are not assessed" in output
    assert path.read_bytes() == before

    spec["functional"] = 123  # A real schema violation remains an error.
    write()
    report = validate.run(path)
    assert not report["ok"]
    assert any(f["code"] == "E_PAYLOAD_SCHEMA" for f in report["findings"])
    spec["functional"] = None
    manifest["qvf_version"] = 99
    write()
    report = validate.run(path)
    assert not report["ok"] and report["validation_context"]["unsupported_format_version"]
    assert any(f["code"] == "E_VERSION" and "unsupported archive format version 99" in f["message"]
               for f in report["findings"])
