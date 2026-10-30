"""VASP POSCAR/CONTCAR geometry interchange; see docs/converters.md.

Import reads the lattice, species, counts, optional Selective dynamics and
Direct or Cartesian positions of one periodic structure; a CONTCAR velocity
block is checked and reported, not stored. Export writes a periodic structure
with Direct coordinates in archive order.
"""
from __future__ import annotations

import math
import re

from . import __version__
from .convert import (_atom, _export_report, _lattice_inverse, _new_output, _number, _select,
                      _text, _validated)
from ._legacy_writer import _ELEMENT_SYMBOLS
from .reader import Reader
from .writer import Writer

_NUMBER = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?")


def _floats(line, count, label):
    tokens = line.split()
    if len(tokens) < count or not all(_NUMBER.fullmatch(t) for t in tokens[:count]):
        raise ValueError(f"POSCAR {label} requires {count} numbers")
    return [_number(t) for t in tokens[:count]], tokens[count:]


def _species(token):
    """The element of a species entry; POTCAR labels such as Fe_pv or
    Si/1a2b reduce to their element."""
    match = re.fullmatch(r"([A-Z][a-z]?)(?:[_/.].*)?", token)
    if not match or match.group(1) not in _ELEMENT_SYMBOLS[1:]:
        raise ValueError(f"POSCAR species {token!r} is not an element")
    return match.group(1)


def _header(lines, species):
    """The POSCAR part of ``lines`` (also the head of a CHGCAR): a dict of
    the comment, lattice, atoms, fixed atoms and the index after the last
    position line."""
    if any(ord(c) < 32 and c not in "\t" for line in lines for c in line):
        raise ValueError("POSCAR requires text without control characters")
    if len(lines) < 8:
        raise ValueError("POSCAR is too short for a comment, scale, lattice, counts and mode")
    comment = lines[0].strip()
    scale_tokens = lines[1].split()
    if len(scale_tokens) not in (1, 3):
        raise ValueError("POSCAR scale requires one value or three (one per axis)")
    scale, _ = _floats(lines[1], len(scale_tokens), "scale")
    lattice = [_floats(lines[i], 3, "lattice vector")[0] for i in (2, 3, 4)]
    det = (lattice[0][0] * (lattice[1][1] * lattice[2][2] - lattice[1][2] * lattice[2][1])
           - lattice[0][1] * (lattice[1][0] * lattice[2][2] - lattice[1][2] * lattice[2][0])
           + lattice[0][2] * (lattice[1][0] * lattice[2][1] - lattice[1][1] * lattice[2][0]))
    if abs(det) < 1e-12:
        raise ValueError("POSCAR lattice vectors are linearly dependent")
    if len(scale) == 1:
        if scale[0] == 0:
            raise ValueError("POSCAR scale must not be zero")
        # A negative scale is the cell volume in cubic angstrom.
        factor = (-scale[0] / abs(det)) ** (1 / 3) if scale[0] < 0 else scale[0]
        axes = [factor] * 3
    else:
        if not all(v > 0 for v in scale):
            raise ValueError("POSCAR per-axis scale factors must be positive")
        axes = scale
    lattice = [[v * axes[k] for k, v in enumerate(row)] for row in lattice]
    index = 5
    names = lines[index].split()
    vasp5 = bool(names) and not all(re.fullmatch(r"[0-9]+", t) for t in names)
    if vasp5:
        found = [_species(t) for t in names]
        index += 1
    counts_tokens = lines[index].split() if index < len(lines) else []
    if not counts_tokens or not all(re.fullmatch(r"[0-9]+", t) for t in counts_tokens) \
            or any(int(t) == 0 for t in counts_tokens):
        raise ValueError("POSCAR atom counts must be positive integers")
    counts = [int(t) for t in counts_tokens]
    index += 1
    if species is not None:
        given = [_species(str(t)) for t in species]
        if vasp5 and given != found:
            raise ValueError("POSCAR species line disagrees with the species given")
        found = given
    elif not vasp5:
        raise ValueError("POSCAR without a species line (VASP 4) needs species= / --species")
    if len(found) != len(counts):
        raise ValueError("POSCAR needs one species per atom count")
    selective = index < len(lines) and lines[index].strip()[:1] in ("s", "S")
    index += selective
    if index >= len(lines) or not lines[index].strip() \
            or _NUMBER.match(lines[index].split()[0]):
        raise ValueError("POSCAR requires a Direct or Cartesian line")
    cartesian = lines[index].strip()[0] in "cCkK"
    index += 1
    n = sum(counts)
    if len(lines) < index + n:
        raise ValueError("POSCAR has fewer position lines than atoms")
    symbols = [s for s, c in zip(found, counts) for _ in range(c)]
    atoms, frozen, partial = [], [], 0
    for k in range(n):
        values, rest = _floats(lines[index + k], 3, "position")
        if selective:
            flags = [t.upper() for t in rest[:3]]
            if len(flags) != 3 or any(f not in ("T", "F") for f in flags):
                raise ValueError("POSCAR Selective dynamics requires T or F for each axis")
            if flags == ["F"] * 3:
                frozen.append(k)
            elif "F" in flags:
                partial += 1
        if cartesian:
            position = [v * axes[i] for i, v in enumerate(values)]
        else:
            position = [sum(values[i] * lattice[i][j] for i in range(3)) for j in range(3)]
        atoms.append(_atom(symbols[k], [round(v, 10) + 0.0 for v in position]))
    return {"comment": comment, "scale": scale, "lattice": lattice, "atoms": atoms,
            "species": found, "counts": counts, "vasp5": vasp5, "cartesian": cartesian,
            "selective": selective, "frozen": frozen, "partial": partial,
            "index": index + n}


def _write_structure(writer, head):
    section = {"id": "structure", "kind": "structure"}
    if head["comment"]:
        section["label"] = head["comment"]
    writer.add_section(section)
    writer.add_json("structure", "structure", {"atoms": head["atoms"], "pbc": [True] * 3,
                                               "lattice_vectors": head["lattice"]})
    if head["frozen"]:
        writer.set_constraints(frozen_atoms=head["frozen"])


def _header_report(head):
    return {"atoms": len(head["atoms"]), "species": head["species"], "counts": head["counts"],
            "vasp_format": 5 if head["vasp5"] else 4,
            "coordinates": "cartesian" if head["cartesian"] else "direct",
            "scale": head["scale"], "selective_dynamics": head["selective"],
            "frozen_atoms": len(head["frozen"]),
            "partially_fixed_atoms_omitted": head["partial"]}


def import_poscar(source, destination, *, species=None):
    lines = _text(source).splitlines()
    head = _header(lines, species)
    n = len(head["atoms"])
    rest = lines[head["index"]:]
    velocities, lattice_velocities, trailing = 0, False, 0
    while rest and not rest[0].strip():
        rest = rest[1:]
    if rest and rest[0].strip().lower().startswith("lattice velocities"):
        if len(rest) < 8:
            raise ValueError("POSCAR lattice velocity block is incomplete")
        lattice_velocities, rest = True, rest[8:]
        while rest and not rest[0].strip():
            rest = rest[1:]
    if rest:
        block = rest
        if block[0].strip()[:1] in tuple("cCkKdD") and not _NUMBER.match(block[0].strip()):
            block = block[1:]
        if len(block) < n or any(len(line.split()) < 3 for line in block[:n]):
            raise ValueError("POSCAR has content after the positions that is not a velocity "
                             "row for every atom")
        for line in block[:n]:
            _floats(line, 3, "velocity")
        velocities = n
        trailing = sum(bool(line.strip()) for line in block[n:])
    with _new_output(destination) as temporary:
        with Writer(temporary, "qvf.convert", __version__, "POSCAR structure import") as writer:
            _write_structure(writer, head)
        findings = _validated(temporary)
    return {"format": "poscar", "output": str(destination), **_header_report(head),
            "velocities_omitted": velocities, "lattice_velocities_omitted": lattice_velocities,
            "predictor_corrector_lines_omitted": trailing, "findings": findings,
            "scope": "Lattice, species, positions and fully fixed atoms (as "
                     "constraints.frozen_atoms) only; no velocities, partial "
                     "Selective dynamics flags, magnetic moments, charge or job is "
                     "inferred. Keep the original POSCAR/CONTCAR."}


def _structure_lines(reader, selected, geometry, label):
    """(POSCAR lines, export report fields) of one structure periodic on all
    three axes; ``label`` names the format in errors."""
    lattice = geometry.get("lattice_vectors")
    if not all(geometry.get("pbc", [False] * 3)) or lattice is None:
        raise ValueError(f"{label} export requires a structure periodic on all three axes")
    rows = [[_number(v) for v in row] for row in lattice]
    inverse = _lattice_inverse(rows)
    atoms = geometry["atoms"]
    if not atoms:
        raise ValueError(f"{label} export requires at least one atom")
    runs = []
    for atom in atoms:
        symbol = atom["symbol"]
        if symbol not in _ELEMENT_SYMBOLS[1:]:
            raise ValueError(f"{label} export requires element symbols, not {symbol!r}")
        if runs and runs[-1][0] == symbol:
            runs[-1][1] += 1
        else:
            runs.append([symbol, 1])
    first = next(s.id for s in reader.sections if s.kind == "structure")
    constraints = reader.raw_manifest.get("constraints") or {}
    frozen = set(constraints.get("frozen_atoms", [])) if selected.id == first else set()
    if any(not 0 <= i < len(atoms) for i in frozen):
        raise ValueError("constraints.frozen_atoms names an atom outside the structure")
    raw = next(s for s in reader.raw_manifest["sections"] if s["id"] == selected.id)
    comment = " ".join(str(raw.get("label") or selected.id).split())
    lines = [comment.encode("ascii", "replace").decode("ascii"), "1.0"]
    lines += ["  " + " ".join(f"{v:20.10f}" for v in row) for row in rows]
    lines += ["  " + " ".join(f"{s:>4s}" for s, _ in runs),
              "  " + " ".join(f"{c:>4d}" for _, c in runs)]
    if frozen:
        lines.append("Selective dynamics")
    lines.append("Direct")
    error = 0.0
    for k, atom in enumerate(atoms):
        x = [_number(v) for v in atom["position"]]
        f = [sum(x[i] * inverse[i][j] for i in range(3)) for j in range(3)]
        text = [f"{v:.10f}" for v in f]
        back = [sum(float(text[i]) * rows[i][j] for i in range(3)) for j in range(3)]
        error = max(error, math.dist(back, x))
        flags = (" F F F" if k in frozen else " T T T") if frozen else ""
        lines.append("  " + " ".join(f"{t:>14s}" for t in text) + flags)
    omitted = []
    if constraints.get("frozen_atoms") and not frozen:
        omitted.append("frozen_atoms (they index the archive's first structure)")
    if constraints.get("distance_constraints"):
        omitted.append("distance_constraints")
    return lines, {"atoms": len(atoms), "species": [s for s, _ in runs],
                   "counts": [c for _, c in runs], "selective_dynamics": bool(frozen),
                   "frozen_atoms": len(frozen), "constraints_not_written": omitted,
                   "max_rounding_error_angstrom": error}


def export_poscar(source, destination, *, section=None):
    _validated(source)
    with Reader(source) as reader:
        selected = _select(reader, section, {"structure"})
        geometry = reader.json(selected.id, "structure")
        lines, fields = _structure_lines(reader, selected, geometry, "POSCAR")
        with _new_output(destination) as temporary:
            temporary.write_text("\n".join(lines) + "\n", encoding="ascii")
        report = _export_report(reader, selected, {selected.id}, destination, "poscar")
        report.update(fields, generated="Scale 1.0, the archive's lattice rows and Direct "
                                        "coordinates in archive order; one species entry per "
                                        "consecutive run of an element.")
        return report
