"""Trajectory extensions (spec § 4.3, § 5.5; P12, D06).

Covers the optional per-frame members of ``trajectory`` (``lattice`` in rows,
Å; ``velocities``; ``gradient``; ``times``; binary ``energies``;
``cell_volumes``; ``temperatures``) and the shared ones of ``reaction.path``,
float32 ``coords`` with ``metadata.precision``, the metadata fields
``ensemble``, ``timestep_fs`` and ``pbc``, the writer (round trips and
refusals), the schema, and the validator rules JSON Schema cannot express,
all reported as ``E_MEMBER_MALFORMED``.
"""

import hashlib
import io
import json
import os
import sys
import zipfile

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))

import qvf_reader  # noqa: E402
from qvf_reader import QvfReader, validate_qvf  # noqa: E402
from qvf_writer import BOHR_PER_ANGSTROM, Lattice, QvfWriter  # noqa: E402

_SCHEMA_CODES = {"E_SCHEMA", "E_PAYLOAD_SCHEMA", "W_SCHEMA_SKIPPED"}
SYMBOLS = ["O", "H", "H"]
N_FRAMES, N_ATOMS = 4, 3
COORDS = (np.arange(N_FRAMES * N_ATOMS * 3, dtype=np.float64)
          .reshape(N_FRAMES, N_ATOMS, 3) * 0.1)
# A non-symmetric cell, so rows and columns differ.
ROWS = [[6.0, 0.0, 0.0], [0.5, 5.5, 0.0], [0.25, 0.75, 7.0]]


def _codes(report):
    return {f["code"] for f in report["findings"]} - _SCHEMA_CODES


def _where(report, code="E_MEMBER_MALFORMED"):
    return sorted(f["where"] for f in report["findings"] if f["code"] == code)


# --- raw archives, so the validator sees what the writer would refuse ----------

def _raw_archive(path, kind="trajectory", meta=None, members=None,
                 coords_dtype="float64"):
    """A one-section archive of ``kind`` with ``coords`` (``COORDS`` in
    ``coords_dtype``), a ``metadata`` member (``meta``) and binary
    ``members``: role -> array (written as float64 with its own shape)."""
    meta = {"symbols": SYMBOLS} if meta is None else meta
    files, specs = {}, {}

    def add(role, data, fmt, dtype=None, shape=None):
        p = f"s/{role}.{'json' if fmt == 'json' else 'bin'}"
        files[p] = data
        spec = {"path": p, "format": fmt,
                "sha256": hashlib.sha256(data).hexdigest()}
        if dtype is not None:
            spec["dtype"], spec["shape"] = dtype, list(shape)
        specs[role] = spec

    add("metadata", json.dumps(meta).encode("utf-8"), "json")
    c = COORDS.astype("<f4" if coords_dtype == "float32" else "<f8")
    add("coords", c.tobytes(), "binary", coords_dtype, c.shape)
    for role, arr in (members or {}).items():
        a = np.asarray(arr, dtype="<f8")
        add(role, a.tobytes(), "binary", "float64", a.shape)
    manifest = {"qvf_version": 1,
                "source": {"program": "t", "version": "1", "calculation": "md"},
                "sections": [{"id": "s", "kind": kind, "members": specs}]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        zf.writestr("manifest.json", json.dumps(manifest))
    with open(path, "wb") as fh:
        fh.write(buf.getvalue())
    return str(path)


def _frames(n=N_FRAMES):
    return np.linspace(0.0, 1.0, n)


def _vectors(n_frames=N_FRAMES, n_atoms=N_ATOMS):
    return np.full((n_frames, n_atoms, 3), 0.01)


# --- writer: round trips -----------------------------------------------------

def _md_writer(**kw):
    w = QvfWriter("t", "1", "md", auto_metadata=False)
    cells = [Lattice.from_rows_angstrom(np.array(ROWS) * (1 + 0.01 * k))
             for k in range(N_FRAMES)]
    energies = [-76.3 - 0.001 * k for k in range(N_FRAMES)]
    args = dict(lattice=cells, velocities=_vectors(), gradient=-_vectors(),
                times=[0.5 * k for k in range(N_FRAMES)], energies=energies,
                cell_volumes=[c.volume_angstrom3() for c in cells],
                temperatures=[300.0, 302.0, 298.5, 301.0], precision="float32")
    args.update(kw)
    w.add_trajectory({"symbols": SYMBOLS, "kind": "md", "ensemble": "npt",
                      "timestep_fs": 0.5, "pbc": [True, True, True],
                      "energies": energies}, COORDS, **args)
    return w, cells


def test_md_trajectory_round_trips(tmp_path):
    w, cells = _md_writer()
    path = str(tmp_path / "md.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"] and not report["warnings"], report["findings"]
    with QvfReader(path) as r:
        members = r.sections[0]["members"]
        assert list(members) == ["metadata", "coords", "lattice", "velocities",
                                 "gradient", "times", "energies",
                                 "cell_volumes", "temperatures"]
        meta = r.read_json(members["metadata"])
        assert meta["precision"] == "float32"
        assert meta["ensemble"] == "npt" and meta["timestep_fs"] == 0.5
        assert members["coords"]["dtype"] == "float32"
        coords = r.read_array(members["coords"])
        assert coords.dtype == np.float32
        assert np.allclose(coords, COORDS, atol=1e-6)
        lat = r.read_array(members["lattice"])
        assert members["lattice"]["shape"] == [N_FRAMES, 3, 3]
        # Rows in Å, the structure convention: no transpose, no bohr factor.
        assert np.array_equal(lat[2], np.asarray(cells[2].rows_angstrom()))
        assert lat[0][1][0] == pytest.approx(0.5)
        for role in ("velocities", "gradient", "times", "energies",
                     "cell_volumes", "temperatures"):
            assert members[role]["dtype"] == "float64", role
        assert np.allclose(r.read_array(members["energies"]), meta["energies"])
        assert r.read_array(members["cell_volumes"])[1] == pytest.approx(
            cells[1].volume_angstrom3())


def test_trajectory_lattice_forms(tmp_path):
    meta = {"symbols": SYMBOLS, "pbc": [True, True, True]}
    fixed = Lattice.from_rows_angstrom(ROWS)
    w = QvfWriter("t", "1", auto_metadata=False)
    w.add_trajectory(meta, COORDS, lattice=fixed, section_id="fixed")
    w.add_trajectory(meta, COORDS, lattice=ROWS, section_id="array")
    w.add_trajectory(meta, COORDS, lattice=np.stack([ROWS] * N_FRAMES),
                     section_id="frames")
    path = str(tmp_path / "lat.qvf")
    w.write(path)
    assert validate_qvf(path)["ok"]
    with QvfReader(path) as r:
        by_id = {s["id"]: s for s in r.sections}
        for sid in ("fixed", "array"):
            lat = r.read_array(by_id[sid]["members"]["lattice"])
            assert lat.shape == (3, 3) and np.array_equal(lat, np.array(ROWS))
        assert r.read_array(by_id["frames"]["members"]["lattice"]).shape == (
            N_FRAMES, 3, 3)


def test_trajectory_and_reaction_path_lattice_conventions_differ(tmp_path):
    """The same Lattice is rows in Å on a trajectory and columns in bohr on a
    reaction path (spec § 4.3, "Lattice conventions")."""
    cell = Lattice.from_rows_angstrom(ROWS)
    w = QvfWriter("t", "1", auto_metadata=False)
    w.add_trajectory({"symbols": SYMBOLS, "pbc": [True] * 3}, COORDS,
                     lattice=cell, section_id="traj")
    w.add_reaction_path({"symbols": SYMBOLS}, COORDS, lattice=cell,
                        section_id="path")
    path = str(tmp_path / "conv.qvf")
    w.write(path)
    assert validate_qvf(path)["ok"]
    with QvfReader(path) as r:
        by_id = {s["id"]: s for s in r.sections}
        rows = r.read_array(by_id["traj"]["members"]["lattice"])
        cols = r.read_array(by_id["path"]["members"]["lattice"])
    assert np.allclose(cols, rows.T * BOHR_PER_ANGSTROM)
    assert np.allclose(Lattice.from_columns_bohr(cols).rows_angstrom(), rows)


def test_reaction_path_shared_members(tmp_path):
    w = QvfWriter("t", "1", auto_metadata=False)
    energies = [-1.0, -1.1, -1.05, -1.2]
    w.add_reaction_path({"symbols": SYMBOLS, "energies": energies}, COORDS,
                        velocities=_vectors(), gradient=_vectors(),
                        times=_frames(), energies=energies)
    path = str(tmp_path / "rp.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"] and not report["warnings"], report["findings"]
    with QvfReader(path) as r:
        assert list(r.sections[0]["members"]) == [
            "metadata", "coords", "velocities", "gradient", "times", "energies"]


def test_precision_in_metadata_writes_float32(tmp_path):
    w = QvfWriter("t", "1", auto_metadata=False)
    w.add_trajectory({"symbols": SYMBOLS, "precision": "float32"}, COORDS)
    w.add_trajectory({"symbols": SYMBOLS}, COORDS, precision="float64",
                     section_id="explicit64")
    path = str(tmp_path / "p.qvf")
    w.write(path)
    assert validate_qvf(path)["ok"]
    with QvfReader(path) as r:
        by_id = {s["id"]: s for s in r.sections}
        assert by_id["trajectory"]["members"]["coords"]["dtype"] == "float32"
        assert by_id["explicit64"]["members"]["coords"]["dtype"] == "float64"
        assert r.read_json(by_id["explicit64"]["members"]["metadata"])[
            "precision"] == "float64"


def test_declared_trajectory_units(tmp_path):
    w = QvfWriter("t", "1", auto_metadata=False)
    w.add_trajectory({"symbols": SYMBOLS, "pbc": [True] * 3}, COORDS,
                     lattice=ROWS, times=_frames(),
                     units={"lattice": "angstrom", "times": "fs",
                            "cell_volumes": "a3", "temperatures": "kelvin",
                            "timestep_fs": "fs"})
    path = str(tmp_path / "u.qvf")
    w.write(path)
    report = validate_qvf(path)
    assert report["ok"] and not report["warnings"], report["findings"]


# --- writer: refusals ---------------------------------------------------------

_META = {"symbols": SYMBOLS}
_PBC = {"symbols": SYMBOLS, "pbc": [True, True, True]}


@pytest.mark.parametrize("meta,kwargs,match", [
    (_META, {"lattice": ROWS}, "pbc is REQUIRED"),
    ({"symbols": SYMBOLS, "pbc": [True, False, False]}, {}, "lattice is required"),
    ({"symbols": SYMBOLS, "pbc": [True, False]}, {"lattice": ROWS}, "three booleans"),
    (_PBC, {"lattice": np.zeros((N_FRAMES + 1, 3, 3))}, "frames"),
    (_PBC, {"lattice": np.zeros((3, 4))}, r"\[3, 3\] or \[n_frames, 3, 3\]"),
    (_PBC, {"lattice": [Lattice.from_rows_angstrom(ROWS), ROWS]}, "only Lattice"),
    (_META, {"velocities": _vectors(N_FRAMES + 1)}, "velocities must be"),
    (_META, {"gradient": _vectors(n_atoms=2)}, "gradient must be"),
    (_META, {"times": _frames(N_FRAMES - 1)}, "times must be"),
    (_META, {"cell_volumes": np.zeros((N_FRAMES, 1))}, "cell_volumes must be"),
    (_META, {"temperatures": ["hot"] * N_FRAMES}, "real numbers"),
    ({"symbols": SYMBOLS, "energies": [0.0] * N_FRAMES},
     {"energies": [0.0, 0.0, 0.0, 1e-9]}, "agree within 1e-10"),
    ({"symbols": SYMBOLS, "energies": [0.0] * 3},
     {"energies": [0.0] * N_FRAMES}, "agree within 1e-10"),
    (_META, {"precision": "float16"}, "'float64' or 'float32'"),
    ({"symbols": SYMBOLS, "precision": "float64"}, {"precision": "float32"},
     "contradicts"),
    (_META, {"units": {"lattice": "bohr"}}, "must be 'angstrom'"),
    (_META, {"units": {"times": "ps"}}, "must be 'fs'"),
])
def test_add_trajectory_refuses(meta, kwargs, match):
    w = QvfWriter("t", "1", auto_metadata=False)
    with pytest.raises((ValueError, TypeError), match=match):
        w.add_trajectory(meta, COORDS, **kwargs)
    # Nothing was written: the id is still free and no member exists.
    assert not w._sections and not w._files
    w.add_trajectory({"symbols": SYMBOLS}, COORDS)


@pytest.mark.parametrize("meta,kwargs,match", [
    ({"symbols": SYMBOLS, "precision": "float32"}, {}, "float64 coords"),
    (_META, {"velocities": _vectors(N_FRAMES - 1)}, "velocities must be"),
    ({"symbols": SYMBOLS, "energies": [0.0] * N_FRAMES},
     {"energies": [1.0] * N_FRAMES}, "agree within"),
    (_META, {"lattice": np.zeros((2, 3, 3))}, "frames"),
])
def test_add_reaction_path_refuses(meta, kwargs, match):
    w = QvfWriter("t", "1", auto_metadata=False)
    with pytest.raises(ValueError, match=match):
        w.add_reaction_path(meta, COORDS, **kwargs)
    assert not w._sections and not w._files


def test_reaction_path_has_no_trajectory_only_members():
    w = QvfWriter("t", "1")
    with pytest.raises(TypeError):
        w.add_reaction_path(_META, COORDS, cell_volumes=_frames())


# --- validator ------------------------------------------------------------------

def test_raw_archive_baseline_is_valid(tmp_path):
    path = _raw_archive(tmp_path / "ok.qvf",
                        meta={"symbols": SYMBOLS, "pbc": [True, True, False],
                              "energies": list(_frames())},
                        members={"lattice": ROWS, "velocities": _vectors(),
                                 "gradient": _vectors(), "times": _frames(),
                                 "energies": _frames(),
                                 "cell_volumes": _frames(),
                                 "temperatures": _frames()})
    report = validate_qvf(path)
    assert report["ok"] and not report["warnings"], report["findings"]


@pytest.mark.parametrize("kind,meta,members,dtype,where", [
    # float32 coords need metadata.precision float32, and precision names the dtype.
    ("trajectory", None, {}, "float32", "coords"),
    ("trajectory", {"symbols": SYMBOLS, "precision": "float32"}, {}, "float64",
     "coords"),
    ("reaction.path", None, {}, "float32", "coords"),
    # Per-frame extents against coords.
    ("trajectory", None, {"velocities": _vectors(N_FRAMES + 1)}, "float64",
     "velocities"),
    ("trajectory", None, {"gradient": _vectors(n_atoms=2)}, "float64",
     "gradient"),
    ("trajectory", None, {"velocities": np.zeros((N_FRAMES, N_ATOMS))},
     "float64", "velocities"),
    ("trajectory", None, {"times": _frames(N_FRAMES - 1)}, "float64", "times"),
    ("trajectory", None, {"energies": _frames(N_FRAMES + 2)}, "float64",
     "energies"),
    ("trajectory", None, {"cell_volumes": _frames(1)}, "float64",
     "cell_volumes"),
    ("trajectory", None, {"temperatures": np.zeros((N_FRAMES, 1))}, "float64",
     "temperatures"),
    ("reaction.path", None, {"gradient": _vectors(N_FRAMES - 1)}, "float64",
     "gradient"),
    ("reaction.path", None, {"times": _frames(2)}, "float64", "times"),
    # Lattice: [3, 3] or [n_frames, 3, 3], on both kinds.
    ("trajectory", {"symbols": SYMBOLS, "pbc": [True] * 3},
     {"lattice": np.zeros((N_FRAMES - 1, 3, 3))}, "float64", "lattice"),
    ("reaction.path", None, {"lattice": np.zeros((N_FRAMES + 1, 3, 3))},
     "float64", "lattice"),
    # Binary energies against metadata.energies.
    ("trajectory", {"symbols": SYMBOLS, "energies": [0.0, 0.0, 0.0, 0.0]},
     {"energies": [0.0, 0.0, 2e-10, 0.0]}, "float64", "energies"),
    ("reaction.path", {"symbols": SYMBOLS, "energies": [0.0, 0.0, 0.0]},
     {"energies": [0.0, 0.0, 0.0, 0.0]}, "float64", "energies"),
    ("trajectory", {"symbols": SYMBOLS, "energies": [0.0, 0.0, 0.0, 0.0]},
     {"energies": [0.0, float("nan"), 0.0, 0.0]}, "float64", "energies"),
    # A trajectory lattice needs pbc, and a periodic pbc needs the lattice.
    ("trajectory", None, {"lattice": ROWS}, "float64", "metadata"),
    ("trajectory", {"symbols": SYMBOLS, "pbc": [False, True, False]}, {},
     "float64", "metadata"),
])
def test_validator_rule(tmp_path, kind, meta, members, dtype, where):
    path = _raw_archive(tmp_path / "bad.qvf", kind=kind, meta=meta,
                        members=members, coords_dtype=dtype)
    report = validate_qvf(path)
    assert not report["ok"]
    assert _codes(report) == {"E_MEMBER_MALFORMED"}, report["findings"]
    assert _where(report) == [f"/sections/0/members/{where}"], report["findings"]


@pytest.mark.parametrize("kind,meta,members", [
    # Energies that agree within 1e-10 hartree.
    ("trajectory", {"symbols": SYMBOLS, "energies": [-76.0, -76.1, -76.2, -76.3]},
     {"energies": [-76.0, -76.1 + 5e-11, -76.2, -76.3]}),
    # Without metadata.energies there is nothing to compare.
    ("trajectory", None, {"energies": _frames()}),
    # A reaction path signals periodicity by its lattice; no pbc needed.
    ("reaction.path", None, {"lattice": np.stack([ROWS] * N_FRAMES)}),
    # pbc all false with a lattice is allowed (bookkeeping rows, spec § 5.1).
    ("trajectory", {"symbols": SYMBOLS, "pbc": [False] * 3}, {"lattice": ROWS}),
])
def test_validator_accepts(tmp_path, kind, meta, members):
    path = _raw_archive(tmp_path / "ok.qvf", kind=kind, meta=meta,
                        members=members)
    report = validate_qvf(path)
    assert report["ok"] and not report["warnings"], report["findings"]


def test_rules_run_without_the_schema_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(qvf_reader, "_load_schema_validator", lambda: None)
    monkeypatch.setattr(qvf_reader, "_load_payload_validator", lambda _d: None)
    path = _raw_archive(tmp_path / "bad.qvf", coords_dtype="float32",
                        members={"velocities": _vectors(N_FRAMES + 1)})
    report = validate_qvf(path)
    assert _where(report) == ["/sections/0/members/coords",
                              "/sections/0/members/velocities"]


def test_unreadable_metadata_is_not_judged_twice(tmp_path):
    """With a metadata member that does not parse, only its own finding and
    the shape rules remain."""
    path = _raw_archive(tmp_path / "bad.qvf", coords_dtype="float32",
                        members={"lattice": ROWS})
    with zipfile.ZipFile(path) as zf:
        entries = {n: zf.read(n) for n in zf.namelist()}
    entries["s/metadata.json"] = b"{not json"
    manifest = json.loads(entries["manifest.json"])
    manifest["sections"][0]["members"]["metadata"]["sha256"] = \
        hashlib.sha256(b"{not json").hexdigest()
    entries["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as zf:
        for n, d in entries.items():
            zf.writestr(n, d)
    report = validate_qvf(path)
    assert _codes(report) == {"E_JSON_INVALID"}, report["findings"]


# --- schema ----------------------------------------------------------------------

def _payload_errors(defname, doc):
    pytest.importorskip("jsonschema")
    v = qvf_reader._load_payload_validator(defname)
    return [e.message for e in v.iter_errors(doc)]


@pytest.mark.parametrize("doc,ok", [
    ({"symbols": ["O"], "kind": "md", "ensemble": "npt", "timestep_fs": 0.5}, True),
    ({"symbols": ["O"], "ensemble": "NPT"}, False),
    ({"symbols": ["O"], "ensemble": "nvp"}, False),
    ({"symbols": ["O"], "timestep_fs": 0}, False),
    ({"symbols": ["O"], "timestep_fs": "0.5"}, False),
    ({"symbols": ["O"], "kind": "relaxed_scan"}, False),
    ({"symbols": ["O"], "units": {"lattice": "angstrom", "times": "fs",
                                  "cell_volumes": "a3",
                                  "temperatures": "kelvin"}}, True),
    ({"symbols": ["O"], "units": {"lattice": "bohr"}}, False),
    ({"symbols": ["O"], "units": {"cell_volumes": "bohr3"}}, False),
    ({"symbols": ["O"], "units": {"temperatures": "dimensionless"}}, False),
])
def test_trajectory_metadata_payload(doc, ok):
    assert (not _payload_errors("TrajectoryMetadataPayload", doc)) == ok


@pytest.mark.parametrize("doc,ok", [
    ({"symbols": ["O"], "units": {"lattice": "bohr", "times": "fs"}}, True),
    ({"symbols": ["O"], "units": {"lattice": "angstrom"}}, False),
    ({"symbols": ["O"], "ensemble": "nve", "timestep_fs": 1.0}, True),
])
def test_reaction_path_metadata_payload(doc, ok):
    assert (not _payload_errors("ReactionPathMetadataPayload", doc)) == ok


def test_schema_members(tmp_path):
    """float32 coords are schema-valid; reaction.path has no trajectory-only
    member; a lattice of the wrong shape and a float32 velocity are not."""
    jsonschema = pytest.importorskip("jsonschema")
    with open(qvf_reader._SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    v = jsonschema.Draft202012Validator(schema)

    def manifest(kind, members):
        sha = "0" * 64
        specs = {"metadata": {"path": "m.json", "format": "json", "sha256": sha}}
        for role, (dtype, shape) in members.items():
            specs[role] = {"path": f"{role}.bin", "format": "binary",
                           "dtype": dtype, "shape": shape, "sha256": sha}
        return {"qvf_version": 1,
                "source": {"program": "t", "version": "1", "calculation": ""},
                "sections": [{"id": "s", "kind": kind, "members": specs}]}

    def ok(kind, members):
        return not list(v.iter_errors(manifest(kind, members)))

    coords = ("float64", [4, 3, 3])
    assert ok("trajectory", {"coords": ("float32", [4, 3, 3])})
    assert ok("reaction.path", {"coords": ("float32", [4, 3, 3])})
    assert not ok("trajectory", {"coords": ("int32", [4, 3, 3])})
    full = {"coords": coords, "lattice": ("float64", [4, 3, 3]),
            "velocities": ("float64", [4, 3, 3]),
            "gradient": ("float64", [4, 3, 3]), "times": ("float64", [4]),
            "energies": ("float64", [4]), "cell_volumes": ("float64", [4]),
            "temperatures": ("float64", [4])}
    assert ok("trajectory", full)
    assert ok("trajectory", {**full, "lattice": ("float64", [3, 3])})
    assert not ok("trajectory", {**full, "lattice": ("float64", [3, 4])})
    assert not ok("trajectory", {**full, "velocities": ("float32", [4, 3, 3])})
    assert not ok("trajectory", {**full, "gradient": ("float64", [4, 3, 2])})
    assert not ok("trajectory", {**full, "times": ("float64", [4, 1])})
    shared = {k: full[k] for k in ("coords", "velocities", "gradient", "times",
                                   "energies")}
    assert ok("reaction.path", shared)
    assert not ok("reaction.path", {**shared, "cell_volumes": ("float64", [4])})
    assert not ok("reaction.path", {**shared, "temperatures": ("float64", [4])})
