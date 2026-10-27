"""Sketch documents: the chemical identity of structure sections (spec § 5.1),
``reaction.scheme`` (§ 5.14), ``preview`` (§ 5.15), opaque vendor members with
a ``media_type`` (§ 4.2, § 7.3), job sets (§ 5.8, § 5.9), removing and
replacing sections in an archive (§ 2.3), and the withdrawn ``qvf_version`` 2
(§ 3.1)."""

import io
import json
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

from qvf_reader import QvfReader, validate_qvf  # noqa: E402
from qvf_writer import QvfWriter  # noqa: E402

from test_reference_writer import _tiny_png  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LEGACY_V2 = os.path.join(ROOT, "conformance", "legacy", "reaction_path_v2.qvf")

WATER = [{"symbol": "O", "position": [0.0, 0.0, 0.1173]},
         {"symbol": "H", "position": [0.0, 0.7572, -0.4692]},
         {"symbol": "H", "position": [0.0, -0.7572, -0.4692]}]
OH = [{"symbol": "O", "position": [0.0, 0.0, 0.0]},
      {"symbol": "H", "position": [0.0, 0.0, 0.971]}]
SVG = "<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'/>"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 16 + b"\xff\xd9"


def _writer(**kw):
    return QvfWriter("test-code", "1.0", "sketch", auto_metadata=False, **kw)


def _codes(report, severity=None):
    return sorted(f["code"] for f in report["findings"]
                  if severity is None or f["severity"] == severity)


def _validate(writer):
    return validate_qvf(io.BytesIO(writer.to_bytes()))


def _section(writer, sid):
    return next(s for s in writer.build_manifest()["sections"] if s["id"] == sid)


# --- chemical identity (spec § 5.1) -------------------------------------------

def test_structure_identity_is_written_on_the_section():
    w = _writer()
    w.add_structure(WATER, charge=0, multiplicity=1, name="water", smiles="O",
                    inchi="InChI=1S/H2O/h1H2",
                    inchikey="XLYOFNOQVPJJNP-UHFFFAOYSA-N", label="1",
                    section_id="s1")
    section = _section(w, "s1")
    assert list(section)[:3] == ["id", "kind", "label"]
    assert {k: section[k] for k in ("charge", "multiplicity", "name", "smiles",
                                    "inchi", "inchikey", "label")} == {
        "charge": 0, "multiplicity": 1, "name": "water", "smiles": "O",
        "inchi": "InChI=1S/H2O/h1H2", "inchikey": "XLYOFNOQVPJJNP-UHFFFAOYSA-N",
        "label": "1"}
    assert _validate(w)["findings"] == []


@pytest.mark.parametrize("kwargs, match", [
    ({"charge": 0.5}, "integer"),
    ({"multiplicity": 0}, ">= 1"),
    ({"smiles": "C C"}, "smiles"),
    ({"smiles": "C\n"}, "smiles"),
    ({"inchikey": "XLYOFNOQVPJJNP-UHFFFAOYSA-N\n"}, "inchikey"),
    ({"inchi": "1S/H2O"}, "inchi"),
    ({"inchikey": "XLYOFNOQVPJJNP"}, "inchikey"),
    ({"name": ""}, "non-empty"),
    ({"charge": 0, "multiplicity": 2}, "parity"),
    ({"charge": 11}, "electrons"),
    ({"charge": -1, "multiplicity": 13}, "impossible"),
])
def test_structure_identity_is_checked(kwargs, match):
    w = _writer()
    with pytest.raises(ValueError, match=match):
        w.add_structure(WATER, section_id="s1", **kwargs)
    assert w.build_manifest()["sections"] == []
    w.add_structure(WATER, section_id="s1")     # the id was not reserved


def test_possible_charges_and_multiplicities():
    w = _writer()
    w.add_structure(OH, charge=0, multiplicity=2, section_id="radical")
    w.add_structure(OH, charge=-1, multiplicity=1, section_id="anion")
    w.add_structure(WATER, charge=0, multiplicity=3, section_id="triplet")
    w.add_structure(WATER, multiplicity=2, section_id="no_charge")   # unchecked
    assert _validate(w)["findings"] == []


def test_validator_checks_the_electron_count():
    w = _writer()
    w.add_structure(WATER, section_id="s1")
    w.annotate_section("s1", label="x")
    archive = w.build_manifest()
    data = w.to_bytes()
    # Patch an impossible multiplicity into the manifest (the writer refuses).
    archive["sections"][0].update({"charge": 0, "multiplicity": 2})
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            payload = zin.read(info)
            if info.filename == "manifest.json":
                payload = json.dumps(archive).encode()
            zout.writestr(info, payload)
    report = validate_qvf(io.BytesIO(out.getvalue()))
    assert [(f["code"], f["where"]) for f in report["findings"]] == [
        ("E_CHARGE_MULTIPLICITY", "/sections/0/multiplicity")]


def test_identity_agrees_with_provenance_only_for_a_single_structure():
    w = _writer()
    w.add_structure(WATER, charge=0, multiplicity=1, section_id="s1")
    w.set_provenance(charge=1, multiplicity=2)
    report = _validate(w)
    assert [(f["code"], f["where"]) for f in report["findings"]] == [
        ("E_ROOT_INCONSISTENT", "/sections/0/charge"),
        ("E_ROOT_INCONSISTENT", "/sections/0/multiplicity")]
    w.add_structure(OH, charge=0, multiplicity=2, section_id="s2")
    assert _validate(w)["findings"] == []       # two structures: no comparison


# --- reaction.scheme (spec § 5.14) --------------------------------------------

def _two_species():
    w = _writer()
    w.add_structure(WATER, charge=0, multiplicity=1, label="1", section_id="a")
    w.add_structure(OH, charge=0, multiplicity=2, label="2", section_id="b")
    return w


def test_reaction_scheme_normalises_participants():
    w = _two_species()
    w.add_reaction_scheme([
        {"id": "r1", "reactants": ["a"], "products": [{"structure_ref": "b",
                                                        "coefficient": 2}],
         "arrow": "retrosynthetic", "conditions": ["hv"],
         "yield_percent": 50, "yield_text": "50%", "x_note": "kept"}],
        label="scheme")
    section = _section(w, "reaction_scheme")
    assert section["kind"] == "reaction.scheme" and section["label"] == "scheme"
    with QvfReader(io.BytesIO(w.to_bytes())) as r:
        payload = r.read_json(section["members"]["scheme"])
    assert payload == {"steps": [{
        "id": "r1", "reactants": [{"structure_ref": "a"}],
        "products": [{"structure_ref": "b", "coefficient": 2}],
        "arrow": "retrosynthetic", "conditions": ["hv"], "yield_percent": 50,
        "yield_text": "50%", "x_note": "kept"}]}
    assert _validate(w)["findings"] == []


@pytest.mark.parametrize("step, match", [
    ({"id": "r1", "reactants": ["missing"], "products": ["b"]}, "no such section"),
    ({"id": "r1", "reactants": ["a", "a"], "products": ["b"]}, "more than once"),
    ({"id": "r1", "reactants": [], "products": ["b"]}, "at least one"),
    ({"id": "r1", "reactants": ["a"]}, "products is required"),
    ({"id": "r 1", "reactants": ["a"], "products": ["b"]}, "id must match"),
    ({"id": "r1", "reactants": ["a"], "products": ["b"], "arrow": "curly"}, "arrow"),
    ({"id": "r1", "reactants": ["a"], "products": ["b"], "yield_percent": 120},
     "0 to 100"),
    ({"id": "r1", "reactants": ["a"], "products": ["b"], "energies": {}},
     "needs version, deltas, terms"),
    ({"id": "r1", "reactants": [{"structure_ref": "a", "coefficient": 0}],
      "products": ["b"]}, "> 0"),
    ({"id": "r1", "reactants": ["a"], "products": ["b"], "conditions": "THF"},
     "list of strings"),
])
def test_reaction_scheme_is_checked(step, match):
    w = _two_species()
    with pytest.raises(ValueError, match=match):
        w.add_reaction_scheme([step])
    assert len(w.build_manifest()["sections"]) == 2


def _energies(**changes):
    """a -> b energies (spec § 5.14), one term each; ``changes`` edits them."""
    method = {"program": "test-code", "program_version": "1.0",
              "specification": {"method": "HF", "basis": "STO-3G"}}
    source = {"name": "a.out", "sha256": "0" * 64, "parser": "test/1"}
    terms = [{"structure_ref": "a", "coefficient": -1, "energy_eh": -75.0,
              "method": method, "source": source},
             {"structure_ref": "b", "coefficient": 1, "energy_eh": -75.5,
              "method": method, "source": source}]
    energies = {"version": 1, "deltas": {"energy": {"value_eh": -0.5,
                                                    "kcal_mol": -313.754737}},
                "terms": terms}
    for key, value in changes.items():
        if key.startswith("term1_"):
            terms[1][key[6:]] = value
        else:
            energies[key] = value
    return {"id": "r1", "reactants": ["a"], "products": ["b"], "energies": energies}


def test_reaction_scheme_energies_round_trip():
    w = _two_species()
    w.add_run_record(program="test-code", log_text="E -75.5", section_id="run_b")
    step = _energies(term1_run_ref="run_b")
    w.add_reaction_scheme([step])
    with QvfReader(io.BytesIO(w.to_bytes())) as r:
        payload = r.read_json(_section(w, "reaction_scheme")["members"]["scheme"])
    assert payload["steps"][0]["energies"] == step["energies"]
    assert _validate(w)["findings"] == []


@pytest.mark.parametrize("changes, match", [
    ({"deltas": {"energy": {"value_eh": -0.4}}}, "not the sum of its terms"),
    ({"deltas": {"energy": {"value_eh": -0.5, "kcal_mol": -300.0}}}, "627.509474"),
    ({"term1_coefficient": -1}, "but the step gives"),
    ({"term1_structure_ref": "a"}, "more than one term"),
    ({"term1_run_ref": "a"}, "does not name a run.record"),
    ({"term1_method": {"program": "other", "program_version": "1",
                       "specification": {}}}, "different methods"),
    ({"deltas": {"energy": {"value_eh": -0.5}, "enthalpy": {"value_eh": -0.5}},
      "temperature_k": 298.15, "pressure_atm": 1.0}, "has no enthalpy_eh"),
    ({"version": 2}, "1 was expected"),
])
def test_reaction_scheme_energies_are_checked(changes, match):
    pytest.importorskip("jsonschema") if match == "1 was expected" else None
    w = _two_species()
    with pytest.raises(ValueError, match=match):
        w.add_reaction_scheme([_energies(**changes)])
    assert len(w.build_manifest()["sections"]) == 2


def test_reaction_scheme_energies_refused_on_resonance():
    w = _two_species()
    with pytest.raises(ValueError, match="resonance"):
        w.add_reaction_scheme([{**_energies(), "arrow": "resonance"}])


def test_reaction_scheme_step_ids_are_unique():
    w = _two_species()
    step = {"id": "r1", "reactants": ["a"], "products": ["b"]}
    with pytest.raises(ValueError, match="used by another step"):
        w.add_reaction_scheme([step, dict(step)])
    with pytest.raises(ValueError, match="at least one step"):
        w.add_reaction_scheme([])


def test_reaction_scheme_participant_must_be_a_structure():
    w = _two_species()
    w.add_job_spec(job_type="molecular", structure_ref="a", section_id="job")
    with pytest.raises(ValueError, match="a 'job.spec' section"):
        w.add_reaction_scheme([{"id": "r1", "reactants": ["a"],
                                "products": ["job"]}])


# --- preview (spec § 5.15) ----------------------------------------------------

def test_preview_members_carry_their_media_type_and_are_stored():
    w = _writer()
    png = _tiny_png(4, 3)
    w.add_preview(png, image=SVG, label="picture")
    section = _section(w, "preview")
    thumb, image = section["members"]["thumbnail"], section["members"]["image"]
    assert thumb == {"path": "preview/thumbnail.png", "format": "binary",
                     "sha256": thumb["sha256"], "size": len(png),
                     "media_type": "image/png"}
    assert image["media_type"] == "image/svg+xml"
    assert image["path"] == "preview/image.svg"
    data = w.to_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.getinfo("preview/thumbnail.png").compress_type == zipfile.ZIP_STORED
        assert zf.getinfo("preview/image.svg").compress_type == zipfile.ZIP_STORED
        assert zf.read("preview/thumbnail.png") == png
    assert validate_qvf(io.BytesIO(data))["findings"] == []


def test_preview_media_types_are_sniffed_and_checked():
    w = _writer()
    w.add_preview(JPEG, image=_tiny_png(), section_id="p1")
    members = _section(w, "p1")["members"]
    assert members["thumbnail"]["media_type"] == "image/jpeg"
    assert members["thumbnail"]["path"] == "p1/thumbnail.jpg"
    assert members["image"]["media_type"] == "image/png"
    with pytest.raises(ValueError, match="not PNG or JPEG"):
        w.add_preview(b"GIF89a....", section_id="p2")
    with pytest.raises(ValueError, match="PNG signature"):
        w.add_preview(JPEG, thumbnail_media_type="image/png", section_id="p2")
    with pytest.raises(ValueError, match="is not one of"):
        w.add_preview(SVG.encode(), thumbnail_media_type="image/svg+xml",
                      section_id="p2")
    with pytest.raises(ValueError, match="UTF-8"):
        w.add_preview(_tiny_png(), image=b"<svg>\xff</svg>",
                      image_media_type="image/svg+xml", section_id="p2")
    assert [s["id"] for s in w.build_manifest()["sections"]] == ["p1"]


# --- opaque vendor members (spec § 4.2, § 7.3) --------------------------------

def test_vendor_section_with_opaque_members():
    w = _writer()
    w.add_vendor_section("x_demo.document", json_members={"doc": {"a": 1}},
                         opaque_members={"drawing": (SVG.encode(), "image/svg+xml"),
                                         "raw": b"\x00\x01\x02"},
                         section_id="doc")
    members = _section(w, "doc")["members"]
    assert members["drawing"]["media_type"] == "image/svg+xml"
    assert "dtype" not in members["raw"] and "media_type" not in members["raw"]
    assert _validate(w)["findings"] == []
    with pytest.raises(ValueError, match="type/subtype"):
        w.add_vendor_section("x_demo.other", opaque_members={"x": (b"1", "png")},
                             section_id="other")
    with pytest.raises(ValueError, match="type/subtype"):
        w.add_vendor_section("x_demo.other",
                             opaque_members={"x": (b"1", "image/png\n")},
                             section_id="other")
    with pytest.raises(ValueError, match="more than once"):
        w.add_vendor_section("x_demo.other", json_members={"x": {}},
                             opaque_members={"x": b"1"}, section_id="other")
    # Nothing of the refused sections was queued.
    with zipfile.ZipFile(io.BytesIO(w.to_bytes())) as zf:
        assert not any(n.startswith("other/") for n in zf.namelist())


# --- job sets (spec § 5.8, § 5.9) ---------------------------------------------

def test_job_set_with_one_run():
    w = _two_species()
    w.set_provenance(run_status="running")
    w.add_job_spec(job_type="molecular", method="rks", structure_ref="a",
                   section_id="job_a")
    w.add_job_spec(job_type="molecular", method="uks", multiplicity=2,
                   structure_ref="b", section_id="job_b")
    assert _section(w, "job_a")["structure_ref"] == "a"
    w.add_run_record(program="engine", log_text="ok\n", job_ref="job_a",
                     run_status="converged", section_id="run_a")
    run = _section(w, "run_a")
    assert run["job_ref"] == "job_a" and run["run_status"] == "converged"
    assert _validate(w)["findings"] == []
    with pytest.raises(ValueError, match="'job.spec' section"):
        w.add_run_record(program="engine", log_text="x", job_ref="a",
                         section_id="run_x")
    with pytest.raises(ValueError, match="run_status"):
        w.add_run_record(program="engine", log_text="x", job_ref="job_b",
                         run_status="pending", section_id="run_x")


def test_validator_resolves_job_ref():
    w = _two_species()
    w.add_run_record(program="engine", log_text="ok\n", section_id="run")
    data = w.build_manifest()
    data["sections"][-1]["job_ref"] = "a"
    raw = w.to_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            payload = zin.read(info)
            if info.filename == "manifest.json":
                payload = json.dumps(data).encode()
            zout.writestr(info, payload)
    report = validate_qvf(io.BytesIO(out.getvalue()))
    assert [(f["code"], f["where"]) for f in report["findings"]] == [
        ("E_REF_UNRESOLVED", "/sections/2/job_ref")]


# --- labels ---------------------------------------------------------------------

def test_label_on_any_add_method():
    w = _writer()
    sid = w.add_structure(WATER, label="water")
    w.add_bonds([{"i": 0, "j": 1}], label="O-H")
    w.add_citations("@misc{x, title={T}}", label="references")
    w.add_scf_history([{"iter": 1, "energy_eh": -75.0}], label="SCF")
    labels = {s["id"]: s.get("label") for s in w.build_manifest()["sections"]}
    assert labels == {sid: "water", "bonds": "O-H", "citations": "references",
                      "scf_history": "SCF"}
    with pytest.raises(ValueError, match="label must be a string"):
        w.add_bonds([{"i": 0, "j": 2}], label=3, section_id="b2")


# --- removing and replacing sections (spec § 2.3) -----------------------------

def test_remove_section_in_a_new_archive_drops_its_members():
    w = _writer()
    w.add_structure(WATER, section_id="s1")
    w.add_preview(_tiny_png())
    removed = w.remove_section("preview")
    assert removed["kind"] == "preview"
    with zipfile.ZipFile(io.BytesIO(w.to_bytes())) as zf:
        assert not any(n.startswith("preview/") for n in zf.namelist())
    w.add_preview(_tiny_png(3, 3))               # the id and the path are free again
    assert _section(w, "preview")["members"]["thumbnail"]["path"] == \
        "preview/thumbnail.png"
    with pytest.raises(ValueError, match="no section"):
        w.remove_section("nothing")


def test_replace_a_section_in_an_archive_on_disk(tmp_path):
    w = _writer()
    w.add_structure(WATER, section_id="s1")
    w.add_vendor_section("x_demo.document", json_members={"doc": {"rev": 1}},
                         section_id="doc")
    path = w.write(str(tmp_path / "doc.qvf"))

    u = QvfWriter.open_for_update(path)
    u.remove_section("doc")
    u.add_vendor_section("x_demo.document", json_members={"doc": {"rev": 2}},
                         section_id="doc")
    u.add_structure(OH, charge=0, multiplicity=2, section_id="s2")
    u.write()
    report = validate_qvf(path)
    assert report["ok"] and _codes(report) == ["W_ORPHAN_MEMBER"] * 2
    with QvfReader(path) as r:
        doc = next(s for s in r.sections if s["id"] == "doc")
        assert doc["members"]["doc"]["path"] == "doc/doc.2.json"
        assert r.read_json(doc["members"]["doc"]) == {"rev": 2}
        assert [s["id"] for s in r.sections] == ["s1", "doc", "s2"]

    # Repacking drops the superseded document and manifest.
    u = QvfWriter.open_for_update(path)
    u.set_metadata(title="repacked")
    u.write(repack=True)
    report = validate_qvf(path)
    assert report["findings"] == []
    with zipfile.ZipFile(path) as zf:
        assert "doc/doc.json" not in zf.namelist()
        assert zf.namelist().count("manifest.json") == 1


def test_update_an_archive_held_in_memory(tmp_path):
    w = _writer()
    w.add_structure(WATER, section_id="s1")
    w.add_vendor_section("x_demo.document", json_members={"doc": {"rev": 1}},
                         section_id="doc")
    original = w.to_bytes()

    u = QvfWriter.open_for_update(original)
    u.remove_section("doc")
    u.add_vendor_section("x_demo.document", json_members={"doc": {"rev": 2}},
                         section_id="doc")
    appended = u.to_bytes()
    packed = u.to_bytes(repack=True)
    assert _codes(validate_qvf(io.BytesIO(appended))) == ["W_ORPHAN_MEMBER"] * 2
    assert validate_qvf(io.BytesIO(packed))["findings"] == []
    assert len(packed) < len(appended)
    with QvfReader(io.BytesIO(packed)) as r:
        doc = next(s for s in r.sections if s["id"] == "doc")
        assert r.read_json(doc["members"]["doc"]) == {"rev": 2}
        assert r.manifest["metadata"]["modified_utc"].endswith("Z")

    with pytest.raises(TypeError, match="needs a path"):
        u.write()
    out = u.write(str(tmp_path / "saved"), repack=True)
    assert out.endswith("saved.qvf")
    assert validate_qvf(out)["findings"] == []
    # The saved archive is the base of the next update.
    u.add_structure(OH, section_id="s2")
    assert [s["id"] for s in QvfReader(io.BytesIO(u.to_bytes())).sections] == [
        "s1", "doc", "s2"]


# --- qvf_version 2 (spec § 3.1) -------------------------------------------------

@pytest.mark.skipif(not os.path.exists(LEGACY_V2), reason="legacy corpus not present")
def test_withdrawn_version_2_is_read_as_1():
    report = validate_qvf(LEGACY_V2)
    assert report["ok"] and _codes(report) == ["W_VERSION_WITHDRAWN"]
    with open(LEGACY_V2, "rb") as fh:
        u = QvfWriter.open_for_update(fh.read())
    u.set_metadata(title="restamped")
    data = u.to_bytes(repack=True)
    with QvfReader(io.BytesIO(data)) as r:
        assert r.manifest["qvf_version"] == 1
        assert r.manifest["schema_uri"].endswith("/spec/qvf/1/manifest.schema.json")
    assert validate_qvf(io.BytesIO(data))["findings"] == []
