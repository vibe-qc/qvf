"""Explicit, standard-library-only XYZ/extXYZ and scalar cube conversions.

Conversions create a new file and return a report. They do not execute a job
or infer a grid's physical quantity, periodicity, charge or multiplicity.
See docs/converters.md for the supported subsets and loss reporting.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import shlex
import struct

from . import __version__
from ._legacy_writer import BOHR_PER_ANGSTROM, _ELEMENT_SYMBOLS
from .operations import _new_output
from .reader import Reader
from .writer import Writer
from .validate import run

__all__ = ["import_xyz", "export_xyz", "import_cube", "export_cube"]
_MAX_TEXT = 64 * 1024 * 1024
_MAX_VALUES = 5_000_000
_SCALAR_KINDS = {"volume." + name for name in (
    "density", "orbital", "spin", "elf", "difference", "potential", "rdg",
    "generic", "laplacian", "transition_density")}


def _text(path):
    with open(path, "rb") as stream:
        raw = stream.read(_MAX_TEXT + 1)
    if len(raw) > _MAX_TEXT:
        raise ValueError("converter text limit exceeded (64 MiB)")
    return raw.decode("utf-8")


def _number(value):
    result = float(str(value).replace("D", "E").replace("d", "e"))
    if not math.isfinite(result):
        raise ValueError("conversion requires finite numeric values")
    return result


def _symbol(value):
    if value not in _ELEMENT_SYMBOLS[1:]:
        raise ValueError(f"unsupported element symbol {value!r}")
    return value


def _atom(symbol, position):
    return {"symbol": _symbol(symbol), "atomic_number": _ELEMENT_SYMBOLS.index(symbol),
            "position": [_number(v) for v in position]}


def _binary(writer, sid, role, values, shape):
    with writer.begin_binary(sid, role, dtype="float64", shape=shape) as sink:
        chunk = []
        for value in values:
            chunk.append(_number(value))
            if len(chunk) == 4096:
                sink.write(struct.pack("<4096d", *chunk)); chunk.clear()
        if chunk:
            sink.write(struct.pack("<" + str(len(chunk)) + "d", *chunk))


def _check_cell(pbc, lattice):
    if any(pbc) and lattice is None:
        raise ValueError("periodic geometry needs a cell")
    if lattice is not None:
        active = [row for row, flag in zip(lattice, pbc) if flag]
        if any(not any(v != 0 for v in row) for row in active):
            raise ValueError("periodic cell vectors must be nonzero")
        if len(active) >= 2:
            a, b = active[:2]
            cross = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
            if not any(v != 0 for v in cross) or (len(active) == 3 and sum(x*y for x, y in zip(cross, active[2])) == 0):
                raise ValueError("periodic cell vectors must be independent")


def _structure(writer, atoms, pbc, lattice):
    _check_cell(pbc, lattice)
    writer.add_section({"id": "structure", "kind": "structure"})
    writer.add_json("structure", "structure", {
        "atoms": atoms, "pbc": pbc, "lattice_vectors": lattice})


def _validated(path):
    report = run(path)
    if not report["ok"]:
        errors = [f["code"] for f in report["findings"] if f["severity"] == "error"]
        raise ValueError("converted archive failed validation: " + ", ".join(errors))
    return report["findings"]


def _xyz_frames(text):
    lines = text.splitlines(); index = 0; frames = []; count = 0; comments = 0
    while index < len(lines):
        if not lines[index].strip() and not any(line.strip() for line in lines[index:]):
            break
        n = int(lines[index]); index += 1
        count += n * 3
        if n < 1 or count > _MAX_VALUES or index + n >= len(lines):
            raise ValueError("invalid, truncated or oversized XYZ frame")
        comment = lines[index]; index += 1
        lattice = None; pbc = [False] * 3; species_column = 0; position_columns = [1, 2, 3]
        if re.search(r'\b(?:Properties|Lattice|pbc)\s*=', comment):
            attrs = {}
            # Geometry subset: key=value, with quoted space-separated vectors.
            tokens = shlex.split(re.sub(r'\s*=\s*', '=', comment), comments=False)
            for token in tokens:
                if '=' not in token:
                    raise ValueError("unsupported extXYZ header syntax")
                key, value = token.split('=', 1)
                if key in attrs or key not in {"Properties", "Lattice", "pbc"}:
                    raise ValueError(f"unsupported or repeated extXYZ field {key!r}")
                attrs[key] = value
            props = attrs.get("Properties")
            if props == "pos:R:3:species:S:1":
                species_column = 3; position_columns = [0, 1, 2]
            elif props != "species:S:1:pos:R:3":
                raise ValueError("extXYZ requires only species:S:1 and pos:R:3")
            if "Lattice" in attrs:
                values = [_number(x) for x in attrs["Lattice"].split()]
                if len(values) != 9:
                    raise ValueError("extXYZ Lattice must contain nine row-vector components")
                lattice = [values[i:i + 3] for i in (0, 3, 6)]
                pbc = [True] * 3
            if "pbc" in attrs:
                flags = attrs["pbc"].lower().split()
                if len(flags) != 3 or any(x not in {"t", "f", "true", "false"} for x in flags):
                    raise ValueError("extXYZ pbc must contain three booleans")
                pbc = [x in {"t", "true"} for x in flags]
            if any(pbc) and lattice is None:
                raise ValueError("periodic extXYZ needs Lattice")
        elif comment:
            comments += 1
        atoms = []
        for line in lines[index:index + n]:
            fields = line.split()
            if len(fields) != 4:
                raise ValueError("XYZ atom rows must contain a symbol and three coordinates")
            atoms.append(_atom(fields[species_column], [fields[i] for i in position_columns]))
        index += n
        frames.append({"atoms": atoms, "pbc": pbc, "lattice_vectors": lattice})
    if not frames:
        raise ValueError("XYZ has no frames")
    first = frames[0]
    for frame in frames[1:]:
        if [a["symbol"] for a in frame["atoms"]] != [a["symbol"] for a in first["atoms"]]:
            raise ValueError("trajectory frames must preserve atom count and symbol order")
        if frame["pbc"] != first["pbc"] or (frame["lattice_vectors"] is None) != (first["lattice_vectors"] is None):
            raise ValueError("trajectory frames must preserve periodicity and cell availability")
    return frames, comments


def import_xyz(source, destination):
    """Convert geometry-only XYZ/extXYZ to structure, plus trajectory if needed."""
    frames, comments = _xyz_frames(_text(source)); first = frames[0]
    with _new_output(destination) as temporary:
        with Writer(temporary, "qvf.convert", __version__, "XYZ geometry import") as writer:
            _structure(writer, first["atoms"], first["pbc"], first["lattice_vectors"])
            if len(frames) > 1:
                writer.add_section({"id": "trajectory", "kind": "trajectory", "structure_ref": "structure"})
                writer.add_json("trajectory", "metadata", {
                    "symbols": [a["symbol"] for a in first["atoms"]], "pbc": first["pbc"]})
                _binary(writer, "trajectory", "coords", (v for f in frames for a in f["atoms"] for v in a["position"]),
                        [len(frames), len(first["atoms"]), 3])
                if first["lattice_vectors"] is not None:
                    _binary(writer, "trajectory", "lattice", (v for f in frames for row in f["lattice_vectors"] for v in row),
                            [len(frames), 3, 3])
        findings = _validated(temporary)
    return {"format": "xyz", "frames": len(frames), "findings": findings,
            "omitted_comments": comments, "output": str(destination)}


def _select(reader, section, kinds):
    if section is not None:
        result = reader.section(section)
        if result.kind not in kinds:
            raise ValueError("selected section has an unsupported conversion kind")
        return result
    choices = [s for s in reader.sections if s.kind in kinds]
    if len(choices) != 1:
        raise ValueError("select a section explicitly when zero or multiple candidates exist")
    return choices[0]


def _export_report(reader, selected, used, destination, fmt):
    return {"format": fmt, "section": selected.id, "output": str(destination),
            "omitted_sections": [s.id for s in reader.sections if s.id not in used],
            "scope": "Selected geometry/grid only; QVF metadata, bonds, identity, jobs and other results are not preserved. Keep the original archive."}


def export_xyz(source, destination, *, section=None, extended=True):
    """Export one structure or trajectory; extXYZ preserves cell and pbc."""
    _validated(source)
    with Reader(source) as reader:
        selected = _select(reader, section, {"structure", "trajectory"})
        if selected.kind == "structure":
            frames = [reader.json(selected.id, "structure")]
        else:
            metadata = reader.json(selected.id, "metadata")
            symbols = metadata.get("symbols")
            if symbols is None:
                numbers = metadata.get("atomic_numbers")
                if numbers is None:
                    atoms = metadata.get("atoms", [])
                    symbols = [a.get("symbol") for a in atoms]
                else:
                    symbols = [_ELEMENT_SYMBOLS[z] for z in numbers]
            coords = reader.tensor(selected.id, "coords").tolist()
            lattice = reader.tensor(selected.id, "lattice") if selected.member("lattice") else None
            cells = lattice.tolist() if lattice else None
            frames = []
            for i, positions in enumerate(coords):
                if len(symbols) != len(positions):
                    raise ValueError("trajectory atom identities are incomplete")
                frames.append({"atoms": [_atom(s, p) for s, p in zip(symbols, positions)],
                               "pbc": metadata.get("pbc", [False] * 3),
                               "lattice_vectors": cells[i] if lattice and len(lattice.shape) == 3 else cells})
        lines = []
        for frame in frames:
            cell = frame.get("lattice_vectors"); pbc = frame.get("pbc", [False] * 3)
            _check_cell(pbc, cell)
            if not extended and (cell is not None or any(pbc)):
                raise ValueError("plain XYZ cannot retain a cell or periodicity; use extXYZ")
            header = "QVF geometry export"
            if extended:
                header = 'Properties=species:S:1:pos:R:3 pbc="' + ' '.join('T' if x else 'F' for x in pbc) + '"'
                if cell is not None:
                    header += ' Lattice="' + ' '.join(format(_number(v), '.17g') for row in cell for v in row) + '"'
            lines.extend([str(len(frame["atoms"])), header])
            for atom in frame["atoms"]:
                lines.append(_symbol(atom["symbol"]) + ' ' + ' '.join(format(_number(v), '.17g') for v in atom["position"]))
        with _new_output(destination) as temporary:
            temporary.write_text('\n'.join(lines) + '\n', encoding="utf-8")
        report = _export_report(reader, selected, {selected.id}, destination, "extxyz" if extended else "xyz")
        report["frames"] = len(frames)
        return report


def import_cube(source, destination, *, kind="volume.generic", periodic=(False, False, False), includes_endpoint=True):
    """Import a single scalar cube in bohr, with explicit quantity/periodicity.

    A periodic cell is derived from voxel vectors times n-1 (endpoint) or n.
    Scalar values are unchanged; choosing a specific kind asserts its units.
    """
    if kind not in _SCALAR_KINDS:
        raise ValueError("cube conversion requires a scalar volume kind")
    if len(periodic) != 3 or not all(type(x) is bool for x in periodic) or type(includes_endpoint) is not bool:
        raise ValueError("periodic requires three booleans and includes_endpoint a boolean")
    lines = _text(source).splitlines()
    if len(lines) < 6:
        raise ValueError("truncated cube header")
    axes = re.findall(r'(?:OUTER|MIDDLE|INNER) LOOP:\s*([XYZ])', lines[1].upper())
    if axes and axes != ['X', 'Y', 'Z']:
        raise ValueError("cube axis order must be X/Y/Z")
    head = lines[2].split()
    if len(head) not in (4, 5):
        raise ValueError("invalid cube atom/origin line")
    natoms = int(head[0]); origin = [_number(v) for v in head[1:4]]
    if natoms < 1 or (len(head) == 5 and int(head[4]) != 1):
        raise ValueError("only positive-atom, single-scalar cubes are supported")
    shape = []; vectors = []
    for line in lines[3:6]:
        fields = line.split()
        if len(fields) != 4 or int(fields[0]) < 1:
            raise ValueError("cube axes require positive counts and bohr vectors")
        shape.append(int(fields[0])); vectors.append([_number(v) for v in fields[1:]])
    count = math.prod(shape)
    if count > _MAX_VALUES or natoms * 3 > _MAX_VALUES or len(lines) < 6 + natoms:
        raise ValueError("truncated or oversized cube")
    atoms = []; charges = []
    for line in lines[6:6 + natoms]:
        fields = line.split()
        if len(fields) != 5 or not 1 <= int(fields[0]) < len(_ELEMENT_SYMBOLS):
            raise ValueError("unsupported cube atom record")
        charges.append(_number(fields[1]))
        atoms.append(_atom(_ELEMENT_SYMBOLS[int(fields[0])], [_number(v) / BOHR_PER_ANGSTROM for v in fields[2:]]))
    values = [_number(v) for line in lines[6 + natoms:] for v in line.split()]
    if len(values) != count:
        raise ValueError("cube data count differs from grid shape")
    cell = None
    if any(periodic):
        cell = [[v * (shape[i] - int(includes_endpoint)) / BOHR_PER_ANGSTROM for v in row]
                for i, row in enumerate(vectors)]
    grid = {"shape": shape, "origin": origin, "voxel_vectors": vectors,
            "periodic": list(periodic), "includes_endpoint": includes_endpoint, "structure_ref": "structure"}
    with _new_output(destination) as temporary:
        with Writer(temporary, "qvf.convert", __version__, "Scalar cube import") as writer:
            _structure(writer, atoms, list(periodic), cell)
            writer.add_section({"id": "volume", "kind": kind})
            writer.add_json("volume", "grid", grid)
            _binary(writer, "volume", "data", values, shape)
        findings = _validated(temporary)
    return {"format": "cube", "output": str(destination), "kind": kind, "findings": findings,
            "omitted": ["two comment lines", "cube atom charge column"],
            "nonzero_atom_charges_omitted": sum(v != 0 for v in charges)}


def export_cube(source, destination, *, section=None):
    """Export a selected scalar grid and its unambiguous structure in bohr."""
    _validated(source)
    with Reader(source) as reader:
        selected = _select(reader, section, _SCALAR_KINDS)
        grid = reader.json(selected.id, "grid"); tensor = reader.tensor(selected.id, "data")
        if len(tensor.shape) != 3:
            raise ValueError("cube needs a scalar three-dimensional grid")
        sid = selected.to_json().get("structure_ref") or grid.get("structure_ref")
        structure = _select(reader, sid, {"structure"})
        atoms = reader.json(structure.id, "structure")["atoms"]
        if not atoms:
            raise ValueError("cube requires at least one atom")
        rows = ["QVF scalar grid export (bohr)", "OUTER LOOP: X, MIDDLE LOOP: Y, INNER LOOP: Z"]
        rows.append(str(len(atoms)) + ' ' + ' '.join(format(_number(v), '.17g') for v in grid["origin"]))
        for n, vector in zip(tensor.shape, grid["voxel_vectors"]):
            rows.append(str(n) + ' ' + ' '.join(format(_number(v), '.17g') for v in vector))
        for atom in atoms:
            z = _ELEMENT_SYMBOLS.index(_symbol(atom["symbol"]))
            rows.append(f"{z} 0 " + ' '.join(format(_number(v) * BOHR_PER_ANGSTROM, '.17g') for v in atom["position"]))
        with _new_output(destination) as temporary, temporary.open('w', encoding='utf-8') as stream:
            stream.write('\n'.join(rows) + '\n')
            for i, (value,) in enumerate(struct.iter_unpack('<f' if tensor.dtype == 'float32' else '<d', tensor.data)):
                stream.write(format(_number(value), '.17g') + ('\n' if i % 6 == 5 else ' '))
            stream.write('\n')
        report = _export_report(reader, selected, {selected.id, structure.id}, destination, "cube")
        report.update(kind=selected.kind, periodic=grid.get("periodic", [False] * 3),
                      includes_endpoint=grid.get("includes_endpoint", True),
                      note="Cube does not encode QVF kind or periodicity; retain these options when reimporting. Atom charge column is zero, not a population analysis.")
        return report
