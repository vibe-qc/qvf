"""Explicit, standard-library-only XYZ/extXYZ, PDB, XSF and cube conversions.

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

__all__ = ["import_xyz", "export_xyz", "import_cube", "export_cube", "import_xsf", "export_xsf",
           "import_pdb", "export_pdb"]
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


_PDB_METADATA = set("""HEADER OBSLTE TITLE SPLIT CAVEAT COMPND SOURCE KEYWDS
    EXPDTA MDLTYP AUTHOR REVDAT SPRSDE JRNL REMARK DBREF DBREF1 DBREF2 SEQADV
    SEQRES MODRES HET HETNAM HETSYN FORMUL HELIX SHEET SSBOND LINK CISPEP SITE
    CRYST1 ORIGX1 ORIGX2 ORIGX3 SCALE1 SCALE2 SCALE3 MTRIX1 MTRIX2 MTRIX3
    ANISOU TER CONECT MASTER""".split())


def _pdb_integer(field, label):
    if not re.fullmatch(r"[0-9]+", field.strip()) or int(field) < 1:
        raise ValueError(f"PDB {label} requires a positive decimal integer")
    return int(field)


def import_pdb(source, destination):
    """Import one geometry from PDB fixed columns; refuse all alternate sites.

    Only element and Cartesian angstrom coordinates are retained. No chain,
    residue, connectivity, crystal cell or assembly is reconstructed. MODEL
    may wrap the one geometry, but ensembles require external selection.
    """
    atoms = []; serials = set(); omitted = {}; model = None
    in_model = False; ended = False; charged = 0; numbered = False
    text = _text(source)
    if any((ord(c) < 32 and c not in '\r\n') or ord(c) > 126 for c in text):
        raise ValueError("PDB requires ASCII records without control characters")
    for line in text.splitlines():
        if not line.strip():
            continue
        if any(ord(c) < 32 or ord(c) > 126 for c in line) or line[80:].strip():
            raise ValueError("PDB requires ASCII fixed-column records of at most 80 columns")
        if ended:
            raise ValueError("PDB has records after END")
        record = line[:6].strip()
        if line[:6].ljust(6) != record.ljust(6):
            raise ValueError("PDB record names must be left-aligned in columns 1-6")
        if record == "MODEL":
            if model is not None or atoms:
                raise ValueError("PDB supports one model only; select an ensemble member externally")
            if line[6:10].strip() or line[14:].strip():
                raise ValueError("PDB MODEL serial must fit columns 11-14")
            model = _pdb_integer(line[10:14], "model serial")
            in_model = True
        elif record == "ENDMDL":
            if not in_model or not atoms:
                raise ValueError("PDB ENDMDL requires a nonempty MODEL")
            in_model = False
        elif record == "NUMMDL":
            if line[6:10].strip() or line[14:].strip():
                raise ValueError("PDB NUMMDL count must fit columns 11-14")
            if numbered or _pdb_integer(line[10:14], "NUMMDL") != 1:
                raise ValueError("PDB supports one model only and one NUMMDL record")
            numbered = True
        elif record in {"ATOM", "HETATM"}:
            if model is not None and not in_model:
                raise ValueError("PDB coordinate record outside MODEL/ENDMDL")
            if len(line) < 78:
                raise ValueError("PDB atom requires coordinates and explicit element columns 77-78")
            if line[11] != ' ' or line[20] != ' ' or line[27:30].strip():
                raise ValueError("PDB atom fields overflow fixed-column separators")
            if line[16] != " ":
                raise ValueError("PDB alternate locations are unsupported; select a conformation externally")
            serial = _pdb_integer(line[6:11], "atom serial")
            if serial in serials:
                raise ValueError("PDB atom serials must be unique")
            serials.add(serial)
            if len(serials) > 99999:
                raise ValueError("PDB geometry exceeds 99999 atoms")
            fields = [line[i:i + 8].strip() for i in (30, 38, 46)]
            if any(not re.fullmatch(r"[+-]?[0-9]+\.[0-9]{3}", v) for v in fields):
                raise ValueError("PDB coordinates require fixed-width Real(8.3) fields")
            # Atom names such as CA are not element declarations. Never guess.
            symbol = line[76:78].strip().capitalize()
            atoms.append(_atom(symbol, fields))
            charged += bool(line[78:80].strip())
        elif record == "END":
            ended = True
        elif record in _PDB_METADATA:
            omitted[record] = omitted.get(record, 0) + 1
        else:
            raise ValueError(f"unsupported PDB record {record!r}")
    if in_model:
        raise ValueError("PDB MODEL is missing ENDMDL")
    if not atoms:
        raise ValueError("PDB has no atoms")
    with _new_output(destination) as temporary:
        with Writer(temporary, "qvf.convert", __version__, "PDB geometry import") as writer:
            _structure(writer, atoms, [False] * 3, None)
        findings = _validated(temporary)
    return {"format": "pdb", "output": str(destination), "atoms": len(atoms),
            "model": model, "findings": findings, "omitted_records": dict(sorted(omitted.items())),
            "atom_charge_fields_omitted": charged,
            "omitted": ["atom serials/names, residue and chain identities",
                        "occupancies, temperature factors and atom charges"],
            "scope": "Explicit elements and coordinates only; no bonds, crystal cell, symmetry or biological assembly is reconstructed. No charge, multiplicity or job is inferred. Keep the original PDB."}


def export_pdb(source, destination, *, section=None):
    """Export a nonperiodic structure as synthetic HETATM geometry records.

    Each atom gets its own synthetic UNL residue. This is a coordinate
    interchange subset, not a biomolecular or deposition-ready PDB file.
    """
    _validated(source)
    with Reader(source) as reader:
        selected = _select(reader, section, {"structure", "trajectory"})
        if selected.kind != "structure":
            raise ValueError("PDB export requires one structure, not a trajectory")
        geometry = reader.json(selected.id, "structure")
        if geometry.get("lattice_vectors") is not None or any(geometry.get("pbc", [False] * 3)):
            raise ValueError("PDB geometry export cannot retain a cell or periodicity; use extXYZ")
        atoms = geometry["atoms"]
        if not 1 <= len(atoms) <= 9999:
            raise ValueError("PDB geometry export requires 1-9999 atoms (one synthetic residue per atom)")
        lines = ["REMARK   1 QVF GEOMETRY ONLY; SYNTHETIC UNL RESIDUES, NO CONNECTIVITY",
                 "REMARK   1 OCCUPANCY 1.00 AND TEMPERATURE FACTOR 0.00 ARE PLACEHOLDERS"]
        max_error = 0.0
        for i, atom in enumerate(atoms, 1):
            symbol = _symbol(atom["symbol"]).upper()
            name = (" " + symbol).ljust(4) if len(symbol) == 1 else symbol.ljust(4)
            position = [_number(v) for v in atom["position"]]
            fields = [f"{v:8.3f}" for v in position]
            if len(position) != 3 or any(len(field) != 8 for field in fields):
                raise ValueError("PDB coordinates overflow fixed-width Real(8.3) fields")
            max_error = max(max_error, *(abs(v - float(field)) for v, field in zip(position, fields)))
            lines.append(f"HETATM{i:5d} {name} UNL  {i:4d}    " + ''.join(fields)
                         + f"  1.00  0.00          {symbol:>2s}  ")
        lines.append("END")
        with _new_output(destination) as temporary:
            temporary.write_text('\n'.join(line.ljust(80) for line in lines) + '\n', encoding="ascii")
        report = _export_report(reader, selected, {selected.id}, destination, "pdb")
        report.update(atoms=len(atoms), coordinate_precision_angstrom=0.001,
                      max_rounding_error_angstrom=max_error,
                      generated="Synthetic serials, element-based atom names, one UNL residue per atom, occupancy 1.00 and temperature factor 0.00; no chemical or experimental meaning.")
        return report


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


class _XsfLines:
    """Keep comments at section boundaries; never discard unknown records."""
    def __init__(self, text):
        self.lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.index = 0
        self.comments = 0

    def boundary(self):
        while self.index < len(self.lines) and self.lines[self.index].startswith('#'):
            self.index += 1
            self.comments += 1
        return self.lines[self.index] if self.index < len(self.lines) else None

    def take(self):
        if self.index == len(self.lines):
            raise ValueError("truncated XSF section")
        line = self.lines[self.index]
        self.index += 1
        return line

    def expect(self, expected):
        if self.take() != expected:
            raise ValueError(f"XSF subset requires {expected}")

    def vector(self):
        fields = self.take().split()
        if len(fields) != 3:
            raise ValueError("XSF vector requires three components")
        return [_number(v) for v in fields]


def _xsf_atom(line):
    fields = line.split()
    if len(fields) != 4:
        raise ValueError("XSF atom rows require identity and three coordinates; forces are unsupported")
    symbol = fields[0]
    if re.fullmatch(r'[0-9]+', symbol):
        z = int(symbol)
        if not 1 <= z < len(_ELEMENT_SYMBOLS):
            raise ValueError("unsupported XSF atomic number")
        symbol = _ELEMENT_SYMBOLS[z]
    return _atom(symbol, fields[1:])


def import_xsf(source, destination, *, kind=None, periodic=None):
    """Import one XSF geometry and optional scalar datagrid, without resampling.

    Geometry periodicity follows CRYSTAL/SLAB/POLYMER. Grid periodicity is
    independent and must be asserted explicitly; its default is a finite box.
    Grid coordinates convert angstrom to bohr; choosing kind asserts the
    scalar values already have that canonical kind's units.
    """
    if kind is not None and kind not in _SCALAR_KINDS:
        raise ValueError("XSF conversion requires a scalar volume kind")
    if periodic is not None and (len(periodic) != 3 or not all(type(v) is bool for v in periodic)):
        raise ValueError("periodic requires three booleans")
    lines = _XsfLines(_text(source))
    header = lines.boundary()
    dimensions = {"CRYSTAL": 3, "SLAB": 2, "POLYMER": 1}
    lattice = None
    if header in dimensions:
        lines.take()
        pbc = [i < dimensions[header] for i in range(3)]
        lines.boundary(); lines.expect("PRIMVEC")
        lattice = [lines.vector() for _ in range(3)]
        lines.boundary()
        if lines.take() not in ("PRIMCOORD", "PRIMCOORD 1"):
            raise ValueError("XSF subset requires one primitive PRIMCOORD section")
        count = lines.take().split()
        if len(count) != 2 or count[1] != '1' or not 0 < int(count[0]) * 3 <= _MAX_VALUES:
            raise ValueError("invalid or oversized XSF primitive atom count")
        atoms = [_xsf_atom(lines.take()) for _ in range(int(count[0]))]
    else:
        if header == "MOLECULE":
            lines.take(); lines.boundary()
        lines.expect("ATOMS")
        pbc = [False] * 3
        atoms = []
        while lines.index < len(lines.lines):
            line = lines.lines[lines.index]
            if line.startswith('#') or line.startswith('BEGIN_'):
                break
            atoms.append(_xsf_atom(lines.take()))
            if len(atoms) * 3 > _MAX_VALUES:
                raise ValueError("oversized XSF geometry")
        if not atoms:
            raise ValueError("XSF requires at least one atom")
    _check_cell(pbc, lattice)
    grid = None; values = None
    if lines.boundary() is not None:
        lines.expect("BEGIN_BLOCK_DATAGRID_3D")
        if len(lines.take().split()) != 1:
            raise ValueError("XSF datagrid block identifier must be one word")
        # Some established writers omit the underscore before the identifier.
        if not re.fullmatch(r'BEGIN_DATAGRID_3D\S+', lines.take()):
            raise ValueError("XSF requires a named scalar 3D datagrid")
        fields = lines.take().split()
        if len(fields) != 3:
            raise ValueError("XSF grid requires three counts")
        shape = [int(v) for v in fields]
        if min(shape) < 2 or math.prod(shape) > _MAX_VALUES:
            raise ValueError("XSF grid requires 2 or more points per axis within the value limit")
        origin = lines.vector()
        spans = [lines.vector() for _ in range(3)]
        _check_cell([True] * 3, spans)
        values = []
        while len(values) < math.prod(shape):
            values.extend(_number(v) for v in lines.take().split())
        if len(values) != math.prod(shape):
            raise ValueError("XSF data count differs from grid shape")
        lines.expect("END_DATAGRID_3D")
        lines.expect("END_BLOCK_DATAGRID_3D")
        flags = list(periodic) if periodic is not None else [False] * 3
        if any(flag and not axis for flag, axis in zip(flags, pbc)):
            raise ValueError("periodic XSF grid axes require matching periodic structure axes")
        grid = {"shape": shape, "origin": [v * BOHR_PER_ANGSTROM for v in origin],
                "voxel_vectors": [[v * BOHR_PER_ANGSTROM / (shape[i] - 1) for v in row]
                                  for i, row in enumerate(spans)],
                "includes_endpoint": True, "periodic": flags, "structure_ref": "structure"}
    if lines.boundary() is not None:
        raise ValueError("unsupported XSF record or additional geometry/grid")
    if grid is None and (kind is not None or periodic is not None):
        raise ValueError("XSF kind/periodic options require a scalar datagrid")
    with _new_output(destination) as temporary:
        with Writer(temporary, "qvf.convert", __version__, "XSF geometry and scalar import") as writer:
            _structure(writer, atoms, pbc, lattice)
            if grid is not None:
                writer.add_section({"id": "volume", "kind": kind or "volume.generic"})
                writer.add_json("volume", "grid", grid)
                nx, ny, nz = grid["shape"]
                # XSF index x + nx*(y + ny*z); QVF index z + nz*(y + ny*x).
                _binary(writer, "volume", "data",
                        (values[x + nx*(y + ny*z)] for x in range(nx) for y in range(ny) for z in range(nz)),
                        grid["shape"])
        findings = _validated(temporary)
    return {"format": "xsf", "output": str(destination), "findings": findings,
            "kind": (kind or "volume.generic") if grid is not None else None,
            "periodic": grid["periodic"] if grid is not None else None,
            "omitted_comments": lines.comments,
            "omitted": ["datagrid block and field labels"] if grid is not None else []}


def export_xsf(source, destination, *, section=None):
    """Export one structure or scalar grid with its structure to static XSF.

    Periodic grids without duplicate endpoints are refused. No points are
    synthesized. Scalar kind and field periodicity are returned in the report
    so callers can assert them again when importing the text representation.
    """
    _validated(source)
    with Reader(source) as reader:
        selected = _select(reader, section, _SCALAR_KINDS | {"structure"})
        grid = None; tensor = None
        if selected.kind != "structure":
            grid = reader.json(selected.id, "grid")
            tensor = reader.tensor(selected.id, "data")
            if len(tensor.shape) != 3 or min(tensor.shape) < 2 or math.prod(tensor.shape) > _MAX_VALUES:
                raise ValueError("XSF requires a bounded scalar 3D grid with at least two points per axis")
            if any(grid.get("periodic", [])) and not grid.get("includes_endpoint", True):
                raise ValueError("XSF periodic grids require included endpoints; no planes are synthesized")
            sid = selected.to_json().get("structure_ref") or grid.get("structure_ref")
            structure = _select(reader, sid, {"structure"})
        else:
            structure = selected
        payload = reader.json(structure.id, "structure")
        pbc = payload.get("pbc", [False] * 3); cell = payload.get("lattice_vectors")
        _check_cell(pbc, cell)
        headers = {(True, True, True): "CRYSTAL", (True, True, False): "SLAB", (True, False, False): "POLYMER"}
        fmt = lambda row: ' '.join(format(_number(v), '.17g') for v in row)
        atoms = payload["atoms"]
        if not atoms or len(atoms) * 3 > _MAX_VALUES:
            raise ValueError("XSF requires a bounded, nonempty geometry")
        if any(pbc):
            if tuple(pbc) not in headers:
                raise ValueError("XSF periodic axes must be the leading cell axes; axes are never permuted")
            rows = [headers[tuple(pbc)], "PRIMVEC", *(fmt(row) for row in cell), "PRIMCOORD", f"{len(atoms)} 1"]
        else:
            if cell is not None:
                raise ValueError("XSF molecular subset cannot retain a nonperiodic cell")
            rows = ["ATOMS"]
        rows.extend(str(_ELEMENT_SYMBOLS.index(_symbol(a["symbol"]))) + ' ' + fmt(a["position"]) for a in atoms)
        if grid is not None:
            spans = [[v * (tensor.shape[i] - 1) / BOHR_PER_ANGSTROM for v in row]
                     for i, row in enumerate(grid["voxel_vectors"])]
            _check_cell([True] * 3, spans)
            rows.extend(["BEGIN_BLOCK_DATAGRID_3D", "qvf_grid", "BEGIN_DATAGRID_3D_field",
                         ' '.join(str(n) for n in tensor.shape),
                         fmt(v / BOHR_PER_ANGSTROM for v in grid["origin"]), *(fmt(row) for row in spans)])
        with _new_output(destination) as temporary, temporary.open('w', encoding='utf-8') as stream:
            stream.write('\n'.join(rows) + '\n')
            if tensor is not None:
                nx, ny, nz = tensor.shape
                code = '<f' if tensor.dtype == 'float32' else '<d'
                size = struct.calcsize(code)
                for z in range(nz):
                    for y in range(ny):
                        stream.write(fmt(struct.unpack_from(code, tensor.data, size*(z + nz*(y + ny*x)))[0]
                                         for x in range(nx)) + '\n')
                stream.write("END_DATAGRID_3D\nEND_BLOCK_DATAGRID_3D\n")
        report = _export_report(reader, selected, {selected.id, structure.id}, destination, "xsf")
        if grid is not None:
            report.update(kind=selected.kind, periodic=grid.get("periodic", [False] * 3), includes_endpoint=True,
                          note="XSF retains structure periodicity but not QVF field kind or field periodicity; supply kind and periodic again on import.")
        return report
