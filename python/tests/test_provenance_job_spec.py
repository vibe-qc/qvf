"""Typed ``provenance`` fields (spec § 3.2) and the grown ``job.spec`` payload
(spec § 5.9).

* The schema types ``provenance.software`` / ``git_commit`` / ``n_threads`` /
  ``n_mpi_ranks`` / ``n_gpus`` / ``started_utc`` / ``finished_utc`` while the
  block stays open, and ``$defs/JobSpecPayload`` gains ``structure_ref``,
  ``solvation``, ``dispersion``, ``relativistic``, ``scf``, ``geometry`` and
  ``resources``, each block strict.
* ``set_provenance`` and ``add_job_spec`` check what they write, with clear
  errors, and change nothing when they refuse a value.
* The validator resolves a ``job.spec`` payload's ``structure_ref`` to a
  ``structure`` section (``E_REF_UNRESOLVED``).
* The conformance archives that exercise all of it.
"""

import hashlib
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

import qvf_reader  # noqa: E402
from qvf_reader import QvfReader, validate_qvf  # noqa: E402
from qvf_writer import QvfWriter  # noqa: E402

_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
_CONFORMANCE = os.path.join(_ROOT, "conformance")
_HYDROGEN = [{"symbol": "H", "position": [0, 0, 0], "atomic_number": 1}]

with open(qvf_reader._SCHEMA_PATH, encoding="utf-8") as _fh:
    _SCHEMA = json.load(_fh)

# Every typed provenance field, with a value of the right form.
_PROVENANCE_FULL = {
    "software": [{"name": "my-code", "version": "1.2.3"},
                 {"name": "integral-lib", "version": "2.9.0",
                  "url": "https://example.org/integral-lib"}],
    "git_commit": "9f2b6c1d4e7a",
    "n_threads": 8, "n_mpi_ranks": 4, "n_gpus": 2,
    "started_utc": "2026-10-07T12:00:00Z",
    "finished_utc": "2026-10-07T12:07:31.25Z",
}

_SOLVATION = {"model": "pcm", "solvent": "water", "epsilon": 78.4}
_SCF = {"convergence": 1e-8, "max_iterations": 100, "guess": "sad",
        "damping": 0.3}
_GEOMETRY = {"convergence": 4.5e-4, "max_steps": 50, "coordinates": "redundant"}
_RESOURCES = {"n_cores": 16, "memory_mb": 32000, "walltime_s": 86400}
_JOB_FULL = {"job_type": "periodic", "method": "rks", "functional": "pbe",
             "basis": "pob-tzvp-rev2", "structure_ref": "structure",
             "kpoints": [4, 4, 1], "tasks": ["optimize"], "dispersion": "d3bj",
             "relativistic": "x2c", "solvation": _SOLVATION, "scf": _SCF,
             "geometry": _GEOMETRY, "resources": _RESOURCES,
             "options": {"cutoff_ha": 300.0}}


def _jsonschema():
    return pytest.importorskip("jsonschema")


def _provenance_errors(provenance):
    """Schema errors of a manifest whose root ``provenance`` is given."""
    jsonschema = _jsonschema()
    manifest = {"qvf_version": 1,
                "source": {"program": "p", "version": "1", "calculation": "c"},
                "sections": [], "provenance": provenance}
    validator = jsonschema.Draft202012Validator(_SCHEMA)
    return [e.message for e in validator.iter_errors(manifest)]


def _payload_errors(payload, defname="JobSpecPayload"):
    jsonschema = _jsonschema()
    validator = jsonschema.Draft202012Validator({
        "$schema": _SCHEMA["$schema"], "$ref": f"#/$defs/{defname}",
        "$defs": _SCHEMA["$defs"]})
    return [e.message for e in validator.iter_errors(payload)]


def _with(base, **changes):
    out = dict(base)
    out.update(changes)
    return out


def _codes(report):
    return {f["code"] for f in report["findings"]} - {"W_SCHEMA_SKIPPED"}


def _writer():
    w = QvfWriter("test-code", "1.0", "provenance", auto_metadata=False)
    w.add_structure(_HYDROGEN)
    return w


def _read_spec(reader):
    """The parsed ``spec`` member of the archive's ``job.spec`` section."""
    (section,) = [s for s in reader.manifest["sections"]
                  if s["kind"] == "job.spec"]
    return reader.read_json(section["members"]["spec"])


# --- schema: provenance --------------------------------------------------------

def test_every_typed_provenance_field_validates():
    assert _provenance_errors(_PROVENANCE_FULL) == []


def test_provenance_stays_open_and_keeps_wall_seconds():
    props = _SCHEMA["properties"]["provenance"]
    assert props["additionalProperties"] is True
    assert "wall_seconds" in props["properties"]
    assert "walltime_s" not in props["properties"]
    assert _provenance_errors({"x_anything": [1, 2], "other": "kept"}) == []
    assert _provenance_errors(_with(_PROVENANCE_FULL, wall_seconds=451.0)) == []


@pytest.mark.parametrize("value", [
    "9f2b6c1", "9F2B6C1D4E7A", "0" * 40, "a" * 64, "0123456789abcdefABCDEF"])
def test_git_commit_accepts_7_to_64_hex_characters(value):
    assert _provenance_errors({"git_commit": value}) == []


@pytest.mark.parametrize("value", [
    "9f2b6c", "a" * 65, "9f2b6c1g", "not-a-hash", "9f2b6c1 ", "", 1234567])
def test_git_commit_rejects_other_strings(value):
    assert _provenance_errors({"git_commit": value})


@pytest.mark.parametrize("key,minimum", [
    ("n_threads", 1), ("n_mpi_ranks", 1), ("n_gpus", 0)])
def test_count_fields_are_integers_at_or_above_their_minimum(key, minimum):
    assert _provenance_errors({key: minimum}) == []
    assert _provenance_errors({key: minimum + 63}) == []
    for bad in (minimum - 1, 1.5, "4", None, True):
        assert _provenance_errors({key: bad}), (key, bad)


@pytest.mark.parametrize("key", ["started_utc", "finished_utc"])
def test_utc_fields_take_the_metadata_form(key):
    for good in ("2026-10-07T12:00:00Z", "2026-10-07T12:00:00.25Z",
                 "2016-12-31T23:59:60Z"):
        assert _provenance_errors({key: good}) == [], good
    for bad in ("2026-10-07T12:00:00", "2026-10-07T12:00:00+00:00",
                "2026-10-07T12:00:00+02:00", "2026-10-07 12:00:00Z",
                "2026-10-07", "2026-13-07T12:00:00Z", "2026-10-07T24:00:00Z",
                "2026-10-07T12:00:00z", 1790000000):
        assert _provenance_errors({key: bad}), bad


def test_software_items_are_strict_objects_with_a_name():
    assert _provenance_errors({"software": []}) == []
    assert _provenance_errors({"software": [{"name": "a"}]}) == []
    assert _provenance_errors({"software": [{"name": "a", "x_build": "gnu"}]}) == []
    for bad in ([{"version": "1"}],              # name is required
                [{"name": ""}],
                [{"name": "a", "version": 1}],
                [{"name": "a", "url": 5}],
                [{"name": "a", "license": "MIT"}],   # strict
                ["a"],
                {"name": "a"},                    # not an array
                "a"):
        assert _provenance_errors({"software": bad}), bad


def test_provenance_pattern_is_metadatas():
    meta = _SCHEMA["$defs"]["Metadata"]["properties"]["created_utc"]["pattern"]
    props = _SCHEMA["properties"]["provenance"]["properties"]
    assert props["started_utc"]["pattern"] == meta
    assert props["finished_utc"]["pattern"] == meta


# --- schema: job.spec ----------------------------------------------------------

def test_full_job_spec_payload_validates():
    assert _payload_errors(_JOB_FULL) == []


def test_job_spec_root_stays_open_and_every_new_field_is_optional():
    assert _payload_errors({"job_type": "molecular"}) == []
    assert _payload_errors({"job_type": "molecular", "x_future": {"a": 1}}) == []
    assert _SCHEMA["$defs"]["JobSpecPayload"]["additionalProperties"] is True
    assert _SCHEMA["$defs"]["JobSpecPayload"]["required"] == ["job_type"]


@pytest.mark.parametrize("field,bad", [
    ("structure_ref", ""), ("structure_ref", 3),
    ("dispersion", ""), ("dispersion", 1),
    ("relativistic", ""), ("relativistic", ["x2c"]),
    ("solvation", "pcm"), ("scf", []), ("geometry", 1), ("resources", None),
])
def test_job_spec_scalar_fields_are_typed(field, bad):
    assert _payload_errors({"job_type": "molecular", field: bad}), (field, bad)


@pytest.mark.parametrize("block,payload", [
    ("solvation", {"solvent": "water"}),                      # model required
    ("solvation", {"model": ""}),
    ("solvation", {"model": "pcm", "epsilon": 0}),
    ("solvation", {"model": "pcm", "epsilon": -78.4}),
    ("solvation", {"model": "pcm", "epsilon": "78"}),
    ("solvation", {"model": "pcm", "cavity": 1.2}),           # strict
    ("scf", {"convergence": 0}),
    ("scf", {"convergence": -1e-8}),
    ("scf", {"max_iterations": 0}),
    ("scf", {"max_iterations": 10.5}),
    ("scf", {"guess": ""}),
    ("scf", {"damping": "0.3"}),
    ("scf", {"diis": True}),
    ("geometry", {"convergence": 0}),
    ("geometry", {"max_steps": 0}),
    ("geometry", {"coordinates": "zmatrix"}),
    ("geometry", {"coordinates": "Cartesian"}),
    ("geometry", {"trust_radius": 0.3}),
    ("resources", {"n_cores": 0}),
    ("resources", {"memory_mb": 0}),
    ("resources", {"memory_mb": 1.5}),
    ("resources", {"walltime_s": 0}),
    ("resources", {"walltime_s": -5}),
    ("resources", {"gpus": 1}),
])
def test_job_spec_blocks_reject_wrong_values_and_unknown_keys(block, payload):
    assert _payload_errors({"job_type": "molecular", block: payload}), \
        (block, payload)


@pytest.mark.parametrize("block,payload", [
    ("solvation", {"model": "smd"}),
    ("solvation", {"model": "cosmo", "epsilon": 2}),
    ("scf", {}),
    ("scf", {"damping": -0.5}),
    ("scf", {"convergence": 1}),
    ("scf", {"x_vendor": {"a": 1}}),
    ("geometry", {"coordinates": "cartesian"}),
    ("geometry", {"coordinates": "internal", "max_steps": 1}),
    ("resources", {"walltime_s": 0.5}),
    ("resources", {"x_queue": "short"}),
])
def test_job_spec_blocks_accept_the_forms_they_document(block, payload):
    assert _payload_errors({"job_type": "molecular", block: payload}) == [], \
        (block, payload)


# --- writer: set_provenance ----------------------------------------------------

def test_set_provenance_writes_every_typed_field_and_validates(tmp_path):
    w = _writer()
    w.set_provenance(method="rks", wall_seconds=451.0, **_PROVENANCE_FULL)
    prov = w.build_manifest()["provenance"]
    assert prov["software"] == _PROVENANCE_FULL["software"]
    assert prov["git_commit"] == "9f2b6c1d4e7a"
    assert (prov["n_threads"], prov["n_mpi_ranks"], prov["n_gpus"]) == (8, 4, 2)
    assert prov["started_utc"] == "2026-10-07T12:00:00Z"
    assert _provenance_errors(prov) == []
    path = w.write(str(tmp_path / "prov.qvf"))
    report = validate_qvf(path)
    assert report["ok"], report["errors"]
    with QvfReader(path) as r:
        assert r.manifest["provenance"]["software"][1]["name"] == "integral-lib"


def test_set_provenance_merges_and_none_removes_a_typed_key():
    w = _writer()
    w.set_provenance(method="rhf", n_threads=4)
    w.set_provenance(n_mpi_ranks=2, n_threads=None)
    assert w.build_manifest()["provenance"] == {"method": "rhf", "n_mpi_ranks": 2}
    w.set_provenance(git_commit="9f2b6c1")
    assert w.build_manifest()["provenance"]["git_commit"] == "9f2b6c1"


def test_set_provenance_converts_aware_datetimes_to_utc():
    w = _writer()
    cest = timezone(timedelta(hours=2))
    w.set_provenance(started_utc=datetime(2026, 10, 7, 14, 0, 0, tzinfo=cest),
                     finished_utc=datetime(2026, 10, 7, 12, 7, 31,
                                           tzinfo=timezone.utc))
    prov = w.build_manifest()["provenance"]
    assert prov["started_utc"] == "2026-10-07T12:00:00Z"
    assert prov["finished_utc"] == "2026-10-07T12:07:31Z"
    with pytest.raises(ValueError, match="naive datetime"):
        w.set_provenance(started_utc=datetime(2026, 10, 7, 12, 0, 0))


def test_set_provenance_accepts_numpy_integers():
    np = pytest.importorskip("numpy")
    w = _writer()
    w.set_provenance(n_threads=np.int64(8), n_gpus=np.int32(0))
    prov = w.build_manifest()["provenance"]
    assert prov["n_threads"] == 8 and type(prov["n_threads"]) is int
    assert json.dumps(prov)       # plain Python values


@pytest.mark.parametrize("fields,match", [
    ({"git_commit": "xyz"}, "git_commit"),
    ({"git_commit": "9f2b6c"}, "git_commit"),          # 6 characters
    ({"git_commit": "a" * 65}, "git_commit"),
    ({"git_commit": 1234567}, "git_commit"),
    ({"git_commit": "9f2b6c1\n"}, "git_commit"),      # no trailing newline
    ({"started_utc": "2026-10-07T12:00:00Z\n"}, "started_utc"),
    ({"n_threads": 0}, "n_threads"),
    ({"n_threads": 2.0}, "n_threads"),
    ({"n_threads": True}, "n_threads"),
    ({"n_threads": "4"}, "n_threads"),
    ({"n_mpi_ranks": 0}, "n_mpi_ranks"),
    ({"n_gpus": -1}, "n_gpus"),
    ({"started_utc": "2026-10-07T12:00:00"}, "started_utc"),
    ({"finished_utc": "2026-10-07T12:00:00+02:00"}, "finished_utc"),
    ({"finished_utc": 1790000000}, "finished_utc"),
    ({"software": {"name": "a"}}, "software"),
    ({"software": "a"}, "software"),
    ({"software": ["a"]}, r"software\[0\]"),
    ({"software": [{"version": "1"}]}, "name"),
    ({"software": [{"name": ""}]}, "name"),
    ({"software": [{"name": "a"}, {"name": "b", "version": 2}]},
     r"software\[1\] version"),
    ({"software": [{"name": "a", "license": "MIT"}]}, "license"),
])
def test_set_provenance_refuses_a_wrong_typed_field_and_changes_nothing(
        fields, match):
    w = _writer()
    w.set_provenance(method="rhf")
    with pytest.raises(ValueError, match=match):
        w.set_provenance(**{"n_gpus": 1, **fields})   # a good field alongside
    assert w.build_manifest()["provenance"] == {"method": "rhf"}


def test_set_provenance_leaves_other_fields_alone():
    """The block is open and the other fields keep their behaviour."""
    w = _writer()
    w.set_provenance(method="rhf", scf_energy_eh=-74.96, x_custom={"a": 1},
                     hostname="example-host")
    prov = w.build_manifest()["provenance"]
    assert prov == {"method": "rhf",
                    "scf_energy": {"value": -74.96, "units": "hartree"},
                    "x_custom": {"a": 1}}


def test_software_entry_may_carry_vendor_keys():
    w = _writer()
    w.set_provenance(software=[{"name": "a", "x_build": "release"}])
    assert _provenance_errors(w.build_manifest()["provenance"]) == []


# --- writer: add_job_spec ------------------------------------------------------

def test_add_job_spec_writes_every_new_field(tmp_path):
    w = _writer()
    w.add_job_spec(job_type="periodic", method="rks", functional="pbe",
                   basis="pob-tzvp-rev2", kpoints=[4, 4, 1], tasks=["optimize"],
                   structure_ref="structure", solvation=_SOLVATION,
                   dispersion="d3bj", relativistic="x2c", scf=_SCF,
                   geometry=_GEOMETRY, resources=_RESOURCES,
                   options={"cutoff_ha": 300.0})
    w.set_provenance(run_status="pending")
    path = w.write(str(tmp_path / "job.qvf"))
    report = validate_qvf(path)
    assert report["ok"], report["errors"]
    with QvfReader(path) as r:
        spec = _read_spec(r)
    assert spec == _JOB_FULL
    assert _payload_errors(spec) == []


def test_add_job_spec_omits_what_it_is_not_given():
    w = _writer()
    w.add_job_spec(job_type="molecular")
    (member,) = [s for s in w.build_manifest()["sections"]
                 if s["kind"] == "job.spec"][0]["members"].values()
    assert json.loads(w._files[member["path"]]) == {"job_type": "molecular"}


def test_add_job_spec_normalises_numbers_to_plain_json():
    np = pytest.importorskip("numpy")
    w = _writer()
    w.add_job_spec(job_type="molecular",
                   scf={"max_iterations": np.int64(50),
                        "convergence": np.float64(1e-6)},
                   resources={"n_cores": np.int32(4)})
    raw = w._files["job_spec/spec.json"].decode("utf-8")
    spec = json.loads(raw)
    assert spec["scf"] == {"max_iterations": 50, "convergence": 1e-6}
    assert spec["resources"] == {"n_cores": 4}


@pytest.mark.parametrize("kwargs,match", [
    ({"structure_ref": ""}, "structure_ref"),
    ({"structure_ref": 5}, "structure_ref"),
    ({"structure_ref": "a/b"}, "section id"),
    ({"dispersion": ""}, "dispersion"),
    ({"relativistic": 1}, "relativistic"),
    ({"solvation": "pcm"}, "solvation must be a mapping"),
    ({"solvation": {"solvent": "water"}}, "requires 'model'"),
    ({"solvation": {"model": "pcm", "epsilon": 0}}, "epsilon"),
    ({"solvation": {"model": "pcm", "epsilon": -1.0}}, "epsilon"),
    ({"solvation": {"model": "pcm", "epsilon": "78"}}, "epsilon"),
    ({"solvation": {"model": "pcm", "cavity": 1}}, "cavity"),
    ({"scf": {"convergence": 0}}, "scf.convergence"),
    ({"scf": {"convergence": float("nan")}}, "scf.convergence"),
    ({"scf": {"max_iterations": 0}}, "scf.max_iterations"),
    ({"scf": {"max_iterations": 2.5}}, "scf.max_iterations"),
    ({"scf": {"max_iterations": True}}, "scf.max_iterations"),
    ({"scf": {"guess": ""}}, "scf.guess"),
    ({"scf": {"damping": "high"}}, "scf.damping"),
    ({"scf": {"diis": True}}, "diis"),
    ({"geometry": {"convergence": -1}}, "geometry.convergence"),
    ({"geometry": {"max_steps": 0}}, "geometry.max_steps"),
    ({"geometry": {"coordinates": "zmatrix"}}, "geometry.coordinates"),
    ({"geometry": ["cartesian"]}, "geometry must be a mapping"),
    ({"resources": {"n_cores": 0}}, "resources.n_cores"),
    ({"resources": {"memory_mb": 0}}, "resources.memory_mb"),
    ({"resources": {"walltime_s": 0}}, "resources.walltime_s"),
    ({"resources": {"gpus": 1}}, "gpus"),
])
def test_add_job_spec_refuses_wrong_values_and_adds_nothing(kwargs, match):
    w = _writer()
    sections_before = len(w.build_manifest()["sections"])
    files_before = set(w._files)
    with pytest.raises(ValueError, match=match):
        w.add_job_spec(job_type="molecular", **kwargs)
    assert len(w.build_manifest()["sections"]) == sections_before
    assert set(w._files) == files_before
    w.add_job_spec(job_type="molecular")      # the id was not reserved


def test_add_job_spec_structure_ref_must_not_name_another_kind():
    w = _writer()
    w.add_citations("@misc{x, title={T}}", section_id="refs")
    with pytest.raises(ValueError, match="'citations' section, not a 'structure'"):
        w.add_job_spec(job_type="molecular", structure_ref="refs")
    # An existing structure is fine, and so is one added later.
    w.add_job_spec(job_type="molecular", structure_ref="structure",
                   section_id="job_a")
    w.add_job_spec(job_type="molecular", structure_ref="later",
                   section_id="job_b")


def test_add_job_spec_vendor_keys_pass_through_the_blocks():
    w = _writer()
    w.add_job_spec(job_type="molecular", scf={"x_engine_mode": "direct"},
                   resources={"x_queue": "short"})
    spec = json.loads(w._files["job_spec/spec.json"])
    assert spec["scf"] == {"x_engine_mode": "direct"}
    assert spec["resources"] == {"x_queue": "short"}
    assert _payload_errors(spec) == []


# --- validator: structure_ref resolution ---------------------------------------

def _spec_archive(tmp_path, name, **spec_fields):
    """A pending archive whose job spec carries ``spec_fields`` verbatim."""
    w = _writer()
    w.add_citations("@misc{x, title={T}}", section_id="refs")
    w.add_job_spec(job_type="molecular")
    w.set_provenance(run_status="pending")
    src = w.write(str(tmp_path / f"{name}_src.qvf"))
    return _replace_json_member(src, str(tmp_path / f"{name}.qvf"),
                                "job_spec/spec.json",
                                dict({"job_type": "molecular"}, **spec_fields))


def _replace_json_member(src, dst, member, payload):
    """Copy ``src`` to ``dst`` with the JSON member ``member`` replaced by
    ``payload`` and its ``sha256`` in the manifest updated."""
    data = json.dumps(payload, indent=2).encode("utf-8")
    with zipfile.ZipFile(src) as zin:
        manifest = json.loads(zin.read("manifest.json"))
        entries = {n: zin.read(n) for n in zin.namelist()}
    for section in manifest["sections"]:
        for spec in section["members"].values():
            if spec["path"] == member:
                spec["sha256"] = hashlib.sha256(data).hexdigest()
                if "size" in spec:          # member size (spec § 4.2)
                    spec["size"] = len(data)
    entries[member] = data
    entries["manifest.json"] = json.dumps(manifest, indent=2).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for n, b in entries.items():
            zout.writestr(n, b)
    with open(dst, "wb") as fh:
        fh.write(buf.getvalue())
    return dst


def test_validator_accepts_a_structure_ref_naming_a_structure(tmp_path):
    path = _spec_archive(tmp_path, "ok", structure_ref="structure")
    report = validate_qvf(path)
    assert report["ok"], report["errors"]


def test_validator_accepts_a_job_spec_without_structure_ref(tmp_path):
    report = validate_qvf(_spec_archive(tmp_path, "absent"))
    assert report["ok"], report["errors"]


@pytest.mark.parametrize("ref", ["nowhere", "refs", "job_spec", "", 7, None,
                                 ["structure"]])
def test_validator_reports_an_unresolved_structure_ref(tmp_path, ref):
    path = _spec_archive(tmp_path, "bad", structure_ref=ref)
    report = validate_qvf(path)
    assert not report["ok"]
    assert "E_REF_UNRESOLVED" in _codes(report), report["findings"]
    (finding,) = [f for f in report["findings"] if f["code"] == "E_REF_UNRESOLVED"]
    assert finding["where"] == "/sections/2/members/spec"
    assert "structure_ref" in finding["message"]


def test_resolution_does_not_depend_on_section_order(tmp_path):
    """A job.spec written before its structure still resolves."""
    w = QvfWriter("test-code", "1.0", "order", auto_metadata=False)
    w.add_job_spec(job_type="molecular", structure_ref="late")
    w.add_structure(_HYDROGEN, section_id="late")
    path = w.write(str(tmp_path / "order.qvf"))
    report = validate_qvf(path)
    assert report["ok"], report["errors"]


def test_schema_violations_in_the_blocks_are_payload_schema_errors(tmp_path):
    _jsonschema()
    path = _spec_archive(tmp_path, "schema", solvation={"solvent": "water"},
                         geometry={"coordinates": "zmatrix"})
    report = validate_qvf(path)
    assert not report["ok"]
    assert _codes(report) == {"E_PAYLOAD_SCHEMA"}


# --- the conformance archives --------------------------------------------------

def _archive(*parts):
    path = os.path.join(_CONFORMANCE, *parts)
    if not os.path.exists(path):
        pytest.skip(f"{os.path.join(*parts)} not present (standalone checkout)")
    return path


def test_job_spec_full_archive_exercises_every_new_field():
    path = _archive("corpus", "job_spec_full.qvf")
    report = validate_qvf(path)
    assert report["ok"], report["errors"]
    assert not report["warnings"] or all(
        w.startswith("W_SCHEMA_SKIPPED") for w in report["warnings"])
    with QvfReader(path) as r:
        manifest = r.manifest
        spec = _read_spec(r)
        kinds = {s["id"]: s["kind"] for s in manifest["sections"]}
    assert manifest["provenance"]["run_status"] == "pending"
    for key in ("software", "git_commit", "n_threads", "n_mpi_ranks",
                "started_utc", "finished_utc"):
        assert key in manifest["provenance"], key
    assert set(spec) >= {"structure_ref", "solvation", "dispersion",
                         "relativistic", "scf", "geometry", "resources"}
    assert kinds[spec["structure_ref"]] == "structure"
    assert spec["job_type"] == "periodic"
    assert [s["kind"] for s in manifest["sections"]].count("job.spec") == 1
    assert _payload_errors(spec) == []


def test_provenance_full_archive_uses_every_typed_field():
    path = _archive("corpus", "provenance_full.qvf")
    report = validate_qvf(path)
    assert report["ok"], report["errors"]
    with QvfReader(path) as r:
        prov = r.manifest["provenance"]
    assert set(prov) >= set(_PROVENANCE_FULL) | {"wall_seconds", "run_status"}
    assert prov["run_status"] == "converged"
    assert _provenance_errors(prov) == []


@pytest.mark.parametrize("name,codes", [
    ("job_spec_structure_ref_wrong_kind", {"E_REF_UNRESOLVED"}),
    ("provenance_git_commit_not_hex", {"E_SCHEMA"}),
    ("provenance_started_utc_not_utc", {"E_SCHEMA"}),
])
def test_negative_archives_are_rejected_with_their_codes(name, codes):
    path = _archive("negative", f"{name}.qvf")
    with open(_archive("negative", f"{name}.expected.json"),
              encoding="utf-8") as fh:
        expected = json.load(fh)
    assert {e["code"] for e in expected["expect"]} == codes
    if "E_SCHEMA" in codes:
        _jsonschema()             # only a validator with a schema engine sees it
    report = validate_qvf(path)
    assert not report["ok"]
    assert _codes(report) == codes, report["findings"]
