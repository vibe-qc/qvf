"""Toolkit 0.3.0: what the family's programs already write or read.

The localized-orbital field ``localization_reference_basis`` and three
deprecated ``mo_metadata`` keys (spec § 5.3), ``null`` and the deprecated
``""`` for a ``job.spec`` ``functional`` or ``basis`` (§ 5.9), the
``viewer_defaults`` hints ``camera``, ``crossfade`` and ``energy_window``
(§ 3.4), ``structure_ref`` on a standalone ``bonds`` section (§ 5.1), and the
one rule for the withdrawn ``qvf_version`` 2 (§ 3.1, ``spec/legacy``).
"""

import hashlib
import io
import json
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

import qvf_reader  # noqa: E402
from qvf_reader import validate_qvf  # noqa: E402
from qvf_writer import QvfWriter  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
SCHEMA = json.load(open(qvf_reader._SCHEMA_PATH, encoding="utf-8"))
DEFS = SCHEMA["$defs"]

WATER = [{"symbol": "O", "position": [0.0, 0.0, 0.1173]},
         {"symbol": "H", "position": [0.0, 0.7572, -0.4692]},
         {"symbol": "H", "position": [0.0, -0.7572, -0.4692]}]
H2 = [{"symbol": "H", "position": [0.0, 0.0, 0.0]},
      {"symbol": "H", "position": [0.0, 0.0, 0.74]}]
MO_R = {"n_mo": 2, "n_ao": 2, "spin": "restricted", "orbital_kind": "canonical",
        "energies": [-0.5, 0.3], "occupations": [2.0, 0.0]}


def _writer():
    return QvfWriter("test-code", "1.0", "drift", auto_metadata=False)


def _payload_errors(defname, doc):
    pytest.importorskip("jsonschema")
    validator = qvf_reader._load_payload_validator(defname)
    return [e.message for e in validator.iter_errors(doc)]


def _with(base, **changes):
    doc = json.loads(json.dumps(base))
    doc.update(changes)
    return doc


def _patched(data, section_id, role, update):
    """``data`` (archive bytes) with the JSON payload of member ``role`` of
    section ``section_id`` passed through ``update``; the member's sha256 and
    size in the manifest follow. Produces payloads the reference writer has
    no parameter for, such as deprecated keys."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        entries = [(i.filename, zf.read(i)) for i in zf.infolist()]
    manifest = json.loads(dict(entries)["manifest.json"])
    member = next(s for s in manifest["sections"]
                  if s["id"] == section_id)["members"][role]
    payload = update(json.loads(dict(entries)[member["path"]]))
    raw = json.dumps(payload, indent=2).encode("utf-8")
    member["sha256"] = hashlib.sha256(raw).hexdigest()
    member["size"] = len(raw)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in entries:
            if name == member["path"]:
                body = raw
            elif name == "manifest.json":
                body = json.dumps(manifest, indent=2).encode("utf-8")
            zf.writestr(name, body)
    return out.getvalue()


def _report(data):
    return validate_qvf(io.BytesIO(data))


def _findings(report):
    return [(f["code"], f["severity"], f["where"]) for f in report["findings"]]


def _wavefunction_archive(orbital_kind="canonical"):
    w = _writer()
    w.add_structure(H2)
    w.add_wavefunction_gto(
        [{"center": 0, "l": 0, "exponents": [1.0], "coefficients": [1.0]},
         {"center": 1, "l": 0, "exponents": [1.0], "coefficients": [1.0]}],
        mo_coefficients=[[0.6, 0.6], [0.9, -0.9]], energies=[-0.6, 0.4],
        occupations=[2.0, 0.0], orbital_kind=orbital_kind)
    return w.to_bytes()


# --- mo_metadata (spec § 5.3) ---------------------------------------------------

def test_localization_reference_basis_is_a_non_empty_string():
    doc = _with(MO_R, orbital_kind="ibo", localization_method="ibo",
                localization_reference_basis="minao")
    assert _payload_errors("MoMetadataPayload", doc) == []
    for bad in ("", 1, None, ["minao"]):
        assert _payload_errors("MoMetadataPayload",
                               _with(doc, localization_reference_basis=bad)), bad


@pytest.mark.parametrize("key,good,bads", [
    ("iao_charges", [0.25, -0.25], ["0.25", [0.25, "x"], [[0.25]]]),
    ("excitation_index", 0, [-1, 1.5, "1", True]),
    ("excitation_energy_ev", 3.25, ["3.25", None, [3.25]]),
])
def test_deprecated_mo_metadata_keys_are_valid_and_typed(key, good, bads):
    definition = DEFS["MoMetadataPayload"]["properties"][key]
    assert definition["deprecated"] is True
    assert "SHOULD NOT" in definition["description"]
    assert _payload_errors("MoMetadataPayload", _with(MO_R, **{key: good})) == []
    for bad in bads:
        assert _payload_errors("MoMetadataPayload", _with(MO_R, **{key: bad})), bad


def test_an_unknown_mo_metadata_key_is_still_an_error():
    assert _payload_errors("MoMetadataPayload", _with(MO_R, iao_charge=[0.1]))


def test_archives_with_the_deprecated_keys_validate_without_findings():
    """No warning for a deprecated key, as for provenance.hostname and the
    legacy unit spellings."""
    def localized(meta):
        return dict(meta, orbital_kind="localized", localization_method="ibo",
                    localization_reference_basis="mini",
                    iao_charges=[0.0, 0.0])

    def nto(meta):
        return dict(meta, orbital_kind="natural",
                    occupation_semantics="transition_weight",
                    excitation_index=1, excitation_energy_ev=10.2)

    for update in (localized, nto):
        data = _patched(_wavefunction_archive(), "wf", "mo_metadata", update)
        report = _report(data)
        assert report["ok"] and report["findings"] == [], report["findings"]


def test_empty_localization_reference_basis_is_a_payload_schema_error():
    pytest.importorskip("jsonschema")
    data = _patched(_wavefunction_archive(), "wf", "mo_metadata",
                    lambda m: dict(m, localization_reference_basis=""))
    assert _findings(_report(data)) == [
        ("E_PAYLOAD_SCHEMA", "error", "/sections/1/members/mo_metadata")]


# --- job.spec functional and basis (spec § 5.9) ---------------------------------

@pytest.mark.parametrize("field", ["functional", "basis"])
def test_job_spec_functional_and_basis_take_null_and_the_deprecated_empty_string(
        field):
    assert _payload_errors("JobSpecPayload",
                           {"job_type": "molecular", field: None}) == []
    assert _payload_errors("JobSpecPayload",
                           {"job_type": "molecular", field: ""}) == []
    assert _payload_errors("JobSpecPayload",
                           {"job_type": "molecular", field: "pbe0"}) == []
    for bad in (3, ["pbe0"], {}, True):
        assert _payload_errors("JobSpecPayload",
                               {"job_type": "molecular", field: bad}), bad
    branches = DEFS["JobSpecPayload"]["properties"][field]["anyOf"]
    assert {"type": "null"} in branches
    empty = next(b for b in branches if b.get("const") == "")
    assert empty["deprecated"] is True


def test_job_spec_with_null_functional_validates_without_findings():
    w = _writer()
    w.add_structure(WATER)
    w.add_job_spec(job_type="molecular", method="rhf", basis="sto-3g",
                   structure_ref="structure", section_id="job_hf")
    w.add_job_spec(job_type="molecular", method="gfn2_xtb",
                   structure_ref="structure", section_id="job_xtb")
    data = _patched(w.to_bytes(), "job_hf", "spec",
                    lambda p: dict(p, functional=None))
    data = _patched(data, "job_xtb", "spec",
                    lambda p: dict(p, functional=None, basis=""))
    report = _report(data)
    assert report["ok"] and report["findings"] == [], report["findings"]


# --- viewer_defaults (spec § 3.4) -----------------------------------------------

CAMERA = {"position": [0.0, -12.0, 4.0], "focal_point": [0.0, 0.0, 0.0],
          "view_up": [0.0, 0.0, 1.0], "view_angle": 30.0}


@pytest.mark.parametrize("hints", [
    {"camera": CAMERA, "crossfade": {"a": "a", "b": "b", "blend": 0.25},
     "structure": {"energy_window": [-15.0, 10.0]}},
    # malformed hints never fail an archive (spec § 3.4)
    {"camera": "front", "crossfade": 5,
     "structure": {"energy_window": "valence"}},
    {"camera": {"position": [0, 0, 1]}, "crossfade": {"a": "nowhere"},
     "structure": {"energy_window": [10.0, -15.0]}},
    {"camera": None, "crossfade": [], "structure": {"energy_window": None}},
])
def test_viewer_hints_are_specified_only_and_never_fail_an_archive(hints):
    w = _writer()
    w.add_structure(WATER)
    w.set_viewer_defaults(hints)
    report = _report(w.to_bytes())
    assert report["ok"] and report["findings"] == [], report["findings"]


def test_camera_and_crossfade_are_documented_reserved_members():
    props = SCHEMA["properties"]["viewer_defaults"]["properties"]
    assert set(props) == {"auto_open", "bookmarks", "camera", "crossfade"}
    for key in ("camera", "crossfade"):
        assert set(props[key]) == {"description"}, key   # not checked
        assert "§ 3.4" in props[key]["description"]


@pytest.mark.parametrize("sid", ["camera", "crossfade"])
def test_camera_and_crossfade_are_reserved_section_ids(sid):
    with pytest.raises(ValueError, match="reserved"):
        _writer().add_structure(WATER, section_id=sid)
    w = _writer()
    w.add_structure(WATER, section_id="s")
    data = w.to_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        entries = [(i.filename, zf.read(i)) for i in zf.infolist()]
    manifest = json.loads(dict(entries)["manifest.json"])
    manifest["sections"][0]["id"] = sid
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name, body in entries:
            zf.writestr(name, json.dumps(manifest).encode()
                        if name == "manifest.json" else body)
    assert _findings(_report(out.getvalue())) == [
        ("E_RESERVED_ID", "error", "/sections/0/id")]


# --- bonds structure_ref (spec § 5.1) -------------------------------------------

def _two_structures(writer):
    writer.add_structure(WATER, section_id="structure_water")
    writer.add_structure(H2, section_id="structure_h2")


def test_add_bonds_writes_structure_ref_on_the_section():
    w = _writer()
    _two_structures(w)
    w.add_bonds([{"i": 0, "j": 1}], structure_ref="structure_h2",
                label="H-H", section_id="bonds_h2")
    section = w.build_manifest()["sections"][-1]
    assert list(section) == ["id", "kind", "label", "structure_ref", "members"]
    assert section["structure_ref"] == "structure_h2"
    report = _report(w.to_bytes())
    assert report["ok"] and report["findings"] == [], report["findings"]


def test_add_bonds_refuses_a_structure_ref_that_names_no_structure():
    w = _writer()
    _two_structures(w)
    w.add_job_spec(job_type="molecular", section_id="job")
    for ref in ("missing", "job"):
        with pytest.raises(ValueError, match="structure"):
            w.add_bonds([{"i": 0, "j": 1}], structure_ref=ref)
    assert [s["kind"] for s in w.build_manifest()["sections"]] == [
        "structure", "structure", "job.spec"]
    w.add_bonds([{"i": 0, "j": 1}])     # the id was not consumed


def _bonds_archive(pairs, structure_ref, *, order="bonds_last"):
    """Two structures and a bonds section, the section's structure_ref patched
    in so that any value can be tested."""
    w = _writer()
    if order == "bonds_first":
        w.add_bonds(pairs)
        _two_structures(w)
    else:
        _two_structures(w)
        w.add_job_spec(job_type="molecular", section_id="job")
        w.add_bonds(pairs)
    data = w.to_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        entries = [(i.filename, zf.read(i)) for i in zf.infolist()]
    manifest = json.loads(dict(entries)["manifest.json"])
    index = next(i for i, s in enumerate(manifest["sections"])
                 if s["kind"] == "bonds")
    if structure_ref is not None:
        manifest["sections"][index]["structure_ref"] = structure_ref
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name, body in entries:
            zf.writestr(name, json.dumps(manifest).encode()
                        if name == "manifest.json" else body)
    return out.getvalue(), index


def test_bond_indices_are_checked_against_the_referenced_structure():
    pairs = [{"i": 0, "j": 1}, {"i": 0, "j": 2}]
    data, _ = _bonds_archive(pairs, "structure_water")
    assert _report(data)["findings"] == []
    data, index = _bonds_archive(pairs, "structure_h2")
    report = _report(data)
    assert _findings(report) == [
        ("E_MEMBER_MALFORMED", "error", f"/sections/{index}/members/bonds")]
    assert "pairs[1].j 2" in report["findings"][0]["message"]
    assert "structure_h2" in report["findings"][0]["message"]


def test_bond_indices_resolve_a_structure_that_comes_later():
    data, index = _bonds_archive([{"i": 1, "j": 2}], "structure_h2",
                                 order="bonds_first")
    assert _findings(_report(data)) == [
        ("E_MEMBER_MALFORMED", "error", f"/sections/{index}/members/bonds")]


def test_bonds_without_structure_ref_are_not_counted():
    """Absent, the bonds belong to the first structure, and no atom count is
    checked: an archive that validated before still does."""
    data, _ = _bonds_archive([{"i": 0, "j": 7}], None)
    assert _report(data)["findings"] == []


@pytest.mark.parametrize("ref", ["missing", "job"])
def test_unresolved_bonds_structure_ref(ref):
    data, index = _bonds_archive([{"i": 0, "j": 7}], ref)
    assert _findings(_report(data)) == [
        ("E_REF_UNRESOLVED", "error", f"/sections/{index}/structure_ref")]


# --- the withdrawn qvf_version 2 (spec § 3.1) ------------------------------------

def test_the_legacy_v2_schema_is_frozen_and_described_as_it_is():
    path = os.path.join(ROOT, "spec", "legacy", "qvf_manifest_v2.schema.json")
    with open(path, "rb") as fh:
        assert hashlib.sha256(fh.read()).hexdigest() == (
            "a80e883f20462ff83d19b6d81bc4e320e9efcd8db0c1b520a620da9b91e5d139")
    with open(os.path.join(ROOT, "spec", "legacy", "README.md"),
              encoding="utf-8") as fh:
        readme = fh.read()
    with open(os.path.join(ROOT, "registry.json"), encoding="utf-8") as fh:
        registry = json.load(fh)
    compatibility = registry["version_decisions"][0]["compatibility"]
    for text in (readme, compatibility):
        assert "strict superset" not in text
        assert "not a superset" in text
        assert "W_VERSION_WITHDRAWN" in text


def test_x_vibesketch_lists_the_members_vibe_sketch_writes():
    with open(os.path.join(ROOT, "registry.json"), encoding="utf-8") as fh:
        registry = json.load(fh)
    entry = next(v for v in registry["vendor_namespaces"]
                 if v["namespace"] == "x_vibesketch")
    purpose = entry["purpose"]
    assert "document" in purpose and "species" in purpose and "sdf" in purpose
    assert "thumbnail." not in purpose and "(the scheme as SVG) and" not in purpose


# --- the family-data archives of the conformance corpus --------------------------

CORPUS = os.path.join(ROOT, "conformance", "corpus")
FAMILY_ARCHIVES = ["wavefunction_localized", "job_set_methods",
                   "deprecated_spellings", "bonds_structure_ref", "viewer_hints"]


def _corpus(name):
    path = os.path.join(CORPUS, f"{name}.qvf")
    with zipfile.ZipFile(path) as zf:
        entries = {name: zf.read(name) for name in zf.namelist()}
    manifest = json.loads(entries["manifest.json"])
    sections = {s["id"]: s for s in manifest["sections"]}

    def payload(sid, role):
        return json.loads(entries[sections[sid]["members"][role]["path"]])
    return path, manifest, sections, payload


@pytest.mark.parametrize("name", FAMILY_ARCHIVES)
def test_family_archive_validates_with_no_finding(name):
    path = os.path.join(CORPUS, f"{name}.qvf")
    report = validate_qvf(path)
    assert report["ok"] and report["findings"] == [], report["findings"]


def test_corpus_localized_orbitals_use_the_canonical_carriers():
    _, _, sections, payload = _corpus("wavefunction_localized")
    meta = payload("wf_ibo", "mo_metadata")
    assert meta["localization_reference_basis"] == "minao"
    assert meta["localization_method"] == "ibo"
    assert not {"iao_charges", "excitation_index",
                "excitation_energy_ev"} & set(meta)
    assert [sum(row) for row in meta["atom_populations"]] == [1.0, 1.0]
    assert "iao_charge" in sections["iao_charges"]["members"]


def test_corpus_job_set_states_null_for_what_a_method_takes_none_of():
    _, _, _, payload = _corpus("job_set_methods")
    rhf, xtb, pbe0 = (payload(j, "spec")
                      for j in ("job_rhf", "job_xtb", "job_pbe0"))
    assert "functional" in rhf and rhf["functional"] is None
    assert xtb["functional"] is None and xtb["basis"] is None
    assert pbe0["functional"] == "pbe0" and pbe0["basis"] == "def2-svp"


def test_corpus_deprecated_spellings_are_all_there():
    _, _, _, payload = _corpus("deprecated_spellings")
    assert "iao_charges" in payload("wf_localized_ibo", "mo_metadata")
    for role in ("hole", "electron"):
        meta = payload(f"wf_nto_S1_{role}", "mo_metadata")
        assert {"excitation_index", "excitation_energy_ev"} <= set(meta)
    assert payload("job_spec", "spec")["basis"] == ""


def test_corpus_bonds_name_their_structure():
    _, manifest, sections, payload = _corpus("bonds_structure_ref")
    first = next(s["id"] for s in manifest["sections"]
                 if s["kind"] == "structure")
    assert first == "structure_water"
    assert sections["bonds_h2"]["structure_ref"] == "structure_h2"
    assert "structure_ref" not in sections["bonds_water"]
    # bonds_water joins atom 2, which only the first structure has.
    h2_atoms = len(payload("structure_h2", "structure")["atoms"])
    assert max(p["j"] for p in payload("bonds_water", "bonds")["pairs"]) >= h2_atoms
    assert len(payload("structure_water", "structure")["atoms"]) == 3


def test_corpus_viewer_hints_have_the_specified_shapes():
    jsonschema = pytest.importorskip("jsonschema")
    _, manifest, sections, payload = _corpus("viewer_hints")
    hints = manifest["viewer_defaults"]
    camera_schema = dict(DEFS["Camera"], **{"$defs": DEFS})
    jsonschema.validate(hints["camera"], camera_schema)
    fade = hints["crossfade"]
    assert sections[fade["a"]]["kind"].startswith("volume.")
    assert sections[fade["b"]]["kind"].startswith("volume.")
    assert 0.0 <= fade["blend"] <= 1.0
    for sid in ("bands", "dos"):
        low, high = hints[sid]["energy_window"]
        assert high > low
    assert sections["bands"]["kind"] == "bands"
    assert sections["dos"]["kind"].startswith("dos.")
    fermi = payload("bands", "kpath")["fermi"]
    assert fermi == -4.5
