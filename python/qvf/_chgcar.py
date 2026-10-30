"""VASP CHGCAR-family charge-density interchange; see docs/converters.md.

CHGCAR, CHG, AECCAR* and PARCHG files share one layout: a POSCAR head, then
one grid per spin component of rho * V_cell (V in cubic angstrom), x fastest.
Import writes the structure, the density in e / bohr^3 and any magnetization
density on a periodic CHGCAR-style grid; export writes them back.
"""
from __future__ import annotations

import math
import re
import struct

from . import __version__
from ._legacy_writer import BOHR_PER_ANGSTROM
from ._poscar import _header, _header_report, _structure_lines, _write_structure
from .convert import (_MAX_VALUES, _binary, _export_report, _new_output, _number, _select,
                      _text, _validated)
from .reader import Reader
from .writer import Writer

_DIMS = re.compile(r"\s*([0-9]+)\s+([0-9]+)\s+([0-9]+)\s*")


def _volume(lattice):
    a, b, c = lattice
    return abs(a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
               + a[2] * (b[0] * c[1] - b[1] * c[0]))


def _grids(lines, index):
    """(shape, [grid values], skipped lines) after the POSCAR head: each grid
    is a dimension line and its values; augmentation occupancies and
    per-atom moment lines between grids are skipped and counted."""
    while index < len(lines) and not lines[index].strip():
        index += 1
    match = _DIMS.fullmatch(lines[index]) if index < len(lines) else None
    if not match:
        raise ValueError("CHGCAR requires a grid dimension line after the positions")
    shape = [int(v) for v in match.groups()]
    total = math.prod(shape)
    if min(shape) < 1 or total > _MAX_VALUES:
        raise ValueError("CHGCAR grid needs 1 or more points per axis within the value limit")
    grids, skipped = [], 0
    while index < len(lines):
        line = lines[index]
        match = _DIMS.fullmatch(line)
        if not match:
            skipped += bool(line.strip())
            index += 1
            continue
        if [int(v) for v in match.groups()] != shape:
            raise ValueError("CHGCAR grids must share one shape")
        index += 1
        values = []
        while len(values) < total:
            if index == len(lines):
                raise ValueError("CHGCAR grid has fewer values than its shape")
            values.extend(_number(v) for v in lines[index].split())
            index += 1
        if len(values) != total:
            raise ValueError("CHGCAR grid values do not end with the grid")
        grids.append(values)
    if len(grids) not in (1, 2, 4):
        raise ValueError("CHGCAR needs 1 (no spin), 2 (collinear) or 4 (noncollinear) grids")
    return shape, grids, skipped


def import_chgcar(source, destination, *, species=None):
    lines = _text(source).splitlines()
    head = _header(lines, species)
    shape, grids, skipped = _grids(lines, head["index"])
    lattice = head["lattice"]
    volume = _volume(lattice)
    scale = 1 / (volume * BOHR_PER_ANGSTROM ** 3)
    nx, ny, nz = shape
    grid = {"origin": [0.0, 0.0, 0.0],
            "voxel_vectors": [[v * BOHR_PER_ANGSTROM / shape[a] for v in row]
                              for a, row in enumerate(lattice)],
            "shape": shape, "periodic": [True] * 3, "includes_endpoint": False,
            "structure_ref": "structure"}
    # CHGCAR index x + nx*(y + ny*z); QVF index z + nz*(y + ny*x).
    order = [x + nx * (y + ny * z) for x in range(nx) for y in range(ny) for z in range(nz)]
    with _new_output(destination) as temporary:
        with Writer(temporary, "qvf.convert", __version__, "CHGCAR density import") as writer:
            _write_structure(writer, head)
            writer.add_section({"id": "density", "kind": "volume.density",
                                "label": "Charge density", "structure_ref": "structure"})
            writer.add_json("density", "grid", grid)
            _binary(writer, "density", "data", (grids[0][i] * scale for i in order), shape)
            if len(grids) == 2:
                writer.add_section({"id": "magnetization", "kind": "volume.spin",
                                    "label": "Magnetization density (up - down), e/bohr^3",
                                    "structure_ref": "structure"})
                writer.add_json("magnetization", "grid", grid)
                _binary(writer, "magnetization", "data", (grids[1][i] * scale for i in order),
                        shape)
            elif len(grids) == 4:
                writer.add_section({"id": "magnetization", "kind": "volume.vector",
                                    "label": "Magnetization density (mx, my, mz), e/bohr^3",
                                    "structure_ref": "structure"})
                writer.add_json("magnetization", "grid", grid)
                _binary(writer, "magnetization", "data",
                        (grids[c][i] * scale for i in order for c in (1, 2, 3)), shape + [3])
        findings = _validated(temporary)
    spin = {1: "none", 2: "collinear", 4: "noncollinear"}[len(grids)]
    return {"format": "chgcar", "output": str(destination), **_header_report(head),
            "sections": ["structure", "density"] + (["magnetization"] if len(grids) > 1 else []),
            "shape": shape, "spin": spin, "cell_volume_angstrom3": volume,
            "electrons": sum(grids[0]) / math.prod(shape),
            "magnetization": [sum(g) / math.prod(shape) for g in grids[1:]],
            "lines_skipped": skipped, "findings": findings,
            "scope": "Structure, total density and magnetization density only; PAW "
                     "augmentation occupancies and per-atom moments are skipped. Keep the "
                     "original CHGCAR for VASP restarts."}


def _grid_of(reader, section):
    raw = next(s for s in reader.raw_manifest["sections"] if s["id"] == section.id)
    grid = reader.json(section.id, "grid")
    return grid, raw.get("structure_ref") or grid.get("structure_ref")


def _values(tensor, components=1):
    fmt = "<f" if tensor.dtype == "float32" else "<d"
    flat = [v for (v,) in struct.iter_unpack(fmt, tensor.data)]
    return [flat[c::components] for c in range(components)]


def export_chgcar(source, destination, *, section=None):
    _validated(source)
    with Reader(source) as reader:
        selected = _select(reader, section, {"volume.density"})
        grid, sid = _grid_of(reader, selected)
        structure = _select(reader, sid, {"structure"})
        geometry = reader.json(structure.id, "structure")
        lines, fields = _structure_lines(reader, structure, geometry, "CHGCAR")
        shape = [int(v) for v in grid["shape"]]
        lattice = [[_number(v) for v in row] for row in geometry["lattice_vectors"]]
        span = [[_number(v) * shape[a] / BOHR_PER_ANGSTROM for v in row]
                for a, row in enumerate(grid["voxel_vectors"])]
        if grid.get("periodic") != [True] * 3 or grid.get("includes_endpoint", True) \
                or any(abs(_number(v)) > 1e-6 for v in grid["origin"]) \
                or any(abs(a - b) > 1e-6 * max(1.0, abs(b))
                       for r, q in zip(span, lattice) for a, b in zip(r, q)):
            raise ValueError("CHGCAR export requires a periodic grid at the origin that spans "
                             "its structure's cell without the endpoint (includes_endpoint "
                             "false)")
        same = []
        for s in reader.sections:
            if s.kind in ("volume.spin", "volume.vector") and s.id != selected.id:
                other, other_sid = _grid_of(reader, s)
                if other_sid == sid and all(other.get(k) == grid.get(k) for k in
                                            ("origin", "voxel_vectors", "shape", "periodic",
                                             "includes_endpoint")):
                    same.append(s)
        magnetization = same[0] if len(same) == 1 else None
        volume = _volume(lattice) * BOHR_PER_ANGSTROM ** 3
        nx, ny, nz = shape
        order = [(x * ny + y) * nz + z for z in range(nz) for y in range(ny) for x in range(nx)]
        datasets = [_values(reader.tensor(selected.id, "data"))[0]]
        if magnetization is not None:
            vector = magnetization.kind == "volume.vector"
            datasets += _values(reader.tensor(magnetization.id, "data"), 3 if vector else 1)
        for values in datasets:
            lines += ["", f" {nx:4d} {ny:4d} {nz:4d}"]
            row = []
            for i in order:
                row.append(f"{values[i] * volume: .11E}")
                if len(row) == 5:
                    lines.append(" " + " ".join(row)); row = []
            if row:
                lines.append(" " + " ".join(row))
        with _new_output(destination) as temporary:
            temporary.write_text("\n".join(lines) + "\n", encoding="ascii")
        used = {selected.id, structure.id} | ({magnetization.id} if magnetization else set())
        report = _export_report(reader, selected, used, destination, "chgcar")
        report.update(fields, shape=shape, spin={1: "none", 2: "collinear", 4: "noncollinear"}[
                          len(datasets)],
                      magnetization_section=magnetization.id if magnetization else None,
                      magnetization_candidates_omitted=[s.id for s in same]
                      if len(same) > 1 else [],
                      generated="rho * V_cell per point with V in cubic angstrom, x fastest, "
                                "11 significant decimals; no PAW augmentation occupancies, so "
                                "the file is for analysis and visualization, not a VASP "
                                "restart.")
        return report
