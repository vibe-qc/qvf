"""Root ``metadata`` (spec § 3.5) and generic section references (spec § 4.1).

* The writer adds ``created_utc`` and a random ``uuid`` by default, once per
  writer, and not with ``auto_metadata=False``; ``set_metadata`` checks the
  fields and wins over the automatic values.
* ``annotate_section`` sets ``structure_ref`` / ``run_ref`` / ``group`` /
  ``label`` on an added section and refuses a reference of the wrong kind.
* The validator resolves ``structure_ref`` to a ``structure`` section,
  ``run_ref`` to a ``run.record`` and ``reaction.waypoints.trajectory_ref`` to
  a ``trajectory`` (``E_REF_UNRESOLVED``), and the schema checks the metadata
  block (``E_SCHEMA``).
"""

import importlib.util
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

from qvf_reader import QvfReader, validate_qvf  # noqa: E402
from qvf_writer import QvfWriter  # noqa: E402

_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
_CORPUS = os.path.join(_ROOT, "conformance", "corpus")
_SCHEMA = os.path.join(HERE, "..", "qvf_manifest.schema.json")

_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}"
                    r"-[0-9a-f]{12}$")
_WATER = [{"symbol": "O", "position": [0, 0, 0.117], "atomic_number": 8},
          {"symbol": "H", "position": [0, 0.757, -0.469], "atomic_number": 1},
          {"symbol": "H", "position": [0, -0.757, -0.469], "atomic_number": 1}]


def _writer(**kw):
    return QvfWriter("test-code", "1.0", "metadata", **kw)


def _schema_errors(manifest):
    jsonschema = pytest.importorskip("jsonschema")
    with open(_SCHEMA, encoding="utf-8") as fh:
        validator = jsonschema.Draft202012Validator(json.load(fh))
    return [f"{list(e.path)}: {e.message}"
            for e in validator.iter_errors(manifest)]


def _codes(report):
    return {f["code"] for f in report["findings"]} - {"W_SCHEMA_SKIPPED"}


# --- root metadata: automatic values -----------------------------------------

def test_auto_metadata_by_default():
    w = _writer()
    w.add_structure(_WATER)
    meta = w.build_manifest()["metadata"]
    assert set(meta) == {"created_utc", "uuid"}
    assert _UTC.match(meta["created_utc"]), meta
    assert _UUID4.match(meta["uuid"]), meta
    stamp = datetime.strptime(meta["created_utc"], "%Y-%m-%dT%H:%M:%SZ")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs(now - stamp) < timedelta(minutes=5)
    assert not _schema_errors(w.build_manifest())


def test_auto_metadata_is_made_once_per_writer(tmp_path):
    w = _writer()
    w.add_structure(_WATER)
    first = w.build_manifest()["metadata"]
    path = w.write(str(tmp_path / "a.qvf"))
    with QvfReader(path) as r:
        assert r.manifest["metadata"] == first
    assert w.build_manifest()["metadata"] == first
    other = _writer().build_manifest()["metadata"]
    assert other["uuid"] != first["uuid"]


def test_auto_metadata_opt_out():
    w = _writer(auto_metadata=False)
    w.add_structure(_WATER)
    assert "metadata" not in w.build_manifest()
    w.set_metadata(title="explicit only")
    assert w.build_manifest()["metadata"] == {"title": "explicit only"}
    w2 = _writer()
    w2.auto_metadata = False
    assert "metadata" not in w2.build_manifest()


def test_explicit_values_win_over_auto():
    w = _writer()
    w.set_metadata(uuid="6f1c2a4e-8b3d-4c5e-9f70-1a2b3c4d5e6f")
    meta = w.build_manifest()["metadata"]
    assert meta["uuid"] == "6f1c2a4e-8b3d-4c5e-9f70-1a2b3c4d5e6f"
    assert _UTC.match(meta["created_utc"])
    w.set_metadata(created_utc="2026-01-02T03:04:05Z")
    assert w.build_manifest()["metadata"]["created_utc"] == "2026-01-02T03:04:05Z"


def test_conformance_generator_turns_auto_metadata_off():
    path = os.path.join(_ROOT, "conformance", "generate_corpus.py")
    if not os.path.exists(path):
        pytest.skip("conformance generator not present (standalone checkout)")
    spec = importlib.util.spec_from_file_location("generate_corpus", path)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert "metadata" not in gen.QvfWriter("p", "1", "c").build_manifest()


# --- root metadata: set_metadata ---------------------------------------------

def test_set_metadata_every_field_validates(tmp_path):
    w = _writer()
    w.add_structure(_WATER)
    w.set_metadata(
        title="Water", description="RHF/STO-3G water",
        created_utc=datetime(2026, 10, 7, 14, 0, tzinfo=timezone(timedelta(hours=2))),
        modified_utc="2026-10-07T12:30:00.125Z",
        uuid=uuid.UUID("3F2504E0-4F89-41D3-9A0C-0305E82C3301"),
        authors=[{"name": "A. Researcher", "orcid": "0000-0002-1825-0097"},
                 {"name": "B. Researcher", "affiliation": "Example Institute",
                  "email": "researcher@example.org", "x_role": "analysis"}],
        license="CC-BY-4.0", doi="10.5281/zenodo.1234567",
        keywords=["water", "rhf"],
        derived_from=["6f1c2a4e-8b3d-4c5e-9f70-1a2b3c4d5e6f"],
        tags=("draft",), x_demo={"anything": True})
    meta = w.build_manifest()["metadata"]
    assert meta["created_utc"] == "2026-10-07T12:00:00Z"        # converted to UTC
    assert meta["uuid"] == "3f2504e0-4f89-41d3-9a0c-0305e82c3301"  # lowercase
    assert meta["tags"] == ["draft"]
    assert not _schema_errors(w.build_manifest())
    path = w.write(str(tmp_path / "meta.qvf"))
    report = validate_qvf(path)
    assert report["ok"], report["errors"]


def test_set_metadata_merges_and_none_removes():
    w = _writer(auto_metadata=False)
    w.set_metadata(title="A", license="MIT")
    w.set_metadata(title="B", keywords=["k"])
    assert w.build_manifest()["metadata"] == {"title": "B", "license": "MIT",
                                              "keywords": ["k"]}
    w.set_metadata(license=None)
    assert w.build_manifest()["metadata"] == {"title": "B", "keywords": ["k"]}


@pytest.mark.parametrize("fields", [
    {"titel": "typo"},                                  # unknown key
    {"created_utc": "2026-10-07 12:00:00"},             # no T, no Z
    {"created_utc": "2026-10-07T12:00:00+02:00"},       # not UTC
    {"modified_utc": "2026-13-01T00:00:00Z"},           # month 13
    {"created_utc": datetime(2026, 10, 7, 12, 0)},      # naive datetime
    {"uuid": "3f2504e04f8941d39a0c0305e82c3301"},       # no hyphens
    {"uuid": "3f2504e0-4f89-01d3-9a0c-0305e82c3301"},   # version 0
    {"uuid": "3f2504e0-4f89-41d3-7a0c-0305e82c3301"},   # NCS variant
    {"uuid": 42},
    {"keywords": "water"},                              # a string, not a list
    {"tags": ["ok", 3]},
    {"license": ""},
    {"title": 5},
    {"authors": [{"orcid": "0000-0002-1825-0097"}]},    # no name
    {"authors": [{"name": "A", "phone": "000"}]},       # unknown author key
    {"authors": {"name": "A"}},                         # not a list
])
def test_set_metadata_rejects(fields):
    w = _writer(auto_metadata=False)
    w.set_metadata(title="kept")
    with pytest.raises(ValueError):
        w.set_metadata(**fields)
    assert w.build_manifest()["metadata"] == {"title": "kept"}


@pytest.mark.parametrize("metadata", [
    {"uuid": "3F2504E0-4F89-41D3-9A0C-0305E82C3301"},   # uppercase
    {"created_utc": "2026-10-07T12:00:00"},             # no Z
    {"subject": "unknown key"},
    {"authors": [{"orcid": "0000-0002-1825-0097"}]},
    {"authors": [{"name": "A", "phone": "000"}]},
    {"keywords": "water"},
])
def test_schema_rejects_bad_metadata(tmp_path, metadata):
    pytest.importorskip("jsonschema")
    w = _writer(auto_metadata=False)
    w.add_structure(_WATER)
    w._root["metadata"] = metadata       # bypass the writer's own checks
    path = w.write(str(tmp_path / "bad.qvf"))
    report = validate_qvf(path)
    assert _codes(report) == {"E_SCHEMA"}, report["findings"]
    assert all(f["where"].startswith("/metadata") for f in report["findings"]
               if f["code"] == "E_SCHEMA")


# --- annotate_section ---------------------------------------------------------

def _two_step_writer():
    w = _writer(auto_metadata=False)
    w.add_structure(_WATER, section_id="geom")
    w.add_run_record(program="test-code", log_text="done\n", section_id="run")
    w.add_scf_history([{"iter": 1, "energy_eh": -74.9}], section_id="scf")
    return w


def test_annotate_section_sets_fields(tmp_path):
    w = _two_step_writer()
    assert w.annotate_section("scf", structure_ref="geom", run_ref="run",
                              group="step 1", label="SCF") == "scf"
    w.annotate_section("scf", group="step 2")          # None leaves the rest
    sec = next(s for s in w.build_manifest()["sections"] if s["id"] == "scf")
    assert (sec["structure_ref"], sec["run_ref"], sec["group"], sec["label"]) \
        == ("geom", "run", "step 2", "SCF")
    path = w.write(str(tmp_path / "annotated.qvf"))
    report = validate_qvf(path)
    assert report["ok"] and not _codes(report), report["findings"]


@pytest.mark.parametrize("kwargs", [
    {"structure_ref": "run"},           # a run.record, not a structure
    {"structure_ref": "nowhere"},
    {"run_ref": "geom"},                # a structure, not a run.record
    {"run_ref": "nowhere"},
    {"group": 3},
    {"structure_ref": "geom", "run_ref": "scf"},   # atomic: nothing is set
])
def test_annotate_section_rejects(kwargs):
    w = _two_step_writer()
    before = json.loads(json.dumps(w.build_manifest()))
    with pytest.raises(ValueError):
        w.annotate_section("scf", **kwargs)
    assert w.build_manifest() == before


def test_annotate_unknown_section():
    with pytest.raises(ValueError, match="no section"):
        _two_step_writer().annotate_section("missing", group="g")


def test_annotate_any_kind_including_vendor(tmp_path):
    w = _two_step_writer()
    w.add_vendor_section("x_demo.note", json_members={"note": {"text": "hi"}},
                         section_id="note")
    w.annotate_section("note", structure_ref="geom", run_ref="run", group="g")
    w.annotate_section("geom", structure_ref="geom")   # self-reference is legal
    report = validate_qvf(w.write(str(tmp_path / "vendor.qvf")))
    assert report["ok"] and not _codes(report), report["findings"]


# --- validator: reference resolution -----------------------------------------

def _archive_with(tmp_path, mutate):
    """Write ``_two_step_writer`` plus a trajectory after ``mutate`` edits the
    sections (by id) behind the writer's checks."""
    w = _two_step_writer()
    w.add_trajectory({"symbols": ["O", "H", "H"]}, np.zeros((1, 3, 3)),
                     section_id="traj")
    w.add_reaction_waypoints("traj", {"waypoints": [
        {"frame_index": 0, "label": "R", "kind": "reactant"}]},
        section_id="marks")
    mutate({s["id"]: s for s in w._sections})
    return validate_qvf(w.write(str(tmp_path / "refs.qvf")))


@pytest.mark.parametrize("sid, field, value", [
    ("scf", "structure_ref", "nowhere"),
    ("scf", "structure_ref", "run"),
    ("scf", "structure_ref", "traj"),
    ("scf", "run_ref", "nowhere"),
    ("scf", "run_ref", "geom"),
    ("marks", "trajectory_ref", "geom"),
    ("marks", "trajectory_ref", "scf"),
    ("marks", "trajectory_ref", "nowhere"),
    ("traj", "run_ref", "marks"),
])
def test_unresolved_or_wrong_kind_reference(tmp_path, sid, field, value):
    def mutate(by_id):
        by_id[sid][field] = value
    report = _archive_with(tmp_path, mutate)
    assert not report["ok"]
    assert _codes(report) == {"E_REF_UNRESOLVED"}, report["findings"]
    (finding,) = [f for f in report["findings"] if f["code"] == "E_REF_UNRESOLVED"]
    assert finding["where"].endswith("/" + field)


def test_non_string_reference(tmp_path):
    def mutate(by_id):
        by_id["scf"]["structure_ref"] = 7
    report = _archive_with(tmp_path, mutate)
    assert "E_REF_UNRESOLVED" in _codes(report)


def test_valid_references_pass(tmp_path):
    def mutate(by_id):
        by_id["scf"].update(structure_ref="geom", run_ref="run", group="g")
        by_id["traj"].update(structure_ref="geom", run_ref="run")
        by_id["marks"]["run_ref"] = "run"
    report = _archive_with(tmp_path, mutate)
    assert report["ok"] and not _codes(report), report["findings"]


def test_duplicate_id_resolves_to_first_section(tmp_path):
    """With duplicate ids (E_SECTION_ID_DUPLICATE) a reference resolves to the
    first section that has the id, as in the C++ and JS validators."""
    def mutate(by_id):
        by_id["scf"]["structure_ref"] = "geom"
        by_id["traj"]["id"] = "geom"                 # second 'geom', a trajectory
        by_id["marks"]["trajectory_ref"] = "geom"    # first 'geom' is a structure
    report = _archive_with(tmp_path, mutate)
    assert _codes(report) == {"E_SECTION_ID_DUPLICATE", "E_REF_UNRESOLVED"}
    (ref,) = [f for f in report["findings"] if f["code"] == "E_REF_UNRESOLVED"]
    assert ref["where"].endswith("/trajectory_ref")


# --- the corpus archive -------------------------------------------------------

def test_multi_structure_corpus_archive():
    path = os.path.join(_CORPUS, "multi_structure.qvf")
    if not os.path.exists(path):
        pytest.skip("conformance corpus not present (standalone checkout)")
    report = validate_qvf(path)
    assert report["ok"], report["errors"]
    with QvfReader(path) as r:
        by_id = {s["id"]: s for s in r.sections}
        kinds = {s["kind"] for s in r.sections}
        assert sum(s["kind"] == "structure" for s in r.sections) == 2
        assert {"volume.density", "wavefunction.gto", "run.record"} <= kinds
        for s in r.sections:
            if "structure_ref" in s:
                assert by_id[s["structure_ref"]]["kind"] == "structure"
            if "run_ref" in s:
                assert by_id[s["run_ref"]]["kind"] == "run.record"
        wf = next(s for s in r.sections if s["kind"] == "wavefunction.gto")
        basis = r.read_json(wf["members"]["basis"])
        # Section and payload agree, as spec § 4.1 asks of producers.
        assert basis["structure_ref"] == wf["structure_ref"]
        rho = next(s for s in r.sections if s["kind"] == "volume.density")
        assert rho["structure_ref"] != wf["structure_ref"]
        meta = r.manifest["metadata"]
        assert meta["license"] == "Apache-2.0"
        assert not any("email" in a or "affiliation" in a
                       for a in meta.get("authors", []))
