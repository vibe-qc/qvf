"""Audit existing corpus and prepared drawings without inventing chemistry."""
import importlib.util
import json
from pathlib import Path

from qvf import Reader
from qvf.jobs import prepare_job
from test_prepare_job import OPTIONS, drawing, rewrite


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("audit_interchange", ROOT / "python/examples/audit_interchange.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
audit = MODULE.audit


def test_additive_job_preserves_unknown_optional_drawing(tmp_path):
    source = drawing(tmp_path / "drawing.qvf")
    result = tmp_path / "pending.qvf"
    prepare_job(source, result, **OPTIONS)
    report = audit(source, result)
    assert report["ok"], report
    assert report["source"]["sha256"] != report["result"]["sha256"]
    assert report["scientific_validity"] == "not_assessed"


def test_valid_lossy_save_is_not_a_lossless_roundtrip(tmp_path):
    source = drawing(tmp_path / "drawing.qvf")

    def drop(manifest, files):
        manifest["sections"] = [s for s in manifest["sections"] if s["id"] != "drawing"]

    result = rewrite(source, tmp_path / "lossy.qvf", drop)
    with Reader(result) as reader:
        assert reader.validate()["ok"]
    report = audit(source, result)
    assert not report["ok"]
    assert "section drawing: missing or changed declaration" in report["errors"]


def test_corrupt_payload_is_not_preservation(tmp_path):
    source = drawing(tmp_path / "drawing.qvf")
    result = rewrite(source, tmp_path / "corrupt.qvf",
                     lambda m, f: f.update({"molecule/structure.json": b"{}"}))
    report = audit(source, result)
    assert not report["ok"]
    assert "result: structural/integrity validation failed" in report["errors"]


def test_reuse_reaction_corpus_and_missing_reference_case():
    valid = ROOT / "conformance/corpus/reaction_scheme.qvf"
    invalid = ROOT / "conformance/negative/reaction_scheme_ref_wrong_kind.qvf"
    assert audit(valid, valid)["ok"]
    report = audit(valid, invalid)
    assert not report["ok"]
    assert any(f["code"] == "E_REF_UNRESOLVED" for f in report["result"]["validation"]["findings"])


def test_cli_corrupt_archive_refuses_with_json(tmp_path, monkeypatch, capsys):
    source = tmp_path / "corrupt.qvf"
    source.write_bytes(b"not a ZIP archive")
    monkeypatch.setattr("sys.argv", ["audit_interchange.py", str(source), str(source)])
    assert MODULE.main() == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
