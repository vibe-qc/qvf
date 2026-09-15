"""qvf_writer — a standalone reference writer for the QVF format.

QVF (``.qvf``, *Quantum Visualization Format*) is a ZIP container with a
mandatory ``manifest.json`` plus typed JSON / binary members. This module is a
dependency-light reference implementation of the QVF **producer** contract: it
depends only on the Python standard library and NumPy, so any code can vendor it
without pulling in vibe-qc.

It is the executable companion to ``spec/qvf-format-spec.md``. Every method below
maps onto a canonical section kind from § 5 of that spec; the class enforces the
byte-level rules (little-endian binary, ``sha256`` over stored bytes,
``itemsize·∏(shape)`` sizing, Appendix-A.1 GTO coefficient normalization).

Typical use::

    from qvf_writer import QvfWriter
    w = QvfWriter(program="my-code", version="1.0", calculation="h2o/rhf")
    w.add_structure(atoms=[{"symbol": "O", "position": [0, 0, 0.117],
                            "atomic_number": 8}, ...])
    w.add_spectrum("spectra.ir", frequencies=[1595.0], intensities=[67.0])
    w.write("h2o.qvf")

License: Apache-2.0.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import zipfile
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

__all__ = ["QvfWriter", "primitive_norm", "QVF_VERSION", "TOOLKIT_VERSION"]

QVF_VERSION = 1
TOOLKIT_VERSION = "0.1.0"
_SCHEMA_URI = "https://vibe-qc.org/spec/qvf/1/manifest.schema.json"

# NumPy dtype names permitted for binary members by the schema (NumpyDtype enum).
_ALLOWED_DTYPES = frozenset(
    {
        "int8", "int16", "int32", "int64",
        "uint8", "uint16", "uint32", "uint64",
        "float32", "float64",
    }
)

_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_VENDOR_RE = re.compile(r"^x_[A-Za-z0-9_]+(\.[A-Za-z0-9_.-]+)?$")

# Per-atom biomolecular fields a structure payload may carry (spec § 5.1,
# $defs/StructureAtom). Passed through verbatim so a PDB-derived structure
# keeps the identity a cartoon renderer needs.
_ATOM_BIOMOLECULE_FIELDS = (
    "atom_name", "residue_name", "residue_seq", "chain_id", "b_factor",
)

_ELEMENT_SYMBOLS = (
    "X", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg",
    "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn",
    "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb",
    "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In",
    "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm",
    "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta",
    "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At",
    "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk",
    "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt",
    "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
)


def primitive_norm(alpha: float, l: int) -> float:
    """Norm of the *axial* Cartesian Gaussian primitive of a shell.

    ``N = (2α/π)^{3/4} · (4α)^{l/2} / √((2l−1)!!)`` where ``l`` is the total
    angular momentum. Engines that store contraction coefficients already
    multiplied by this factor (libint / libcint / PySCF, and GBW-style storage)
    must divide by ``primitive_norm`` before writing them into ``basis.json``.
    See spec Appendix A.

    Note the factor depends only on ``l``, not on the individual
    ``(l_x, l_y, l_z)``: it is the norm of the axial component ``(l, 0, 0)``
    and is applied uniformly across the shell. So for ``pure: false`` shells
    the primitives are *not* individually unit-normalized -- ``⟨xy|xy⟩ = 1/3``
    for a d shell, against ``⟨xx|xx⟩ = 1``. That is the convention the format
    defines; consumers must not add a per-component correction on top of it.
    See spec Appendix A.1.
    """
    radial = (2.0 * alpha / math.pi) ** 0.75
    angular = (4.0 * alpha) ** (l / 2.0)
    df = 1.0
    for k in range(1, 2 * l, 2):  # (2l-1)!!
        df *= k
    return radial * angular / math.sqrt(df)


def _symbol(z: int) -> str:
    return _ELEMENT_SYMBOLS[z] if 0 <= z < len(_ELEMENT_SYMBOLS) else "X"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(obj: Any) -> bytes:
    """Serialize ``obj`` as canonical UTF-8 JSON bytes for a QVF member."""
    return json.dumps(
        obj, ensure_ascii=False, indent=2, allow_nan=False
    ).encode("utf-8")


def _le_bytes(data: Any, dtype: str) -> tuple[bytes, str, list[int]]:
    """Return (little-endian raw bytes, dtype-name, shape) for a binary member.

    The stored bytes are C-contiguous and little-endian regardless of host
    byte order, satisfying the spec § 2.2 contract.
    """
    if dtype not in _ALLOWED_DTYPES:
        raise ValueError(f"dtype {dtype!r} is not a permitted QVF dtype")
    le = np.dtype(dtype).newbyteorder("<")
    arr = np.ascontiguousarray(np.asarray(data).astype(le, copy=False))
    return arr.tobytes(), dtype, list(arr.shape)


class QvfWriter:
    """Accumulate sections and root metadata, then write a ``.qvf`` archive.

    All ``add_*`` methods return the section ``id`` they created. Payloads are
    accepted as plain Python lists / dicts and NumPy arrays; the writer converts,
    checksums, and lays out the ZIP for you.
    """

    def __init__(self, program: str, version: str, calculation: str = "") -> None:
        if not program or not version:
            raise ValueError("source.program and source.version are required")
        self._source = {
            "program": str(program),
            "version": str(version),
            "calculation": str(calculation),
        }
        self._sections: list[dict[str, Any]] = []
        self._files: dict[str, bytes] = {}
        self._ids: set[str] = set()
        self._root: dict[str, Any] = {}

    # -- root metadata ----------------------------------------------------

    def set_provenance(self, **fields: Any) -> None:
        """Set the root ``provenance`` block (method, basis, energies, …).

        ``scf_energy`` / ``fermi_energy`` may be passed as ``scf_energy_eh`` /
        ``fermi_energy_ev`` convenience floats, which are wrapped into the
        ``{value, units}`` shape the schema requires.
        """
        prov = dict(self._root.get("provenance", {}))
        if "scf_energy_eh" in fields:
            prov["scf_energy"] = {"value": float(fields.pop("scf_energy_eh")),
                                  "units": "Eh"}
        if "fermi_energy_ev" in fields:
            prov["fermi_energy"] = {"value": float(fields.pop("fermi_energy_ev")),
                                    "units": "eV"}
        prov.update(fields)
        self._root["provenance"] = prov

    def set_thermochemistry(self, **fields: Any) -> None:
        self._root["thermochemistry"] = dict(fields)

    def set_dipole_moment(self, total_debye: float | None = None,
                          vector_debye: Sequence[float] | None = None,
                          origin: str | None = None) -> None:
        d: dict[str, Any] = {}
        if total_debye is not None:
            d["total_debye"] = float(total_debye)
        if vector_debye is not None:
            d["vector_debye"] = [float(x) for x in vector_debye]
        if origin is not None:
            d["origin"] = str(origin)
        self._root["dipole_moment"] = d

    def set_constraints(self, frozen_atoms: Sequence[int] | None = None,
                        distance_constraints: Sequence[Mapping[str, Any]] | None = None
                        ) -> None:
        c: dict[str, Any] = {}
        if frozen_atoms is not None:
            c["frozen_atoms"] = [int(i) for i in frozen_atoms]
        if distance_constraints is not None:
            c["distance_constraints"] = [dict(x) for x in distance_constraints]
        self._root["constraints"] = c

    def set_viewer_defaults(self, defaults: Mapping[str, Any]) -> None:
        self._root["viewer_defaults"] = dict(defaults)

    def set_extensions(self, extensions: Mapping[str, Mapping[str, Any]]) -> None:
        """Declare vendor extension namespaces (keys without the ``x_``… no:
        keys *include* ``x_``, e.g. ``{"x_orca": {"version": "1.0"}}``)."""
        self._root["extensions"] = {k: dict(v) for k, v in extensions.items()}

    # -- internal helpers -------------------------------------------------

    def _reserve_id(self, section_id: str) -> str:
        if not _ID_RE.match(section_id):
            raise ValueError(f"section id {section_id!r} must match [A-Za-z0-9_.-]+")
        if section_id in self._ids:
            raise ValueError(f"duplicate section id {section_id!r}")
        self._ids.add(section_id)
        return section_id

    def _add_file(self, path: str, data: bytes) -> None:
        if path in self._files:
            raise ValueError(f"duplicate member path {path!r}")
        if ".." in path.split("/") or path.startswith("/"):
            raise ValueError(f"illegal member path {path!r}")
        self._files[path] = data

    def _json_member(self, path: str, obj: Any) -> dict[str, Any]:
        data = _json_bytes(obj)
        self._add_file(path, data)
        return {"path": path, "format": "json", "sha256": _sha256_hex(data)}

    def _binary_member(self, path: str, data: Any, dtype: str,
                       *, with_shape: bool = True) -> dict[str, Any]:
        raw, dname, shape = _le_bytes(data, dtype)
        self._add_file(path, raw)
        member: dict[str, Any] = {"path": path, "format": "binary",
                                  "sha256": _sha256_hex(raw)}
        if with_shape:
            member["dtype"] = dname
            member["shape"] = shape
        return member

    def _push(self, section: dict[str, Any]) -> str:
        self._sections.append(section)
        return section["id"]

    # -- structure / bonds -----------------------------------------------

    def add_structure(self, atoms: Sequence[Mapping[str, Any]], *,
                      pbc: Sequence[bool] | None = None,
                      lattice_vectors: Sequence[Sequence[float]] | None = None,
                      dimensionality: int | None = None,
                      bonds: Sequence[Mapping[str, Any]] | None = None,
                      biomolecule: Mapping[str, Any] | None = None,
                      section_id: str = "structure") -> str:
        """Add a ``structure`` section. ``atoms`` positions are in Ångström.

        Each atom is ``{"symbol", "position": [x, y, z], "atomic_number"}``;
        missing ``symbol``/``atomic_number`` are inferred from each other.
        ``bonds`` (optional) is a list of ``{i, j, order}`` written as the
        section's ``bonds`` member. ``biomolecule`` adds ``chains`` /
        ``residues`` / ``secondary_structure`` / ``b_factors`` peer fields for
        cartoon rendering (spec § 5.1). The per-atom biomolecular fields
        ``atom_name`` / ``residue_name`` / ``residue_seq`` / ``chain_id`` /
        ``b_factor`` are passed through from each atom mapping when present.

        ``pbc`` marks which axes are periodic and is the normative carrier of
        that information (spec § 5.1); ``lattice_vectors`` is required whenever
        any axis is periodic, and its row ``i`` pairs with ``pbc[i]``.
        ``dimensionality`` is derived — pass it only to have it written out, and
        it must equal ``sum(pbc)``. Passing ``dimensionality`` without ``pbc``
        derives the leading axes as the periodic ones, which is this writer's
        convenience, not a rule of the format.
        """
        norm_atoms = []
        for a in atoms:
            z = a.get("atomic_number")
            sym = a.get("symbol")
            if z is None and sym is not None:
                z = _ELEMENT_SYMBOLS.index(sym) if sym in _ELEMENT_SYMBOLS else 0
            if sym is None and z is not None:
                sym = _symbol(int(z))
            atom: dict[str, Any] = {
                "symbol": sym,
                "position": [float(x) for x in a["position"]],
                "atomic_number": int(z) if z is not None else 0,
            }
            for extra in _ATOM_BIOMOLECULE_FIELDS:
                if a.get(extra) is not None:
                    atom[extra] = a[extra]
            norm_atoms.append(atom)
        if pbc is not None:
            flags = [bool(x) for x in pbc]
            if len(flags) != 3:
                raise ValueError(f"pbc must have 3 entries, got {len(flags)}")
        elif dimensionality is not None:
            flags = [i < int(dimensionality) for i in range(3)]
        else:
            flags = [False, False, False]

        if dimensionality is not None and int(dimensionality) != sum(flags):
            raise ValueError(
                f"dimensionality {int(dimensionality)} != sum(pbc) {sum(flags)}; "
                f"the QVF invariant is dimensionality == sum(pbc) (spec § 5.1)")

        lattice = (
            [[float(x) for x in row] for row in lattice_vectors]
            if lattice_vectors is not None else None
        )
        if any(flags) and lattice is None:
            raise ValueError(
                f"pbc {flags} marks a periodic axis, so lattice_vectors is "
                f"required (spec § 5.1)")

        struct: dict[str, Any] = {
            "atoms": norm_atoms,
            "pbc": flags,
            "lattice_vectors": lattice,
        }
        if dimensionality is not None:
            struct["dimensionality"] = int(dimensionality)
        members = {"structure": self._json_member(
            f"{section_id}/structure.json", struct)}
        if bonds is not None:
            members["bonds"] = self._json_member(
                f"{section_id}/bonds.json", {"pairs": [dict(b) for b in bonds]})
        section: dict[str, Any] = {
            "id": self._reserve_id(section_id), "kind": "structure",
            "members": members,
        }
        if biomolecule is not None:
            for key in ("chains", "residues", "secondary_structure", "b_factors"):
                if key in biomolecule:
                    section[key] = biomolecule[key]
        return self._push(section)

    def add_bonds(self, pairs: Sequence[Mapping[str, Any]], *,
                 section_id: str = "bonds") -> str:
        """Add a standalone ``bonds`` connectivity section."""
        member = self._json_member(f"{section_id}/connectivity.json",
                                   {"pairs": [dict(p) for p in pairs]})
        return self._push({"id": self._reserve_id(section_id), "kind": "bonds",
                          "members": {"bonds": member}})

    def add_bond_orders(self, method: str, pairs: Sequence[Mapping[str, Any]], *,
                       section_id: str = "bond_orders") -> str:
        """Add a ``bond_orders`` table. ``pairs`` each carry ``i``, ``j``,
        ``order`` and optionally ``distance_ang``, ``symbol_i``, ``symbol_j``."""
        payload = {"method": str(method), "pairs": [dict(p) for p in pairs]}
        member = self._json_member(f"{section_id}/orders.json", payload)
        return self._push({"id": self._reserve_id(section_id),
                          "kind": "bond_orders",
                          "members": {"bond_orders": member}})

    # -- volumes ----------------------------------------------------------

    _VOLUME_KINDS = frozenset({
        "volume.density", "volume.orbital", "volume.spin", "volume.elf",
        "volume.generic", "volume.potential", "volume.rdg", "volume.difference",
    })

    def add_volume(self, kind: str, data: np.ndarray, origin: Sequence[float],
                  voxel_vectors: Sequence[Sequence[float]], *,
                  label: str | None = None, dtype: str = "float32",
                  component: str | None = None, section_id: str | None = None,
                  operand_a: str | None = None, operand_b: str | None = None,
                  description: str | None = None) -> str:
        """Add any ``volume.*`` section. ``data`` is a 3-D array; ``origin`` and
        ``voxel_vectors`` are in bohr (spec § 5.2). For ``volume.difference`` you
        may pass ``operand_a``/``operand_b`` section ids."""
        if kind not in self._VOLUME_KINDS:
            raise ValueError(f"{kind!r} is not a volume kind")
        arr = np.asarray(data)
        if arr.ndim != 3:
            raise ValueError(f"{kind}: data must be 3-D, got ndim={arr.ndim}")
        sid = section_id or (kind.replace(".", "_") + f"_{len(self._sections)}")
        stem = sid
        grid = {
            "origin": [float(x) for x in origin],
            "voxel_vectors": [[float(x) for x in v] for v in voxel_vectors],
            "shape": list(arr.shape),
        }
        members = {
            "grid": self._json_member(f"volumes/{stem}_grid.json", grid),
            "data": self._binary_member(f"volumes/{stem}.dat", arr, dtype),
        }
        section: dict[str, Any] = {"id": self._reserve_id(sid), "kind": kind,
                                   "members": members}
        if label is not None:
            section["label"] = label
        if component is not None:
            section["component"] = component
        if kind == "volume.difference" and (operand_a or operand_b):
            if not (operand_a and operand_b):
                raise ValueError("volume.difference needs both operand_a and operand_b")
            section["operand_a"] = operand_a
            section["operand_b"] = operand_b
            if description is not None:
                section["description"] = description
        return self._push(section)

    def add_density(self, data, origin, voxel_vectors, **kw) -> str:
        return self.add_volume("volume.density", data, origin, voxel_vectors, **kw)

    def add_orbital(self, data, origin, voxel_vectors, **kw) -> str:
        return self.add_volume("volume.orbital", data, origin, voxel_vectors, **kw)

    def add_basis_ao(self, ao_metadata: Mapping[str, Any], data: np.ndarray,
                    origin: Sequence[float], voxel_vectors: Sequence[Sequence[float]],
                    *, label: str | None = None, dtype: str = "float32",
                    section_id: str | None = None) -> str:
        """Add a ``basis.ao`` section: one AO evaluated on a grid + quantum
        numbers in the section-level ``ao_metadata`` peer field."""
        arr = np.asarray(data)
        if arr.ndim != 3:
            raise ValueError(f"basis.ao: data must be 3-D, got ndim={arr.ndim}")
        sid = section_id or f"ao_{len(self._sections)}"
        grid = {
            "origin": [float(x) for x in origin],
            "voxel_vectors": [[float(x) for x in v] for v in voxel_vectors],
            "shape": list(arr.shape),
        }
        members = {
            "grid": self._json_member(f"basis_ao/{sid}_grid.json", grid),
            "data": self._binary_member(f"basis_ao/{sid}.dat", arr, dtype),
        }
        section: dict[str, Any] = {"id": self._reserve_id(sid), "kind": "basis.ao",
                                   "members": members,
                                   "ao_metadata": dict(ao_metadata)}
        if label is not None:
            section["label"] = label
        return self._push(section)

    # -- wavefunction -----------------------------------------------------

    def add_wavefunction_gto(self, shells: Sequence[Mapping[str, Any]], *,
                            mo_coefficients: np.ndarray | None = None,
                            mo_coefficients_alpha: np.ndarray | None = None,
                            mo_coefficients_beta: np.ndarray | None = None,
                            energies: Sequence[float] | None = None,
                            occupations: Sequence[float] | None = None,
                            energies_alpha: Sequence[float] | None = None,
                            occupations_alpha: Sequence[float] | None = None,
                            energies_beta: Sequence[float] | None = None,
                            occupations_beta: Sequence[float] | None = None,
                            structure_ref: str = "structure",
                            orbital_kind: str = "canonical",
                            pure: bool = True,
                            k_point: Sequence[float] | None = None,
                            coeffs_are_libint_normalized: bool = False,
                            section_id: str = "wf") -> str:
        """Add a ``wavefunction.gto`` section (spec § 5.3 + Appendix A).

        ``shells`` are ``{"center", "l", "exponents": [...],
        "coefficients": [...], "pure"?}``. ``mo_coefficients`` is ``[n_mo, n_ao]``
        (rows are MOs); for unrestricted pass ``*_alpha`` + ``*_beta`` instead.

        If your engine stores contraction coefficients pre-multiplied by the
        primitive norm ``N_i`` (libint / libcint / GBW-style), pass
        ``coeffs_are_libint_normalized=True`` and this writer divides them out so
        they apply to ``N_i``-normalized primitives, as the format requires
        (spec Appendix A.1 -- ``N_i`` is the shell's *axial* norm, one factor
        per shell from the total ``l``, not a per-component unit norm).
        """
        out_shells = []
        for sh in shells:
            l = int(sh["l"])
            exps = [float(x) for x in sh["exponents"]]
            coeffs = [float(c) for c in sh["coefficients"]]
            if coeffs_are_libint_normalized:
                coeffs = [c / primitive_norm(a, l) for a, c in zip(exps, coeffs)]
            out_shells.append({
                "center": int(sh["center"]), "l": l,
                "exponents": exps, "coefficients": coeffs,
                "pure": bool(sh.get("pure", pure)),
            })
        n_ao = 0
        for sh in out_shells:
            l = sh["l"]
            n_ao += (2 * l + 1) if sh["pure"] else ((l + 1) * (l + 2) // 2)

        basis_json = {"structure_ref": structure_ref, "pure": pure,
                      "n_ao": n_ao, "shells": out_shells}
        members = {"basis": self._json_member(
            f"{section_id}/basis.json", basis_json)}

        if mo_coefficients is not None:
            C = np.asarray(mo_coefficients, dtype=np.float64)
            n_mo = int(C.shape[0])
            mo_meta: dict[str, Any] = {
                "n_mo": n_mo, "n_ao": n_ao, "spin": "restricted",
                "orbital_kind": orbital_kind,
                "energies": list(map(float, energies)) if energies is not None
                else [0.0] * n_mo,
                "occupations": list(map(float, occupations)) if occupations is not None
                else [0.0] * n_mo,
            }
            if k_point is not None:
                mo_meta["k_point"] = [float(x) for x in k_point]
            members["mo_metadata"] = self._json_member(
                f"{section_id}/mo_metadata.json", mo_meta)
            members["mo_coefficients"] = self._binary_member(
                f"{section_id}/mo_coefficients.dat", C, "float64")
        elif mo_coefficients_alpha is not None and mo_coefficients_beta is not None:
            Ca = np.asarray(mo_coefficients_alpha, dtype=np.float64)
            Cb = np.asarray(mo_coefficients_beta, dtype=np.float64)
            mo_meta = {
                "n_ao": n_ao, "spin": "unrestricted", "orbital_kind": orbital_kind,
                "alpha": {
                    "n_mo": int(Ca.shape[0]),
                    "energies": list(map(float, energies_alpha)) if energies_alpha
                    is not None else [0.0] * int(Ca.shape[0]),
                    "occupations": list(map(float, occupations_alpha)) if
                    occupations_alpha is not None else [0.0] * int(Ca.shape[0]),
                },
                "beta": {
                    "n_mo": int(Cb.shape[0]),
                    "energies": list(map(float, energies_beta)) if energies_beta
                    is not None else [0.0] * int(Cb.shape[0]),
                    "occupations": list(map(float, occupations_beta)) if
                    occupations_beta is not None else [0.0] * int(Cb.shape[0]),
                },
            }
            if k_point is not None:
                mo_meta["k_point"] = [float(x) for x in k_point]
            members["mo_metadata"] = self._json_member(
                f"{section_id}/mo_metadata.json", mo_meta)
            members["mo_coefficients_alpha"] = self._binary_member(
                f"{section_id}/mo_coefficients_alpha.dat", Ca, "float64")
            members["mo_coefficients_beta"] = self._binary_member(
                f"{section_id}/mo_coefficients_beta.dat", Cb, "float64")
        else:
            raise ValueError("provide mo_coefficients or both alpha and beta")

        return self._push({"id": self._reserve_id(section_id),
                          "kind": "wavefunction.gto", "members": members})

    # -- atom properties --------------------------------------------------

    def add_atom_properties(self, *, mulliken_charge: Sequence[float] | None = None,
                           loewdin_charge: Sequence[float] | None = None,
                           spin_population: Sequence[float] | None = None,
                           section_id: str = "atom_properties") -> str:
        """Add an ``atom_properties`` section. Each array is float64 [n_atoms]."""
        members: dict[str, Any] = {}
        for role, arr in (("mulliken_charge", mulliken_charge),
                          ("loewdin_charge", loewdin_charge),
                          ("spin_population", spin_population)):
            if arr is not None:
                members[role] = self._binary_member(
                    f"atom_properties/{role}.bin", np.asarray(arr), "float64")
        if not members:
            raise ValueError("atom_properties needs at least one array")
        return self._push({"id": self._reserve_id(section_id),
                          "kind": "atom_properties", "members": members})

    # -- trajectories / reactions / scans --------------------------------

    def add_trajectory(self, metadata: Mapping[str, Any], coords: np.ndarray, *,
                      section_id: str = "trajectory") -> str:
        """Add a ``trajectory`` section. ``coords`` is float64
        [n_frames, n_atoms, 3] in Å."""
        arr = np.asarray(coords, dtype=np.float64)
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise ValueError("trajectory coords must be [n_frames, n_atoms, 3]")
        members = {
            "metadata": self._json_member(f"{section_id}/metadata.json",
                                          dict(metadata)),
            "coords": self._binary_member(f"{section_id}/coords.bin", arr, "float64"),
        }
        return self._push({"id": self._reserve_id(section_id), "kind": "trajectory",
                          "members": members})

    def add_reaction_path(self, metadata: Mapping[str, Any], coords: np.ndarray, *,
                         lattice: np.ndarray | None = None,
                         section_id: str = "reaction_path") -> str:
        """Add a ``reaction.path`` section (trajectory layout + waypoint
        annotations carried in ``metadata``).

        ``lattice`` (optional) marks the path **periodic**: float64 with shape
        ``[3, 3]`` (fixed cell) or ``[n_frames, 3, 3]`` (variable cell), columns
        = a, b, c, in **bohr**. Its presence — not the manifest version — is how
        a consumer detects a periodic reaction path (spec § 5.5). A path without
        ``lattice`` is unambiguously molecular.
        """
        arr = np.asarray(coords, dtype=np.float64)
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise ValueError("reaction.path coords must be [n_frames, n_atoms, 3]")
        members = {
            "metadata": self._json_member(f"{section_id}/metadata.json",
                                          dict(metadata)),
            "coords": self._binary_member(f"{section_id}/coords.bin", arr, "float64"),
        }
        if lattice is not None:
            lat = np.asarray(lattice, dtype=np.float64)
            if lat.shape != (3, 3) and not (lat.ndim == 3 and lat.shape[1:] == (3, 3)):
                raise ValueError(
                    "reaction.path lattice must be [3, 3] or [n_frames, 3, 3]; "
                    f"got shape {tuple(lat.shape)}")
            if lat.ndim == 3 and lat.shape[0] != arr.shape[0]:
                raise ValueError(
                    f"reaction.path per-frame lattice has {lat.shape[0]} frames "
                    f"but coords has {arr.shape[0]}")
            members["lattice"] = self._binary_member(
                f"{section_id}/lattice.bin", lat, "float64")
        return self._push({"id": self._reserve_id(section_id),
                          "kind": "reaction.path", "members": members})

    def add_reaction_waypoints(self, trajectory_ref: str,
                              waypoints: Mapping[str, Any], *,
                              section_id: str = "reaction_waypoints") -> str:
        """Add a ``reaction.waypoints`` annotation over an existing trajectory."""
        if trajectory_ref not in self._ids:
            raise ValueError(f"trajectory_ref {trajectory_ref!r} not yet added")
        member = self._json_member(f"{section_id}/waypoints.json", dict(waypoints))
        return self._push({"id": self._reserve_id(section_id),
                          "kind": "reaction.waypoints",
                          "trajectory_ref": trajectory_ref,
                          "members": {"waypoints": member}})

    def add_scan_surface(self, metadata: Mapping[str, Any], axis_a: Sequence[float],
                        axis_b: Sequence[float], energies: np.ndarray, *,
                        geometries: np.ndarray | None = None,
                        section_id: str = "scan_surface") -> str:
        """Add a ``scan.surface`` 2-D relaxed-scan energy surface."""
        members = {
            "metadata": self._json_member(f"{section_id}/metadata.json",
                                          dict(metadata)),
            "axis_a": self._binary_member(f"{section_id}/axis_a.bin",
                                          np.asarray(axis_a), "float64"),
            "axis_b": self._binary_member(f"{section_id}/axis_b.bin",
                                          np.asarray(axis_b), "float64"),
            "energies": self._binary_member(f"{section_id}/energies.bin",
                                            np.asarray(energies), "float64"),
        }
        if geometries is not None:
            members["geometries"] = self._binary_member(
                f"{section_id}/geometries.bin", np.asarray(geometries), "float64")
        return self._push({"id": self._reserve_id(section_id), "kind": "scan.surface",
                          "members": members})

    # -- vibrations / spectra --------------------------------------------

    def add_vibrations(self, metadata: Mapping[str, Any], displacements: np.ndarray,
                      *, section_id: str = "vibrations") -> str:
        """Add a ``vibrations`` section. ``displacements`` is float64
        [n_modes, n_atoms, 3]; ``metadata.frequencies`` in cm⁻¹."""
        arr = np.asarray(displacements, dtype=np.float64)
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise ValueError("displacements must be [n_modes, n_atoms, 3]")
        members = {
            "metadata": self._json_member(f"{section_id}/metadata.json",
                                          dict(metadata)),
            "displacements": self._binary_member(
                f"{section_id}/displacements.bin", arr, "float64"),
        }
        return self._push({"id": self._reserve_id(section_id), "kind": "vibrations",
                          "members": members})

    _SPECTRA_KINDS = frozenset({
        "spectra.ir", "spectra.raman", "spectra.uvvis", "spectra.ecd",
        "spectra.vcd", "spectra.nmr", "spectra.epr", "spectra.generic",
    })

    def add_spectrum(self, kind: str, *,
                    frequencies: Sequence[float] | None = None,
                    intensities: Sequence[float] | None = None,
                    payload: Mapping[str, Any] | None = None,
                    label: str | None = None,
                    section_id: str | None = None) -> str:
        """Add a ``spectra.*`` section. Pass ``frequencies``+``intensities`` for
        the simple 1-D kinds, or a full ``payload`` dict (required for
        ``spectra.nmr``; see spec § 5.4)."""
        if kind not in self._SPECTRA_KINDS:
            raise ValueError(f"{kind!r} is not a spectra kind")
        if payload is None:
            if frequencies is None or intensities is None:
                raise ValueError(f"{kind}: pass frequencies+intensities or payload")
            payload = {"frequencies": [float(x) for x in frequencies],
                       "intensities": [float(x) for x in intensities]}
        sid = section_id or kind.replace(".", "_")
        member = self._json_member(f"spectra/{sid}.json", dict(payload))
        section: dict[str, Any] = {"id": self._reserve_id(sid), "kind": kind,
                                   "members": {"spectrum": member}}
        if label is not None:
            section["label"] = label
        return self._push(section)

    # -- bands / dos ------------------------------------------------------

    def add_bands(self, kpath: Mapping[str, Any], eigenvalues: np.ndarray, *,
                 projections: np.ndarray | None = None,
                 section_id: str = "bands") -> str:
        """Add a ``bands`` section. ``eigenvalues`` is float64
        [n_spin, n_k, n_bands] in eV; optional ``projections``
        [n_k, n_bands, n_channels] for fat bands."""
        eig = np.asarray(eigenvalues, dtype=np.float64)
        if eig.ndim != 3:
            raise ValueError("eigenvalues must be [n_spin, n_kpoints, n_bands]")
        members = {
            "kpath": self._json_member(f"{section_id}/kpath.json", dict(kpath)),
            "eigenvalues": self._binary_member(f"{section_id}/eigenvalues.bin",
                                               eig, "float64"),
        }
        if projections is not None:
            members["projections"] = self._binary_member(
                f"{section_id}/projections.bin",
                np.asarray(projections, dtype=np.float64), "float64")
        return self._push({"id": self._reserve_id(section_id), "kind": "bands",
                          "members": members})

    def add_dos_total(self, energies: Sequence[float], dos: np.ndarray, *,
                     smearing: float | None = None, smearing_type: str | None = None,
                     fermi_energy_ev: float | None = None,
                     n_electrons: float | None = None, n_spin: int = 1,
                     section_id: str = "dos_total") -> str:
        """Add a ``dos.total`` section. Metadata (smearing, Fermi level, …) is
        carried as section-level peer fields, not members (schema constraint)."""
        members = {
            "energies": self._binary_member(f"dos/{section_id}_energies.bin",
                                            np.asarray(energies), "float64"),
            "dos": self._binary_member(f"dos/{section_id}.bin",
                                       np.asarray(dos), "float64"),
        }
        section: dict[str, Any] = {"id": self._reserve_id(section_id),
                                   "kind": "dos.total", "members": members,
                                   "n_spin": int(n_spin)}
        for k, v in (("smearing", smearing), ("smearing_type", smearing_type),
                     ("fermi_energy_ev", fermi_energy_ev),
                     ("n_electrons", n_electrons)):
            if v is not None:
                section[k] = v
        return self._push(section)

    def add_dos_projected(self, energies: Sequence[float], projections: np.ndarray,
                         channels: Sequence[Mapping[str, Any]], *, n_spin: int = 1,
                         fermi_energy_ev: float | None = None,
                         section_id: str = "dos_projected") -> str:
        """Add a ``dos.projected`` section. ``channels`` (labels) ride as a
        section-level peer field."""
        members = {
            "energies": self._binary_member(f"dos/{section_id}_energies.bin",
                                            np.asarray(energies), "float64"),
            "projections": self._binary_member(f"dos/{section_id}_projections.bin",
                                               np.asarray(projections), "float64"),
        }
        section: dict[str, Any] = {"id": self._reserve_id(section_id),
                                   "kind": "dos.projected", "members": members,
                                   "n_spin": int(n_spin),
                                   "channels": [dict(c) for c in channels]}
        if fermi_energy_ev is not None:
            section["fermi_energy_ev"] = fermi_energy_ev
        return self._push(section)

    def add_dos_coop_cohp(self, kind: str, energies: Sequence[float],
                         projections: np.ndarray, integrated: np.ndarray,
                         meta: Mapping[str, Any], *, section_id: str | None = None
                         ) -> str:
        """Add a ``dos.coop`` or ``dos.cohp`` section (bonding analysis). Here
        ``meta`` IS a member (JSON), unlike dos.total/projected."""
        if kind not in ("dos.coop", "dos.cohp"):
            raise ValueError("kind must be dos.coop or dos.cohp")
        sid = section_id or kind.replace(".", "_")
        members = {
            "energies": self._binary_member(f"dos/{sid}_energies.bin",
                                            np.asarray(energies), "float64"),
            "projections": self._binary_member(f"dos/{sid}_projections.bin",
                                               np.asarray(projections), "float64"),
            "integrated": self._binary_member(f"dos/{sid}_integrated.bin",
                                              np.asarray(integrated), "float64"),
            "meta": self._json_member(f"dos/{sid}_meta.json", dict(meta)),
        }
        return self._push({"id": self._reserve_id(sid), "kind": kind,
                          "members": members})

    # -- symmetry / scf history / citations ------------------------------

    def add_structure_symmetry(self, data: Mapping[str, Any], *,
                              section_id: str = "symmetry") -> str:
        member = self._json_member(f"structure/symmetry.json", dict(data))
        return self._push({"id": self._reserve_id(section_id),
                          "kind": "structure.symmetry",
                          "members": {"data": member}})

    def add_scf_history(self, iterations: Sequence[Mapping[str, Any]], *,
                       section_id: str = "scf_history") -> str:
        """Add an ``scf_history`` section. Each iteration is
        ``{iter, energy_eh, delta_e?, diis_error?}``."""
        member = self._json_member(f"{section_id}/iterations.json",
                                   {"iterations": [dict(i) for i in iterations]})
        return self._push({"id": self._reserve_id(section_id), "kind": "scf_history",
                          "members": {"iterations": member}})

    def add_citations(self, bibtex: str, *, section_id: str = "citations") -> str:
        """Add a ``citations`` section from a BibTeX string."""
        data = bibtex.encode("utf-8") if isinstance(bibtex, str) else bytes(bibtex)
        path = f"{section_id}/references.bib"
        self._add_file(path, data)
        member = {"path": path, "format": "binary", "sha256": _sha256_hex(data)}
        return self._push({"id": self._reserve_id(section_id), "kind": "citations",
                          "members": {"references": member}})

    def add_run_record(self, *, program: str,
                       input_text: str | bytes | None = None,
                       log_text: str | bytes | None = None,
                       program_version: str | None = None,
                       command: str | None = None,
                       exit_status: int | None = None,
                       started_utc: str | None = None,
                       finished_utc: str | None = None,
                       sequence: int | None = None,
                       files: Mapping[str, Any] | None = None,
                       attachments: Mapping[str, bytes] | None = None,
                       section_id: str = "run_record") -> str:
        """Add a ``run.record`` section — the self-contained record of one
        program invocation.

        ``program`` names the code the input/log belong to (e.g. ``"orca"``),
        which may differ from the archive-level ``source.program`` when the
        QVF is written by a converter. At least one of ``input_text`` /
        ``log_text`` is required; both are stored as opaque UTF-8 bytes.
        ``attachments`` maps a role suffix to raw bytes, stored as members
        named ``attachment.<suffix>``; describe original filenames in the
        optional ``files`` index (role -> {filename, description?, media_type?}).
        """
        if not program:
            raise ValueError("run.record requires a non-empty program")
        if input_text is None and log_text is None:
            raise ValueError("run.record requires input_text and/or log_text")
        sid = self._reserve_id(section_id)
        members: dict[str, Any] = {}

        def _opaque(role: str, path: str, payload: str | bytes) -> None:
            data = (payload.encode("utf-8") if isinstance(payload, str)
                    else bytes(payload))
            self._add_file(path, data)
            members[role] = {"path": path, "format": "binary",
                             "sha256": _sha256_hex(data)}

        if input_text is not None:
            _opaque("input", f"{section_id}/input.txt", input_text)
        if log_text is not None:
            _opaque("log", f"{section_id}/log.txt", log_text)
        for suffix, blob in (attachments or {}).items():
            _opaque(f"attachment.{suffix}",
                    f"{section_id}/attachments/{suffix}", blob)
        if files is not None:
            members["files"] = self._json_member(f"{section_id}/files.json",
                                                 dict(files))
        section: dict[str, Any] = {"id": sid, "kind": "run.record",
                                   "program": program, "members": members}
        if program_version is not None:
            section["program_version"] = program_version
        if command is not None:
            section["command"] = command
        if exit_status is not None:
            section["exit_status"] = int(exit_status)
        if started_utc is not None:
            section["started_utc"] = started_utc
        if finished_utc is not None:
            section["finished_utc"] = finished_utc
        if sequence is not None:
            section["sequence"] = int(sequence)
        return self._push(section)

    def add_job_spec(self, *, job_type: str,
                     method: str | None = None,
                     basis: str | None = None,
                     functional: str | None = None,
                     charge: int | None = None,
                     multiplicity: int | None = None,
                     kpoints: Sequence[int] | None = None,
                     tasks: Sequence[str] | None = None,
                     options: Mapping[str, Any] | None = None,
                     section_id: str = "job_spec") -> str:
        """Add a ``job.spec`` section — the declarative specification of the
        calculation this archive *requests* (QVF spec § 5.9).

        ``job_type`` is ``"molecular"`` or ``"periodic"`` and selects which
        class of engine runs the job; the geometry itself (including
        periodicity) lives in the archive's ``structure`` section. Engine
        keywords beyond the typed fields go under ``options``. Pair with
        ``set_provenance(run_status="pending")`` for an archive describing a
        job that has not yet run.
        """
        if job_type not in ("molecular", "periodic"):
            raise ValueError(
                f"job.spec job_type must be 'molecular' or 'periodic', "
                f"got {job_type!r}")
        payload: dict[str, Any] = {"job_type": job_type}
        if method is not None:
            payload["method"] = str(method)
        if basis is not None:
            payload["basis"] = str(basis)
        if functional is not None:
            payload["functional"] = str(functional)
        if charge is not None:
            payload["charge"] = int(charge)
        if multiplicity is not None:
            payload["multiplicity"] = int(multiplicity)
        if kpoints is not None:
            mesh = [int(n) for n in kpoints]
            if len(mesh) != 3 or any(n < 1 for n in mesh):
                raise ValueError(
                    f"job.spec kpoints must be three integers >= 1, "
                    f"got {list(kpoints)!r}")
            payload["kpoints"] = mesh
        if tasks is not None:
            payload["tasks"] = [str(t) for t in tasks]
        if options is not None:
            payload["options"] = dict(options)
        sid = self._reserve_id(section_id)
        member = self._json_member(f"{sid}/spec.json", payload)
        return self._push({"id": sid, "kind": "job.spec",
                          "members": {"spec": member}})

    # -- periodic-only kinds ---------------------------------------------

    def add_fermi_surface(self, mesh: Mapping[str, Any], energies: np.ndarray, *,
                         section_id: str = "fermi_surface") -> str:
        """Add a ``fermi_surface`` section. ``energies`` is
        [nk1, nk2, nk3, n_bands] float32/64 in eV (signed E(k)-E_F)."""
        arr = np.asarray(energies)
        if arr.ndim != 4:
            raise ValueError("fermi_surface energies must be 4-D")
        members = {
            "mesh": self._json_member(f"fermi/{section_id}_mesh.json", dict(mesh)),
            "energies": self._binary_member(f"fermi/{section_id}.bin", arr,
                                            "float64" if arr.dtype == np.float64
                                            else "float32"),
        }
        return self._push({"id": self._reserve_id(section_id), "kind": "fermi_surface",
                          "members": members})

    def add_phonon_bands(self, qpath: Mapping[str, Any], frequencies: np.ndarray, *,
                        eigenvectors: np.ndarray | None = None,
                        section_id: str = "phonon_bands") -> str:
        """Add a ``phonon_bands`` section. ``frequencies`` is [n_q, n_modes] cm⁻¹."""
        members = {
            "qpath": self._json_member(f"phonons/{section_id}_qpath.json",
                                       dict(qpath)),
            "frequencies": self._binary_member(f"phonons/{section_id}_freq.bin",
                                               np.asarray(frequencies), "float64"),
        }
        if eigenvectors is not None:
            members["eigenvectors"] = self._binary_member(
                f"phonons/{section_id}_eig.bin", np.asarray(eigenvectors), "float64")
        return self._push({"id": self._reserve_id(section_id), "kind": "phonon_bands",
                          "members": members})

    def add_phonon_dos(self, meta: Mapping[str, Any], frequencies: Sequence[float],
                      dos: np.ndarray, *, projected: np.ndarray | None = None,
                      section_id: str = "phonon_dos") -> str:
        """Add a ``phonon_dos`` section."""
        members = {
            "meta": self._json_member(f"phonons/{section_id}_meta.json", dict(meta)),
            "frequencies": self._binary_member(f"phonons/{section_id}_freq.bin",
                                               np.asarray(frequencies), "float64"),
            "dos": self._binary_member(f"phonons/{section_id}_dos.bin",
                                       np.asarray(dos), "float64"),
        }
        if projected is not None:
            members["projected"] = self._binary_member(
                f"phonons/{section_id}_proj.bin", np.asarray(projected), "float64")
        return self._push({"id": self._reserve_id(section_id), "kind": "phonon_dos",
                          "members": members})

    def add_equation_of_state(self, volumes: Sequence[float],
                             energies: Sequence[float], fit: Mapping[str, Any], *,
                             section_id: str = "eos") -> str:
        """Add an ``equation_of_state`` section. ``volumes`` Å³, ``energies`` eV,
        ``fit`` carries model + V0/E0/B0/B0_prime."""
        members = {
            "volumes": self._binary_member(f"eos/{section_id}_volumes.bin",
                                           np.asarray(volumes), "float64"),
            "energies": self._binary_member(f"eos/{section_id}_energies.bin",
                                            np.asarray(energies), "float64"),
            "fit": self._json_member(f"eos/{section_id}_fit.json", dict(fit)),
        }
        return self._push({"id": self._reserve_id(section_id),
                          "kind": "equation_of_state", "members": members})

    def add_topology_qtaim(self, critical_points: Mapping[str, Any], *,
                          section_id: str = "qtaim") -> str:
        """Add a ``topology.qtaim`` section (critical points + optional bond
        paths)."""
        member = self._json_member(f"topology/{section_id}.json",
                                   dict(critical_points))
        return self._push({"id": self._reserve_id(section_id), "kind": "topology.qtaim",
                          "members": {"critical_points": member}})

    # -- vendor escape hatch ---------------------------------------------

    def add_vendor_section(self, kind: str, *,
                          json_members: Mapping[str, Any] | None = None,
                          binary_members: Mapping[str, tuple] | None = None,
                          critical: bool = False, schema_uri: str | None = None,
                          label: str | None = None,
                          section_id: str | None = None) -> str:
        """Add an ``x_<vendor>.*`` section. ``json_members`` maps role -> object;
        ``binary_members`` maps role -> ``(array, dtype)``. If ``critical`` is set,
        remember to declare the namespace via :meth:`set_extensions`."""
        if not _VENDOR_RE.match(kind):
            raise ValueError(f"vendor kind {kind!r} must match x_<vendor>.*")
        sid = section_id or kind.replace(".", "_").replace("x_", "x_", 1)
        prefix = sid
        members: dict[str, Any] = {}
        for role, obj in (json_members or {}).items():
            members[role] = self._json_member(f"{prefix}/{role}.json", obj)
        for role, spec in (binary_members or {}).items():
            arr, dtype = spec
            members[role] = self._binary_member(f"{prefix}/{role}.bin", arr, dtype)
        if not members:
            raise ValueError("vendor section needs at least one member")
        section: dict[str, Any] = {"id": self._reserve_id(sid), "kind": kind,
                                   "members": members}
        if critical:
            section["critical"] = True
        if schema_uri is not None:
            section["schema_uri"] = schema_uri
        if label is not None:
            section["label"] = label
        return self._push(section)

    # -- output -----------------------------------------------------------

    def build_manifest(self) -> dict[str, Any]:
        """Return the manifest object (dict) without writing anything."""
        manifest: dict[str, Any] = {
            "qvf_version": QVF_VERSION,
            "schema_uri": _SCHEMA_URI,
            "source": dict(self._source),
        }
        for key in ("provenance", "thermochemistry", "dipole_moment",
                    "constraints", "extensions", "viewer_defaults"):
            if key in self._root:
                manifest[key] = self._root[key]
        manifest["sections"] = self._sections
        return manifest

    def to_bytes(self, *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
        """Serialize the archive to an in-memory ZIP and return its bytes."""
        import io
        buf = io.BytesIO()
        manifest_bytes = _json_bytes(self.build_manifest())
        with zipfile.ZipFile(buf, "w", compression=compression) as zf:
            # manifest.json stored uncompressed for cheap table-of-contents reads.
            zf.writestr(zipfile.ZipInfo("manifest.json"), manifest_bytes,
                        compress_type=zipfile.ZIP_STORED)
            for path, data in self._files.items():
                zf.writestr(path, data)
        return buf.getvalue()

    def write(self, path: str, *, compression: int = zipfile.ZIP_DEFLATED) -> str:
        """Write ``{path}`` (``.qvf`` appended if missing). Returns the path."""
        if not str(path).endswith(".qvf"):
            path = f"{path}.qvf"
        with open(path, "wb") as fh:
            fh.write(self.to_bytes(compression=compression))
        return path
