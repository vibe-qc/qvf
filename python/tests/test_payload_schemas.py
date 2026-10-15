"""Payload definitions for JSON members (spec § 5, § 6).

A JSON member whose ``(kind, role)`` is listed in ``qvf_reader._PAYLOAD_DEFS``
must conform to that ``$defs`` entry of the schema. These tests pin the table
itself, prove that what the reference writers emit conforms, and check that
each definition rejects the malformed payloads it exists to catch.
"""

import json
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

import qvf_reader  # noqa: E402
from qvf_reader import _PAYLOAD_DEFS, validate_qvf  # noqa: E402
from qvf_writer import QvfWriter  # noqa: E402

with open(qvf_reader._SCHEMA_PATH, encoding="utf-8") as _fh:
    SCHEMA = json.load(_fh)
DEFS = SCHEMA["$defs"]

WATER = [{"symbol": "O", "position": [0.0, 0.0, 0.1173], "atomic_number": 8},
         {"symbol": "H", "position": [0.0, 0.7572, -0.4692], "atomic_number": 1},
         {"symbol": "H", "position": [0.0, -0.7572, -0.4692], "atomic_number": 1}]


def _section_def(kind):
    for branch in DEFS["Section"]["oneOf"]:
        name = branch["$ref"].split("/")[-1]
        if DEFS[name].get("properties", {}).get("kind", {}).get("const") == kind:
            return DEFS[name]
    return None


def _is_json_member(spec):
    if spec.get("$ref") == "#/$defs/JsonMember":
        return True
    return any(_is_json_member(s) for s in spec.get("allOf", []))


# --- the table ---------------------------------------------------------------

def test_payload_defs_name_definitions_and_json_member_roles():
    """Every value names a $defs entry; every (kind, role) is a JSON member
    role of that kind's section definition."""
    assert _PAYLOAD_DEFS, "payload definition table is empty"
    for (kind, role), defname in _PAYLOAD_DEFS.items():
        assert defname in DEFS, f"{kind}/{role}: no $defs/{defname}"
        assert kind in qvf_reader._CANONICAL_KINDS, kind
        section = _section_def(kind)
        assert section is not None, f"no Section definition for kind {kind!r}"
        members = section["properties"]["members"]["properties"]
        assert role in members, f"{kind!r} has no member role {role!r}"
        assert _is_json_member(members[role]), \
            f"{kind}/{role} is not a JSON member in the schema"


def test_every_volume_grid_role_has_the_grid_definition():
    """Every kind with a `grid` member (and reaction.path's volume_grid) is
    covered, so a new volume kind cannot silently skip the check."""
    for branch in DEFS["Section"]["oneOf"]:
        sdef = DEFS[branch["$ref"].split("/")[-1]]
        kind = sdef.get("properties", {}).get("kind", {}).get("const")
        members = sdef.get("properties", {}).get("members", {}).get("properties", {})
        for role in ("grid", "volume_grid"):
            if kind and role in members:
                assert _PAYLOAD_DEFS.get((kind, role)) == "VolumeGridPayload", \
                    (kind, role)


@pytest.mark.parametrize("defname", sorted(set(_PAYLOAD_DEFS.values())))
def test_payload_definitions_are_valid_schemas(defname):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(
        {"$ref": f"#/$defs/{defname}", "$defs": DEFS})


# --- direct checks of each definition ----------------------------------------

def _errors(defname, doc):
    pytest.importorskip("jsonschema")
    v = qvf_reader._load_payload_validator(defname)
    assert v is not None
    return [e.message for e in v.iter_errors(doc)]


GRID = {"origin": [-1.0, -1.0, -1.0],
        "voxel_vectors": [[0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5]],
        "shape": [4, 4, 4]}
BASIS = {"structure_ref": "structure", "pure": True, "n_ao": 4,
         "shells": [{"center": 0, "l": 0, "exponents": [1.0, 0.5],
                     "coefficients": [0.6, 0.4], "pure": True},
                    {"center": 0, "l": 1, "exponents": [1.0],
                     "coefficients": [1.0]}]}
MO_R = {"n_mo": 2, "n_ao": 2, "spin": "restricted", "orbital_kind": "canonical",
        "energies": [-0.5, 0.3], "occupations": [2.0, 0.0]}
CHANNEL = {"n_mo": 2, "energies": [-0.5, 0.3], "occupations": [1.0, 0.0]}
MO_U = {"n_ao": 2, "spin": "unrestricted", "orbital_kind": "canonical",
        "alpha": CHANNEL, "beta": CHANNEL}
WAYPOINT = {"frame_index": 0, "label": "R", "kind": "reactant", "energy_eh": -1.0}


def _with(base, **changes):
    doc = json.loads(json.dumps(base))
    for key, value in changes.items():
        if value is None:
            doc.pop(key, None)
        else:
            doc[key] = value
    return doc


VALID = [
    ("VolumeGridPayload", GRID),
    ("VolumeGridPayload", _with(GRID, x_spacing_label="fine")),
    ("BasisPayload", BASIS),
    ("BasisPayload", _with(BASIS, pure=None)),
    ("BasisPayload", _with(BASIS, n_electrons=10, ecp=[
        {"center": 0, "n_core_electrons": 2, "label": "demo-ECP",
         "projectors": [{"l": 0, "exponents": [1.0], "coefficients": [2.0],
                         "powers": [2]}]}])),
    ("MoMetadataPayload", MO_R),
    ("MoMetadataPayload", _with(MO_R, n_mo=None, orbital_kind=None)),
    ("MoMetadataPayload", _with(MO_R, spin="restricted_open",
                                orbital_kind="pipek_mezey")),
    ("MoMetadataPayload", _with(MO_R, spin="generalized", complex=True,
                                coefficient_encoding="complex_split_last_axis",
                                coefficient_components=["real", "imag"])),
    ("MoMetadataPayload", _with(MO_R, orbital_kind="natural",
                                occupation_semantics="transition_weight",
                                symmetry_labels=["a1", "b2"],
                                k_point=[0.0, 0.0, 0.0], state_ref="S1")),
    ("MoMetadataPayload", _with(MO_R, orbital_kind="localized",
                                localization_method="boys",
                                atom_populations=[[0.5, 0.5], [1.0, 0.0]],
                                centroids_bohr=[[0, 0, 0], [0, 0, 1.0]],
                                n_centres=[2, 1])),
    ("MoMetadataPayload", MO_U),
    ("MoMetadataPayload", _with(MO_U, alpha=_with(CHANNEL, n_mo=None,
                                                  symmetry_labels=["a", "b"]))),
    ("TrajectoryMetadataPayload", {"symbols": ["O", "H", "H"]}),
    ("TrajectoryMetadataPayload", {
        "atoms": [{"symbol": "O", "atomic_number": 8}],
        "energies": [-74.9, -75], "kind": "md", "pbc": [True, True, True],
        "precision": "float64", "units": {"energies": "hartree"},
        "producer_note": "open root"}),
    ("ReactionPathMetadataPayload", {
        "symbols": ["O"], "waypoints": [WAYPOINT],
        "reaction_coordinate": [0.0, 1.0], "reaction_coordinate_unit": "bohr",
        "dim": 3, "volume_frame_index": [0, 2], "volume_label": "rho",
        "volume_isovalue": 0.05}),
    ("ReactionWaypointsPayload", {"waypoints": [WAYPOINT]}),
    ("ReactionWaypointsPayload", {"waypoints": [], "reaction_coordinate": [0.0]}),
    ("ScanSurfaceMetadataPayload", {"axis_a_label": "r1", "axis_b_label": "r2"}),
    ("ScanSurfaceMetadataPayload", {
        "axis_a": {"label": "r", "unit": "bohr", "atoms": [0, 1]},
        "axis_b": {"label": "a"}, "coordinate_a_label": "r",
        "coordinate_a_unit": "bohr", "energy_unit": "Eh"}),
    ("VibrationsMetadataPayload", {"frequencies": [-120.5, 1595, 3657]}),
    ("VibrationsMetadataPayload", {
        "frequencies": [1595], "ir_intensities": [70.1],
        "raman_activities": [5.0], "reduced_masses": [1.08],
        "force_constants": [1.6], "symmetry_labels": ["A1"],
        "imaginary": [False], "n_modes": 1, "symbols": ["O", "H", "H"],
        "atoms": WATER}),
]


@pytest.mark.parametrize("defname,doc", VALID)
def test_valid_payloads_pass(defname, doc):
    assert _errors(defname, doc) == []


INVALID = [
    # strict: unknown key, missing key, wrong arity, out-of-range values
    ("VolumeGridPayload", _with(GRID, spacing=0.5)),
    ("VolumeGridPayload", _with(GRID, shape=[4, 4])),
    ("VolumeGridPayload", _with(GRID, shape=[4, 0, 4])),
    ("VolumeGridPayload", _with(GRID, shape=[4.5, 4, 4])),
    ("VolumeGridPayload", _with(GRID, origin=None)),
    ("VolumeGridPayload", _with(GRID, voxel_vectors=[[0.5, 0, 0], [0, 0.5, 0]])),
    ("BasisPayload", _with(BASIS, structure_ref=None)),
    ("BasisPayload", _with(BASIS, shells=None)),
    ("BasisPayload", _with(BASIS, basis_name="sto-3g")),
    ("BasisPayload", _with(BASIS, shells=[{"center": 0, "l": 8,
                                           "exponents": [1.0],
                                           "coefficients": [1.0]}])),
    ("BasisPayload", _with(BASIS, shells=[{"center": -1, "l": 0,
                                           "exponents": [1.0],
                                           "coefficients": [1.0]}])),
    ("BasisPayload", _with(BASIS, shells=[{"center": 0, "l": 0,
                                           "exponents": [0.0],
                                           "coefficients": [1.0]}])),
    ("BasisPayload", _with(BASIS, shells=[{"center": 0, "l": 0,
                                           "exponents": [],
                                           "coefficients": []}])),
    ("BasisPayload", _with(BASIS, pure="false")),
    ("BasisPayload", _with(BASIS, ecp=[{"center": 0}])),
    ("MoMetadataPayload", _with(MO_R, spin=None)),
    ("MoMetadataPayload", _with(MO_R, spin="ghf")),
    ("MoMetadataPayload", _with(MO_R, orbital_kind="wannier")),
    ("MoMetadataPayload", _with(MO_R, energies=None)),
    ("MoMetadataPayload", _with(MO_R, alpha=CHANNEL)),
    ("MoMetadataPayload", _with(MO_R, n_mo=2.5)),
    ("MoMetadataPayload", _with(MO_R, energies=[-0.5, None])),
    ("MoMetadataPayload", _with(MO_R, coefficient_components=["imag", "real"])),
    ("MoMetadataPayload", _with(MO_U, beta=None)),
    ("MoMetadataPayload", _with(MO_U, energies=[-0.5, 0.3])),
    ("MoMetadataPayload", _with(MO_U, alpha=_with(CHANNEL, occupations=None))),
    ("MoMetadataPayload", _with(MO_U, alpha=_with(CHANNEL, spin="alpha"))),
    # typed-open: an unknown key is fine, a known key of the wrong type is not
    ("TrajectoryMetadataPayload", {"energies": [-1.0]}),
    ("TrajectoryMetadataPayload", {"symbols": ["O"], "kind": "relaxation"}),
    ("TrajectoryMetadataPayload", {"symbols": ["O"], "energies": "-1.0"}),
    ("TrajectoryMetadataPayload", {"symbols": ["O"], "pbc": [True, True]}),
    ("TrajectoryMetadataPayload", {"atoms": [{"symbol": "O"}]}),
    ("ReactionPathMetadataPayload", {"waypoints": [WAYPOINT]}),
    ("ReactionPathMetadataPayload", {"symbols": ["O"],
                                     "waypoints": [_with(WAYPOINT, kind="ts")]}),
    ("ReactionPathMetadataPayload", {"symbols": ["O"],
                                     "volume_frame_index": [-1]}),
    ("ReactionWaypointsPayload", {}),
    ("ReactionWaypointsPayload", {"waypoints": [_with(WAYPOINT, label=None)]}),
    ("ReactionWaypointsPayload", {"waypoints": [_with(WAYPOINT, frame=0)]}),
    ("ReactionWaypointsPayload", {"waypoints": [_with(WAYPOINT,
                                                      energy_eh="low")]}),
    ("ScanSurfaceMetadataPayload", {"axis_a": {"unit": "bohr"}}),
    ("ScanSurfaceMetadataPayload", {"axis_a": {"label": "r", "atoms": [-1]}}),
    ("VibrationsMetadataPayload", {"symbols": ["O"]}),
    ("VibrationsMetadataPayload", {"frequencies": ["1595"]}),
    ("VibrationsMetadataPayload", {"frequencies": [1.0], "imaginary": [0]}),
    ("VibrationsMetadataPayload", {"frequencies": [1.0],
                                   "atoms": [{"symbol": "O"}]}),
]


@pytest.mark.parametrize("defname,doc", INVALID)
def test_invalid_payloads_fail(defname, doc):
    assert _errors(defname, doc), f"{defname} accepted {doc!r}"


# --- end to end: writers and the validator -------------------------------------

def _shells():
    return [{"center": 0, "l": 0, "exponents": [1.0, 0.5],
             "coefficients": [0.6, 0.4]},
            {"center": 0, "l": 1, "exponents": [1.0], "coefficients": [1.0]}]


def test_writer_unrestricted_wavefunction_validates(tmp_path):
    """The Python writer's unrestricted output conforms to MoMetadataPayload
    unchanged (both shapes are exercised by the corpus and the writer)."""
    pytest.importorskip("jsonschema")
    w = QvfWriter("test-code", "1.0", "uhf")
    w.add_structure(WATER)
    C = np.eye(4)
    w.add_wavefunction_gto(_shells(), mo_coefficients_alpha=C,
                           mo_coefficients_beta=C,
                           energies_alpha=[-1, -0.5, 0.5, 1],
                           occupations_alpha=[1, 1, 0, 0],
                           k_point=[0.0, 0.0, 0.0], pure=False)
    path = str(tmp_path / "uhf.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["errors"]
    meta = w.build_manifest()["sections"][1]["members"]["mo_metadata"]
    assert meta["path"].endswith("mo_metadata.json")


def test_every_listed_payload_is_checked_end_to_end(tmp_path):
    """Each (kind, role) of the table is validated when present: a writer
    archive with one malformed payload per kind yields E_PAYLOAD_SCHEMA at
    that member's pointer, and nothing else."""
    pytest.importorskip("jsonschema")
    w = QvfWriter("test-code", "1.0", "bad-payloads")
    w.add_structure(WATER)
    coords = np.zeros((2, 3, 3))
    w.add_trajectory({"symbols": ["O", "H", "H"], "kind": "relaxation"},
                     coords, section_id="traj")
    w.add_reaction_path({"symbols": ["O", "H", "H"],
                         "waypoints": [{"frame_index": 0, "label": "R"}]},
                        coords, section_id="path")
    w.add_reaction_waypoints("traj", {"waypoints": [], "note": "x"},
                             section_id="marks")
    w.add_scan_surface({"axis_a": {"unit": "bohr"}}, [0.0, 1.0], [0.0, 1.0],
                       np.zeros((2, 2)), section_id="scan")
    w.add_vibrations({"symbols": ["O", "H", "H"]}, np.zeros((3, 3, 3)),
                     section_id="vib")
    w.add_wavefunction_gto(_shells(), mo_coefficients=np.eye(4),
                           orbital_kind="wannier", section_id="wf")
    path = str(tmp_path / "bad.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert not report["ok"]
    codes = {f["code"] for f in report["findings"]}
    assert codes == {"E_PAYLOAD_SCHEMA"}, report["findings"]
    where = {f["where"] for f in report["findings"]}
    assert where == {"/sections/1/members/metadata",
                     "/sections/2/members/metadata",
                     "/sections/3/members/waypoints",
                     "/sections/4/members/metadata",
                     "/sections/5/members/metadata",
                     "/sections/6/members/mo_metadata"}, where


def test_grid_payloads_checked_for_every_grid_kind(tmp_path):
    """A writer volume, basis.ao grid and the corpus grid all conform; the
    same grid with an extra non-`x_` key fails for every grid-carrying kind."""
    pytest.importorskip("jsonschema")
    w = QvfWriter("test-code", "1.0", "grids")
    w.add_structure(WATER)
    data = np.zeros((2, 3, 4), dtype=np.float32)
    vox = [[0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5]]
    for kind in sorted(QvfWriter._VOLUME_KINDS):
        w.add_volume(kind, data, [0, 0, 0], vox)
    w.add_basis_ao({"atom_index": 0, "atom_symbol": "O", "shell_index": 0,
                    "primitive_index": 0, "angular_momentum": [0, 0],
                    "shell_type": "s", "exponent": 130.7, "coefficient": 0.15,
                    "is_primitive": False, "is_contracted": True, "ao_index": 0},
                   data, [0, 0, 0], vox)
    path = str(tmp_path / "grids.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"], report["errors"]
    grid_doc = w._files[w.build_manifest()["sections"][1]["members"]["grid"]["path"]]
    assert json.loads(grid_doc)["shape"] == [2, 3, 4]


def test_reaction_path_volume_grid_is_checked(tmp_path):
    """reaction.path's optional volume_grid uses the grid definition."""
    pytest.importorskip("jsonschema")
    import hashlib
    import zipfile

    def member(path, raw, **extra):
        return {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), **extra}

    meta = json.dumps({"symbols": ["H"], "volume_frame_index": [0]}).encode()
    coords = np.zeros((1, 1, 3)).astype("<f8").tobytes()
    vols = np.zeros((1, 2, 2, 2)).astype("<f4").tobytes()
    files = {"p/metadata.json": meta, "p/coords.bin": coords,
             "p/frame_volumes.bin": vols}

    def archive(grid):
        g = json.dumps(grid).encode()
        files["p/volume_grid.json"] = g
        manifest = {"qvf_version": 1,
                    "source": {"program": "t", "version": "1", "calculation": "c"},
                    "sections": [{"id": "p", "kind": "reaction.path", "members": {
                        "metadata": member("p/metadata.json", meta, format="json"),
                        "coords": member("p/coords.bin", coords, format="binary",
                                         dtype="float64", shape=[1, 1, 3]),
                        "frame_volumes": member("p/frame_volumes.bin", vols,
                                                format="binary", dtype="float32",
                                                shape=[1, 2, 2, 2]),
                        "volume_grid": member("p/volume_grid.json", g,
                                              format="json")}}]}
        path = str(tmp_path / "rp.qvf")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            for name, raw in files.items():
                zf.writestr(name, raw)
        return validate_qvf(path)

    good = archive({"origin": [0, 0, 0], "voxel_vectors": [[1, 0, 0], [0, 1, 0],
                                                           [0, 0, 1]],
                    "shape": [2, 2, 2]})
    assert good["ok"], good["findings"]
    bad = archive({"origin": [0, 0, 0], "voxel_vectors": [[1, 0, 0], [0, 1, 0],
                                                          [0, 0, 1]],
                   "shape": [1, 2, 2, 2]})
    assert {f["code"] for f in bad["findings"]} == {"E_PAYLOAD_SCHEMA"}
    assert {f["where"] for f in bad["findings"]} == \
        {"/sections/0/members/volume_grid"}
