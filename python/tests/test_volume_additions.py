"""The ``volume.vector``, ``volume.complex``, ``volume.series`` and
``volume.laplacian`` kinds and the periodic grid semantics (spec § 5.2; P11).

Covers the writer (new kinds, the series ``axis``, the grid fields
``periodic``, ``includes_endpoint`` and ``structure_ref``, and its refusals),
the schema definitions, and the validator rules JSON Schema cannot express:
the data shape of each new kind, a series axis against its slabs, the grid
and axis references, and the span of a periodic grid against the cell of its
structure, in both endpoint conventions.
"""

import hashlib
import json
import math
import os
import sys
import zipfile

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

import qvf_reader  # noqa: E402
import qvf_writer  # noqa: E402
from qvf_reader import QvfReader, validate_qvf  # noqa: E402
from qvf_writer import BOHR_PER_ANGSTROM, QvfWriter  # noqa: E402

_SCHEMA_CODES = {"E_SCHEMA", "E_PAYLOAD_SCHEMA", "W_SCHEMA_SKIPPED"}
_CORPUS = os.path.normpath(os.path.join(HERE, "..", "..", "conformance", "corpus"))
_SPEC = os.path.normpath(os.path.join(HERE, "..", "..", "spec", "qvf-format-spec.md"))

EYE = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
SODIUM = [{"symbol": "Na", "position": [0.0, 0.0, 0.0], "atomic_number": 11}]
CUBIC = [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]]       # Å
HEXAGONAL = [[2.46, 0.0, 0.0], [-1.23, 2.130422, 0.0], [0.0, 0.0, 3.35]]


def _codes(report):
    return {f["code"] for f in report["findings"]} - _SCHEMA_CODES


def _where(report, code):
    return sorted(f["where"] for f in report["findings"] if f["code"] == code)


def _validate(writer, tmp_path, name="a.qvf"):
    path = str(tmp_path / name)
    writer.write(path)
    return validate_qvf(path)


def _vox(rows, shape, endpoint):
    """Voxel vectors (bohr) that span ``rows`` (Å) with ``shape`` points."""
    return [[x * BOHR_PER_ANGSTROM / (shape[a] - (1 if endpoint else 0))
             for x in rows[a]] for a in range(3)]


def _periodic_writer(rows=CUBIC, pbc=(True, True, True), shape=(4, 4, 4),
                     endpoint=False, vox=None, periodic=(True, True, True),
                     **kw):
    w = QvfWriter("t", "1", "periodic grid", auto_metadata=False)
    w.add_structure(SODIUM, pbc=list(pbc), lattice_vectors=rows)
    w.add_volume("volume.density", np.ones(shape, np.float32), [0, 0, 0],
                 vox if vox is not None else _vox(rows, shape, endpoint),
                 periodic=list(periodic), includes_endpoint=endpoint,
                 section_id="rho", **kw)
    return w


# --- raw archives, so the validator sees what the writer refuses ---------------

def _member(path, data, fmt="json", dtype=None, shape=None):
    m = {"path": path, "format": fmt, "sha256": hashlib.sha256(data).hexdigest()}
    if dtype is not None:
        m["dtype"], m["shape"] = dtype, shape
    return m


def _raw_volume(tmp_path, kind, shape, axis=None, grid_shape=None):
    """An archive with one water-free structure and one volume section of
    ``kind`` whose data has ``shape`` (float32 zeros)."""
    struct_doc = json.dumps({"atoms": SODIUM}).encode()
    data = np.zeros(shape, np.float32).astype("<f4").tobytes()
    spatial = grid_shape or (list(shape[1:]) if kind == "volume.series"
                             else list(shape[:3]))
    grid = json.dumps({"origin": [0, 0, 0], "voxel_vectors": EYE,
                       "shape": spatial}).encode()
    files = {"s/structure.json": struct_doc, "v/grid.json": grid, "v/data.bin": data}
    members = {"grid": _member("v/grid.json", grid),
               "data": _member("v/data.bin", data, "binary", "float32", list(shape))}
    if axis is not None:
        ax = json.dumps(axis).encode()
        files["v/axis.json"] = ax
        members["axis"] = _member("v/axis.json", ax)
    manifest = {"qvf_version": 1,
                "source": {"program": "t", "version": "1", "calculation": "c"},
                "sections": [{"id": "structure", "kind": "structure", "members": {
                    "structure": _member("s/structure.json", struct_doc)}},
                    {"id": "v", "kind": kind, "members": members}]}
    path = str(tmp_path / "raw.qvf")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, raw in files.items():
            zf.writestr(name, raw)
    return validate_qvf(path)


# --- writer ---------------------------------------------------------------------

class TestWriter:
    def test_new_kinds_round_trip(self, tmp_path):
        pytest.importorskip("jsonschema")
        w = QvfWriter("t", "1", "new kinds", auto_metadata=False)
        w.add_structure(SODIUM)
        vec = np.arange(2 * 3 * 4 * 3, dtype=np.float64).reshape(2, 3, 4, 3)
        w.add_volume("volume.vector", vec, [0, 0, 0], EYE, dtype="float64",
                     units={"data": "dimensionless"}, section_id="vec")
        psi = np.arange(24.0).reshape(2, 3, 4) * (1 - 2j)
        w.add_volume("volume.complex", psi, [0, 0, 0], EYE, dtype="float64",
                     section_id="psi")
        w.add_trajectory({"symbols": ["Na"]}, np.zeros((6, 1, 3)))
        series = np.arange(3 * 2 * 3 * 4, dtype=np.float32).reshape(3, 2, 3, 4)
        w.add_volume("volume.series", series, [0, 0, 0], EYE, section_id="ser",
                     axis={"kind": "frame", "values": [0, 2.0, 5],
                           "labels": ["a", "b", "c"],
                           "trajectory_ref": "trajectory", "x_note": "kept"})
        w.add_volume("volume.laplacian", np.zeros((2, 3, 4)), [0, 0, 0], EYE,
                     section_id="lap")
        report = _validate(w, tmp_path)
        assert report["ok"] and not report["warnings"], report["findings"]
        with QvfReader(str(tmp_path / "a.qvf")) as r:
            by_id = {s["id"]: s for s in r.sections}
            assert np.array_equal(r.read_array(by_id["vec"]["members"]["data"]), vec)
            got = r.read_array(by_id["psi"]["members"]["data"])
            assert got.shape == (2, 3, 4, 2)
            assert np.array_equal(got[..., 0], psi.real)
            assert np.array_equal(got[..., 1], psi.imag)
            assert r.read_json(by_id["vec"]["members"]["grid"])["shape"] == [2, 3, 4]
            assert r.read_json(by_id["ser"]["members"]["grid"])["shape"] == [2, 3, 4]
            axis = r.read_json(by_id["ser"]["members"]["axis"])
            assert axis == {"kind": "frame", "values": [0, 2, 5],
                            "labels": ["a", "b", "c"],
                            "trajectory_ref": "trajectory", "x_note": "kept"}
            assert by_id["ser"]["members"]["axis"]["path"] == "volumes/ser_axis.json"

    def test_grid_fields_written(self, tmp_path):
        w = _periodic_writer(endpoint=True, shape=(5, 5, 5),
                             structure_ref="structure")
        report = _validate(w, tmp_path)
        assert report["ok"], report["findings"]
        with QvfReader(str(tmp_path / "a.qvf")) as r:
            grid = r.read_json(r.sections[1]["members"]["grid"])
        assert grid["periodic"] == [True, True, True]
        assert grid["includes_endpoint"] is True
        assert grid["structure_ref"] == "structure"

    def test_absent_grid_fields_are_not_written(self):
        w = QvfWriter("t", "1", "c")
        w.add_volume("volume.density", np.zeros((2, 2, 2)), [0, 0, 0], EYE)
        grid = json.loads(next(v for k, v in w._files.items() if k.endswith("_grid.json")))
        assert set(grid) == {"origin", "voxel_vectors", "shape"}

    @pytest.mark.parametrize("kind, shape", [
        ("volume.vector", (2, 2, 2)), ("volume.vector", (2, 2, 2, 2)),
        ("volume.complex", (2, 2, 2, 3)), ("volume.complex", (2, 2, 2, 2, 2)),
        ("volume.series", (2, 2, 2)), ("volume.laplacian", (2, 2, 2, 3)),
        ("volume.density", (2, 2, 2, 1)),
    ])
    def test_wrong_rank_or_trailing_axis_refused(self, kind, shape):
        w = QvfWriter("t", "1", "c")
        axis = ({"kind": "custom", "values": list(range(shape[0]))}
                if kind == "volume.series" else None)
        with pytest.raises(ValueError):
            w.add_volume(kind, np.zeros(shape), [0, 0, 0], EYE, axis=axis)
        assert not w._sections and not w._files

    @pytest.mark.parametrize("axis, why", [
        (None, "needs axis"),
        ({"kind": "epoch", "values": [0, 1]}, "kind"),
        ({"kind": "time"}, "values"),
        ({"kind": "time", "values": [0.0]}, "1 values"),
        ({"kind": "time", "values": [0, 1], "labels": ["only one"]}, "labels"),
        ({"kind": "time", "values": [0, 1], "units": "femtoseconds"}, "unit name"),
        ({"kind": "frame", "values": [0, 1.5]}, "frame indices"),
        ({"kind": "frame", "values": [-1, 0]}, "frame indices"),
        ({"kind": "frame", "values": [0, 1], "trajectory_ref": "structure"},
         "trajectory_ref"),
        ({"kind": "time", "values": [0, 1], "step": 1}, "unknown keys"),
    ])
    def test_series_axis_refusals(self, axis, why):
        w = QvfWriter("t", "1", "c")
        w.add_structure(SODIUM)
        with pytest.raises(ValueError, match=why):
            w.add_volume("volume.series", np.zeros((2, 2, 2, 2)), [0, 0, 0], EYE,
                         axis=axis)
        assert [s["kind"] for s in w._sections] == ["structure"]

    def test_axis_only_on_series(self):
        w = QvfWriter("t", "1", "c")
        with pytest.raises(ValueError, match="only volume.series"):
            w.add_volume("volume.density", np.zeros((2, 2, 2)), [0, 0, 0], EYE,
                         axis={"kind": "time", "values": [0]})

    @pytest.mark.parametrize("kwargs, why", [
        ({"periodic": [True, False]}, "three booleans"),
        ({"periodic": [1, 0, 0]}, "three booleans"),
        ({"includes_endpoint": "yes"}, "boolean"),
        ({"structure_ref": "nowhere"}, "structure_ref"),
    ])
    def test_grid_field_refusals(self, kwargs, why):
        w = QvfWriter("t", "1", "c")
        w.add_structure(SODIUM)
        with pytest.raises(ValueError, match=why):
            w.add_volume("volume.density", np.zeros((2, 2, 2)), [0, 0, 0], EYE,
                         **kwargs)

    def test_unknown_kind_refused(self):
        with pytest.raises(ValueError, match="not a volume kind"):
            QvfWriter("t", "1", "c").add_volume("volume.tensor", np.zeros((2, 2, 2)),
                                                [0, 0, 0], EYE)


# --- validator: data shapes and the series axis ----------------------------------

@pytest.mark.parametrize("kind, shape", [
    ("volume.vector", [2, 2, 2, 2]), ("volume.vector", [2, 2, 2]),
    ("volume.complex", [2, 2, 2, 3]), ("volume.series", [2, 2, 2]),
    ("volume.laplacian", [2, 2, 2, 1]),
])
def test_data_shape_rule(tmp_path, kind, shape):
    axis = {"kind": "custom", "values": [0] * shape[0]} if kind == "volume.series" else None
    report = _raw_volume(tmp_path, kind, shape, axis=axis, grid_shape=[2, 2, 2])
    assert _codes(report) == {"E_MEMBER_MALFORMED"}, report["findings"]
    assert _where(report, "E_MEMBER_MALFORMED") == ["/sections/1/members/data"]


@pytest.mark.parametrize("kind, shape", [
    ("volume.vector", [2, 3, 4, 3]), ("volume.complex", [2, 3, 4, 2]),
    ("volume.series", [5, 2, 3, 4]), ("volume.laplacian", [2, 3, 4]),
])
def test_data_shape_accepted(tmp_path, kind, shape):
    pytest.importorskip("jsonschema")
    axis = {"kind": "custom", "values": [0] * shape[0]} if kind == "volume.series" else None
    report = _raw_volume(tmp_path, kind, shape, axis=axis)
    assert report["ok"] and not report["warnings"], report["findings"]


def test_vector_trailing_axis_is_also_a_schema_error(tmp_path):
    pytest.importorskip("jsonschema")
    report = _raw_volume(tmp_path, "volume.vector", [2, 2, 2, 2])
    assert {f["code"] for f in report["findings"]} == {"E_SCHEMA", "E_MEMBER_MALFORMED"}


@pytest.mark.parametrize("axis, code", [
    ({"kind": "time", "values": [0.0, 1.0], "units": "fs"}, "E_MEMBER_MALFORMED"),
    ({"kind": "state", "values": [1, 2, 3], "labels": ["S1", "S2"]},
     "E_MEMBER_MALFORMED"),
    ({"kind": "frame", "values": [0, 1, 2], "trajectory_ref": "structure"},
     "E_REF_UNRESOLVED"),
    ({"kind": "frame", "values": [0, 1, 2], "trajectory_ref": "nowhere"},
     "E_REF_UNRESOLVED"),
])
def test_series_axis_rules(tmp_path, axis, code):
    report = _raw_volume(tmp_path, "volume.series", [3, 2, 2, 2], axis=axis)
    assert _codes(report) == {code}, report["findings"]
    assert _where(report, code) == ["/sections/1/members/axis"]


def test_series_axis_payload_schema(tmp_path):
    pytest.importorskip("jsonschema")
    for axis in ({"kind": "frame", "values": [0, 0.5, 1]},     # not frame indices
                 {"kind": "time", "values": [0, 1, 2], "step": 1},   # strict
                 {"values": [0, 1, 2]}):                       # kind required
        report = _raw_volume(tmp_path, "volume.series", [3, 2, 2, 2], axis=axis)
        assert {f["code"] for f in report["findings"]} == {"E_PAYLOAD_SCHEMA"}, axis
    report = _raw_volume(tmp_path, "volume.series", [3, 2, 2, 2],
                         axis={"kind": "time", "values": [0, 1, 2], "units": "sec"})
    assert {f["code"] for f in report["findings"]} == {"W_UNIT_UNKNOWN",
                                                       "E_PAYLOAD_SCHEMA"}
    assert _where(report, "W_UNIT_UNKNOWN") == ["/sections/1/members/axis"]


def test_series_axis_may_name_a_reaction_path(tmp_path):
    w = QvfWriter("t", "1", "c", auto_metadata=False)
    w.add_reaction_path({"symbols": ["Na"]}, np.zeros((3, 1, 3)), section_id="path")
    w.add_volume("volume.series", np.zeros((2, 2, 2, 2)), [0, 0, 0], EYE,
                 axis={"kind": "frame", "values": [0, 2], "trajectory_ref": "path"})
    report = _validate(w, tmp_path)
    assert report["ok"], report["findings"]


# --- validator: periodic grids ----------------------------------------------------

class TestPeriodicGrid:
    @pytest.mark.parametrize("endpoint, shape", [(False, (4, 4, 4)), (True, (5, 5, 5)),
                                                 (False, (6, 6, 8)), (True, (7, 7, 9))])
    def test_spanning_grids_validate(self, tmp_path, endpoint, shape):
        w = _periodic_writer(rows=HEXAGONAL, shape=shape, endpoint=endpoint)
        report = _validate(w, tmp_path)
        assert report["ok"] and not report["warnings"], report["findings"]

    def test_endpoint_mislabelled(self, tmp_path):
        """CHGCAR numbers (voxel × shape = cell) declared cube style."""
        vox = _vox(CUBIC, (4, 4, 4), endpoint=False)
        w = _periodic_writer(vox=vox, endpoint=True)
        report = _validate(w, tmp_path)
        assert _codes(report) == {"E_MEMBER_MALFORMED"}
        assert _where(report, "E_MEMBER_MALFORMED") == ["/sections/1/members/grid"] * 3
        # The same numbers declared CHGCAR style are fine.
        assert _validate(_periodic_writer(vox=vox, endpoint=False), tmp_path)["ok"]

    def test_default_endpoint_is_cube_style(self, tmp_path):
        vox = _vox(CUBIC, (4, 4, 4), endpoint=True)
        w = QvfWriter("t", "1", "c", auto_metadata=False)
        w.add_structure(SODIUM, pbc=[True] * 3, lattice_vectors=CUBIC)
        w.add_volume("volume.density", np.zeros((4, 4, 4)), [0, 0, 0], vox,
                     periodic=[True, True, True])
        assert _validate(w, tmp_path)["ok"]

    def test_tolerance_is_relative(self, tmp_path):
        good = _vox(CUBIC, (4, 4, 4), endpoint=False)
        near = [[x * (1 + 5e-7) for x in row] for row in good]
        far = [[x * (1 + 2e-6) for x in row] for row in good]
        assert _validate(_periodic_writer(vox=near), tmp_path)["ok"]
        assert _codes(_validate(_periodic_writer(vox=far), tmp_path)) == \
            {"E_MEMBER_MALFORMED"}

    def test_span_is_compared_as_a_vector(self, tmp_path):
        """A step of the right length in the wrong direction is wrong."""
        good = _vox(HEXAGONAL, (4, 4, 4), endpoint=False)
        swapped = [[good[1][1], good[1][0], 0.0], good[0], good[2]]
        report = _validate(_periodic_writer(rows=HEXAGONAL, vox=swapped), tmp_path)
        assert _codes(report) == {"E_MEMBER_MALFORMED"}
        assert len(_where(report, "E_MEMBER_MALFORMED")) == 2

    def test_only_periodic_axes_are_checked(self, tmp_path):
        vox = _vox(CUBIC, (4, 4, 4), endpoint=False)
        vox[2] = [0.0, 0.0, 0.3]                         # a finite box along c
        w = _periodic_writer(vox=vox, pbc=(True, True, False),
                             periodic=(True, True, False))
        assert _validate(w, tmp_path)["ok"]

    def test_periodic_axis_must_be_periodic_in_the_structure(self, tmp_path):
        w = _periodic_writer(pbc=(True, True, False))
        report = _validate(w, tmp_path)
        assert _codes(report) == {"E_MEMBER_MALFORMED"}
        assert any("pbc[2] false" in f["message"] for f in report["findings"])

    def test_periodic_grid_of_a_molecule(self, tmp_path):
        w = QvfWriter("t", "1", "c", auto_metadata=False)
        w.add_structure(SODIUM)
        w.add_volume("volume.density", np.zeros((2, 2, 2)), [0, 0, 0], EYE,
                     periodic=[False, True, False])
        assert _codes(_validate(w, tmp_path)) == {"E_MEMBER_MALFORMED"}

    def test_structure_comes_later_in_the_manifest(self, tmp_path):
        vox = _vox(CUBIC, (4, 4, 4), endpoint=True)
        w = QvfWriter("t", "1", "c", auto_metadata=False)
        w.add_volume("volume.density", np.zeros((4, 4, 4)), [0, 0, 0], vox,
                     periodic=[True] * 3, includes_endpoint=False)
        w.add_structure(SODIUM, pbc=[True] * 3, lattice_vectors=CUBIC)
        report = _validate(w, tmp_path)
        assert _where(report, "E_MEMBER_MALFORMED") == ["/sections/0/members/grid"] * 3

    def test_structure_resolution(self, tmp_path):
        """Section structure_ref, then grid structure_ref, then the only
        structure; with two structures and no reference nothing is checked."""
        small = [[3.0, 0, 0], [0, 3.0, 0], [0, 0, 3.0]]
        vox = _vox(CUBIC, (4, 4, 4), endpoint=False)

        def writer(**kw):
            w = QvfWriter("t", "1", "c", auto_metadata=False)
            w.add_structure(SODIUM, pbc=[True] * 3, lattice_vectors=CUBIC,
                            section_id="big")
            w.add_structure(SODIUM, pbc=[True] * 3, lattice_vectors=small,
                            section_id="small")
            w.add_volume("volume.density", np.zeros((4, 4, 4)), [0, 0, 0], vox,
                         periodic=[True] * 3, includes_endpoint=False,
                         section_id="rho", **kw)
            return w

        assert _validate(writer(), tmp_path)["ok"]                  # unresolved
        assert _validate(writer(structure_ref="big"), tmp_path)["ok"]
        assert not _validate(writer(structure_ref="small"), tmp_path)["ok"]
        w = writer(structure_ref="small")
        w.annotate_section("rho", structure_ref="big")      # section-level wins
        assert _validate(w, tmp_path)["ok"]

    def test_grid_structure_ref_must_name_a_structure(self, tmp_path):
        w = QvfWriter("t", "1", "c", auto_metadata=False)
        w.add_structure(SODIUM)
        w.add_trajectory({"symbols": ["Na"]}, np.zeros((1, 1, 3)))
        w.add_volume("volume.density", np.zeros((2, 2, 2)), [0, 0, 0], EYE,
                     structure_ref="structure", section_id="rho")
        grid_path = "volumes/rho_grid.json"
        doc = json.loads(w._files[grid_path])
        doc["structure_ref"] = "trajectory"
        w._files[grid_path] = json.dumps(doc).encode()
        w._sections[-1]["members"]["grid"]["sha256"] = hashlib.sha256(
            w._files[grid_path]).hexdigest()
        w._sections[-1]["members"]["grid"]["size"] = len(w._files[grid_path])
        report = _validate(w, tmp_path)
        assert _codes(report) == {"E_REF_UNRESOLVED"}
        assert _where(report, "E_REF_UNRESOLVED") == ["/sections/2/members/grid"]


# --- corpus properties, read from the archives -------------------------------------

def _corpus(name):
    path = os.path.join(_CORPUS, name)
    if not os.path.exists(path):
        pytest.skip("conformance corpus not present (standalone checkout)")
    return QvfReader(path)


def test_volume_series_axis_matches_its_slabs_and_trajectory():
    with _corpus("volume_series.qvf") as r:
        by_id = {s["id"]: s for s in r.sections}
        series = by_id["rho_frames"]
        axis = r.read_json(series["members"]["axis"])
        n = series["members"]["data"]["shape"][0]
        assert len(axis["values"]) == len(axis["labels"]) == n
        traj = by_id[axis["trajectory_ref"]]
        n_frames = traj["members"]["coords"]["shape"][0]
        assert axis["kind"] == "frame"
        assert all(0 <= v < n_frames for v in axis["values"])


def test_volume_complex_is_the_m_plus_one_orbital():
    with _corpus("volume_complex.qvf") as r:
        s = r.sections[1]
        grid = r.read_json(s["members"]["grid"])
        psi = r.read_array(s["members"]["data"])
        i, j, k = 1, 3, 2
        x, y, z = (grid["origin"][a] + (i, j, k)[a] * grid["voxel_vectors"][a][a]
                   for a in range(3))
        radial = math.exp(-0.5 * math.sqrt(x * x + y * y + z * z)) / (8 * math.sqrt(math.pi))
        assert psi[i, j, k, 0] == pytest.approx(x * radial, abs=1e-15)
        assert psi[i, j, k, 1] == pytest.approx(y * radial, abs=1e-15)


# --- constants and prose ---------------------------------------------------------

def test_reader_conversion_factor_is_the_writers():
    assert qvf_reader._BOHR_PER_ANGSTROM == qvf_writer.BOHR_PER_ANGSTROM


def test_spec_states_the_endpoint_rule():
    if not os.path.exists(_SPEC):
        pytest.skip("spec not present (standalone checkout)")
    with open(_SPEC, encoding="utf-8") as fh:
        spec = fh.read()
    section = spec.split("### 5.2 `volume.*`", 1)[1].split("\n### 5.3", 1)[0]
    for needle in ("includes_endpoint", "**MUST** drop the duplicated plane", "CHGCAR",
                   "`volume.series`",
                   "VolumeSeriesAxisPayload", "`volume.laplacian`"):
        assert needle in section, needle
    table = spec.split("## 5. Canonical section kinds", 1)[1].split("### 5.1", 1)[0]
    for kind in ("volume.vector", "volume.complex", "volume.series",
                 "volume.laplacian"):
        assert f"`{kind}`" in table or f"`.{kind.split('.')[1]}`" in table, kind
