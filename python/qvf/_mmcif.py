"""mmCIF (PDBx) atom-site interchange; see docs/converters.md.

Import maps one data block's _atom_site rows to atoms with the PDB atom-site
identity (spec § 5.1), with models, the cell, secondary structure and
_struct_conn bonds handled as the PDB import handles their PDB records.
Export writes one structure as an _atom_site loop.
"""
from __future__ import annotations

import math
import re

from . import __version__
from ._cif import _blocks, _cif_number, _missing
from ._legacy_writer import _ELEMENT_SYMBOLS
from .convert import (_atom, _binary, _export_report, _new_output, _number, _pdb_cell,
                      _pdb_link_bonds, _pdb_structure, _select, _text, _validated)
from .reader import Reader
from .writer import Writer


def _table(block, category):
    """Rows of ``category`` as dicts keyed by the attribute name: a loop, or
    the single row its items form."""
    prefix = f"_{category.lower()}."
    for tags, rows in block[2]:
        if tags[0].startswith(prefix):
            names = [t[len(prefix):] for t in tags]
            return [dict(zip(names, row)) for row in rows]
    row = {t[len(prefix):]: v for t, v in block[1].items() if t.startswith(prefix)}
    return [row] if row else []


def _value(row, *names):
    """The first present, known value of ``names`` as a string, else None."""
    for name in names:
        token = row.get(name)
        if not _missing(token):
            return token[1]
    return None


def _integer(text, label):
    if text is None or not re.fullmatch(r"-?[0-9]+", text):
        raise ValueError(f"mmCIF {label} requires an integer")
    return int(text)


def _atom_row(row):
    symbol_text = _value(row, "type_symbol")
    symbol = symbol_text.capitalize() if symbol_text else None
    if symbol not in _ELEMENT_SYMBOLS[1:]:
        raise ValueError("mmCIF atom sites require an element type_symbol")
    position = [_cif_number(row.get(f"cartn_{a}"), f"Cartn_{a}") for a in "xyz"]
    if None in position:
        raise ValueError("mmCIF atom sites require Cartesian coordinates")
    atom = _atom(symbol, position)
    seq = _value(row, "auth_seq_id", "label_seq_id")
    occupancy = _cif_number(row.get("occupancy"), "occupancy")
    if occupancy is not None and not 0 <= occupancy <= 1:
        raise ValueError("mmCIF occupancy must lie in [0, 1]")
    identity = {"atom_name": _value(row, "auth_atom_id", "label_atom_id"),
                "residue_name": _value(row, "auth_comp_id", "label_comp_id"),
                "residue_seq": None if seq is None else _integer(seq, "residue number"),
                "chain_id": _value(row, "auth_asym_id", "label_asym_id"),
                "insertion_code": _value(row, "pdbx_pdb_ins_code"),
                "alt_loc": _value(row, "label_alt_id"),
                "occupancy": occupancy,
                "b_factor": _cif_number(row.get("b_iso_or_equiv"), "B_iso_or_equiv")}
    atom.update({k: v for k, v in identity.items() if v not in (None, "")})
    group = _value(row, "group_pdb")
    if group is not None:
        if group not in ("ATOM", "HETATM"):
            raise ValueError("mmCIF group_PDB must be ATOM or HETATM")
        atom["hetero"] = group == "HETATM"
    return atom


def _ranges(block):
    """(secondary_structure ranges, other _struct_conf rows such as turns)."""
    ranges, other = [], 0

    def end(row, which):
        chain = _value(row, f"{which}_auth_asym_id", f"{which}_label_asym_id")
        seq = _value(row, f"{which}_auth_seq_id", f"{which}_label_seq_id")
        code = _value(row, f"pdbx_{which}_pdb_ins_code")
        return chain or "", _integer(seq, "secondary-structure residue"), code

    for row in _table(block, "struct_conf"):
        if not (_value(row, "conf_type_id") or "").upper().startswith("HELX"):
            other += 1
            continue
        (c1, s1, i1), (c2, s2, i2) = end(row, "beg"), end(row, "end")
        if c1 != c2:
            raise ValueError("mmCIF helices must start and end on one chain")
        r = {"type": "helix", "chain": c1, "start_seq": s1}
        if i1:
            r["start_insertion_code"] = i1
        r["end_seq"] = s2
        if i2:
            r["end_insertion_code"] = i2
        cls = _value(row, "pdbx_pdb_helix_class")
        if cls is not None:
            if not 1 <= _integer(cls, "helix class") <= 10:
                raise ValueError("mmCIF helix class must lie in 1-10")
            r["helix_class"] = int(cls)
        ranges.append(r)
    for row in _table(block, "struct_sheet_range"):
        (c1, s1, i1), (c2, s2, i2) = end(row, "beg"), end(row, "end")
        if c1 != c2:
            raise ValueError("mmCIF strands must start and end on one chain")
        r = {"type": "sheet", "chain": c1, "start_seq": s1}
        if i1:
            r["start_insertion_code"] = i1
        r["end_seq"] = s2
        if i2:
            r["end_insertion_code"] = i2
        if _value(row, "sheet_id"):
            r["sheet_id"] = _value(row, "sheet_id")
        strand = _value(row, "id")
        if strand is not None and re.fullmatch(r"[0-9]+", strand) and int(strand) >= 1:
            r["strand"] = int(strand)
        ranges.append(r)
    return ranges, other


def _connections(block):
    """(SSBOND/LINK-style records, hydrogen bonds skipped) of _struct_conn."""
    links, hydrogen = [], 0
    for row in _table(block, "struct_conn"):
        kind = (_value(row, "conn_type_id") or "").lower()
        if kind == "hydrog":
            hydrogen += 1
            continue
        ends, operators = [], []
        for p in ("ptnr1", "ptnr2"):
            seq = _value(row, f"{p}_auth_seq_id", f"{p}_label_seq_id")
            ends.append((_value(row, f"{p}_auth_asym_id", f"{p}_label_asym_id") or "",
                         _integer(seq, "struct_conn residue number"),
                         _value(row, f"pdbx_{p}_pdb_ins_code"),
                         _value(row, f"{p}_auth_comp_id", f"{p}_label_comp_id"),
                         _value(row, f"{p}_auth_atom_id", f"{p}_label_atom_id"),
                         _value(row, f"pdbx_{p}_label_alt_id")))
            operator = (_value(row, f"{p}_symmetry") or "1_555").replace("_", "")
            if not re.fullmatch(r"[0-9]{4,6}", operator):
                raise ValueError("mmCIF struct_conn symmetry operators look like 1_555")
            operators.append(operator)
        if any(e[3] is None or e[4] is None for e in ends):
            raise ValueError("mmCIF struct_conn requires residue and atom names")
        links.append(("SSBOND" if kind == "disulf" else "LINK", ends, tuple(operators)))
    return links, hydrogen


def import_mmcif(source, destination, *, block=None):
    blocks = _blocks(_text(source))
    candidates = [b for b in blocks if _table(b, "atom_site")]
    if block is not None:
        candidates = [b for b in blocks if b[0].lower() == block.lower()]
        if not candidates or not _table(candidates[0], "atom_site"):
            raise ValueError(f"mmCIF has no data block {block!r} with _atom_site")
    if len(candidates) != 1:
        raise ValueError("select an mmCIF data block (block=) when zero or several blocks "
                         "have _atom_site")
    chosen = candidates[0]
    models = {}
    for row in _table(chosen, "atom_site"):
        number = _value(row, "pdbx_pdb_model_num")
        models.setdefault(1 if number is None else _integer(number, "model number"),
                          []).append(_atom_row(row))
    serials = sorted(models)
    cell_row = (_table(chosen, "cell") or [{}])[0]
    symmetry_row = (_table(chosen, "symmetry") or _table(chosen, "space_group") or [{}])[0]
    values = [_cif_number(cell_row.get(k), k) for k in
              ("length_a", "length_b", "length_c", "angle_alpha", "angle_beta", "angle_gamma")]
    group = _value(symmetry_row, "space_group_name_h-m", "name_h-m_alt")
    cryst1 = None
    if any(v is not None for v in values):
        if None in values or not group:
            raise ValueError("mmCIF _cell requires six values and a space group")
        if not all(v > 0 for v in values[:3]) or not all(0 < v < 180 for v in values[3:]):
            raise ValueError("mmCIF _cell requires positive lengths and angles in (0, 180)")
        cryst1 = (values, " ".join(group.split()), None)
    cell, group, _, placeholder = _pdb_cell(cryst1, {})
    ranges, turns = _ranges(chosen)
    links, hydrogen = _connections(chosen)

    def identity(atoms):
        return [{k: v for k, v in a.items() if k != "position"} for a in atoms]

    first = models[serials[0]]
    shared = len(serials) > 1 and all(identity(models[s]) == identity(first)
                                      for s in serials[1:])
    resolved = {s: _pdb_link_bonds(links, models[s], f"model {s}") for s in serials}
    symmetry = []
    with _new_output(destination) as temporary:
        with Writer(temporary, "qvf.convert", __version__, "mmCIF structure import") as writer:
            def add(sid, atoms, label, s):
                bonds = sorted(set().union(*resolved[s].values()))
                _pdb_structure(writer, sid, atoms, label, ranges, bonds, cell)
                if cell is not None:
                    symmetry.append(f"symmetry_{sid}" if sid != "structure" else "symmetry")
                    writer.add_section({"id": symmetry[-1], "kind": "structure.symmetry",
                                        "structure_ref": sid})
                    writer.add_json(symmetry[-1], "data", {"space_group_symbol": group})

            if len(serials) == 1 or shared:
                sections = ["structure"]
                add("structure", first, None, serials[0])
                if shared:
                    sections.append("trajectory")
                    writer.add_section({"id": "trajectory", "kind": "trajectory",
                                        "structure_ref": "structure"})
                    writer.add_json("trajectory", "metadata", {
                        "symbols": [a["symbol"] for a in first], "pbc": [cell is not None] * 3,
                        "model_serials": serials})
                    _binary(writer, "trajectory", "coords",
                            (v for s in serials for a in models[s] for v in a["position"]),
                            [len(serials), len(first), 3])
                    if cell is not None:
                        _binary(writer, "trajectory", "lattice",
                                (v for _ in serials for row in cell for v in row),
                                [len(serials), 3, 3])
            else:
                sections = [f"model_{s}" for s in serials]
                for sid, s in zip(sections, serials):
                    add(sid, models[s], f"MODEL {s}", s)
        findings = _validated(temporary)
    linked = resolved[serials[0]]
    return {"format": "mmcif", "output": str(destination), "block": chosen[0],
            "atoms": len(first), "models": serials if len(serials) > 1 else [],
            "ensemble": "trajectory" if shared else "structures" if len(serials) > 1 else None,
            "sections": sections + symmetry, "findings": findings,
            "alternate_location_atoms": sum("alt_loc" in a for s in serials for a in models[s]),
            "bonds": {"ssbond": len(linked["SSBOND"]), "link": len(linked["LINK"])},
            "hydrogen_bonds_omitted": hydrogen,
            "symmetry_mate_bonds_skipped": sum(ops != ("1555", "1555") for _, _, ops in links),
            "secondary_structure_ranges": len(ranges), "other_struct_conf_omitted": turns,
            "cell": None if cell is None else {"space_group": group, "expanded": False},
            "placeholder_cell": placeholder,
            "scope": "Atom sites with their PDB identity (author numbering), models, the "
                     "cell, helices, sheet strands and struct_conn bonds only; no "
                     "assemblies, entities, label numbering, symmetry expansion, charge or "
                     "job. Keep the original mmCIF."}


_RESERVED = re.compile(r"(?i)(data_|loop_|save_|global_|stop_).*")


def _cif_text(value):
    """A CIF value: bare when safe, else quoted; '.' for absent."""
    if value is None or value == "":
        return "."
    text = str(value)
    if re.fullmatch(r"[^\s'\"#$_\[\];][^\s]*", text) and not _RESERVED.fullmatch(text) \
            and text not in ("?", "."):
        return text
    if "\n" in text or ("'" in text and '"' in text):
        raise ValueError(f"mmCIF export cannot quote the value {text!r}")
    return f'"{text}"' if "'" in text else f"'{text}'"


def export_mmcif(source, destination, *, section=None):
    _validated(source)
    with Reader(source) as reader:
        selected = _select(reader, section, {"structure"})
        geometry = reader.json(selected.id, "structure")
        atoms = geometry["atoms"]
        if not atoms:
            raise ValueError("mmCIF export requires at least one atom")
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", selected.id)
        lines = [f"# mmCIF written by qvf.convert {__version__}", f"data_{name}"]
        lattice = geometry.get("lattice_vectors")
        group = None
        if all(geometry.get("pbc", [False] * 3)) and lattice is not None:
            rows = [[_number(v) for v in row] for row in lattice]
            lengths = [math.sqrt(sum(v * v for v in row)) for row in rows]

            def angle(u, v):
                dot = sum(x * y for x, y in zip(rows[u], rows[v])) / (lengths[u] * lengths[v])
                return math.degrees(math.acos(max(-1.0, min(1.0, dot))))

            if any(abs(rows[i][k]) > 1e-4 for i, k in ((0, 1), (0, 2), (1, 2))):
                raise ValueError("mmCIF export of a cell requires the PDB orientation (a along "
                                 "x, b in the xy-plane); coordinates are not rotated")
            raw = {s["id"]: s for s in reader.raw_manifest["sections"]}
            first = next(s.id for s in reader.sections if s.kind == "structure")
            group = "P 1"
            for s in reader.sections:
                if s.kind == "structure.symmetry" and \
                        raw[s.id].get("structure_ref", first) == selected.id:
                    group = reader.json(s.id, "data").get("space_group_symbol") or group
            cell = lengths + [angle(1, 2), angle(0, 2), angle(0, 1)]
            lines += [f"_cell.{k} {v:.4f}" for k, v in zip(
                ("length_a", "length_b", "length_c", "angle_alpha", "angle_beta",
                 "angle_gamma"), cell)]
            lines.append(f"_symmetry.space_group_name_H-M {_cif_text(group)}")
        columns = ["group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id",
                   "label_comp_id", "label_asym_id", "label_seq_id", "pdbx_PDB_ins_code",
                   "Cartn_x", "Cartn_y", "Cartn_z", "occupancy", "B_iso_or_equiv",
                   "auth_seq_id", "auth_comp_id", "auth_asym_id", "auth_atom_id",
                   "pdbx_PDB_model_num"]
        lines += ["loop_"] + [f"_atom_site.{c}" for c in columns]
        error = 0.0
        for serial, atom in enumerate(atoms, 1):
            position = [_number(v) for v in atom["position"]]
            text = [f"{v:.4f}" for v in position]
            error = max(error, max(abs(float(t) - v) for t, v in zip(text, position)))
            name_ = atom.get("atom_name") or atom["symbol"]
            residue = atom.get("residue_name")
            chain = atom.get("chain_id")
            seq = atom.get("residue_seq")
            occupancy = atom.get("occupancy")
            b = atom.get("b_factor")
            values = ["HETATM" if atom.get("hetero", "residue_name" not in atom) else "ATOM",
                      str(serial), atom["symbol"].upper(), _cif_text(name_),
                      _cif_text(atom.get("alt_loc")), _cif_text(residue), _cif_text(chain),
                      _cif_text(seq), _cif_text(atom.get("insertion_code")), *text,
                      "?" if occupancy is None else f"{occupancy:.2f}",
                      "?" if b is None else f"{b:.2f}", _cif_text(seq), _cif_text(residue),
                      _cif_text(chain), _cif_text(name_), "1"]
            lines.append(" ".join(values))
        with _new_output(destination) as temporary:
            temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = _export_report(reader, selected, {selected.id}, destination, "mmcif")
        report.update(atoms=len(atoms), space_group=group, coordinate_precision_angstrom=1e-4,
                      max_rounding_error_angstrom=error,
                      generated="Sequential ids; label columns repeat the author identity "
                                "(no entity or label numbering); bonds, secondary structure "
                                "and other sections are not written.")
        return report
