"""qvf_model -- the typed manifest model: Manifest, Section and MemberSpec.

Dataclasses built from and written back to ``manifest.json`` (spec § 3, § 4),
the Python counterpart of the C++ ``qvf/model.hpp``. The model is lossless:
:meth:`Manifest.from_json` types every field it knows when the field has the
JSON type the schema gives it, and keeps everything else verbatim in the
``extra`` dict of the enclosing record -- keys the model does not know
(kind-specific section fields such as ``operand_a`` or ``ao_metadata``, vendor
keys) and known keys whose value has another type. :meth:`Manifest.to_json`
writes the typed fields, then ``extra``, so ``Manifest.from_json(m).to_json()
== m`` for any manifest dict ``m``. Absent and present are told apart: an
absent field is ``None``.

The model checks nothing; :func:`qvf_reader.validate_qvf` does::

    from qvf_model import Manifest
    from qvf_reader import QvfReader

    with QvfReader("water.qvf") as r:
        m = Manifest.from_json(r.manifest)
        for s in m.sections or []:
            print(s.id, s.kind, [role for role in s.members or {}])

License: Apache-2.0.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any, Dict, List, Optional

__all__ = ["MemberSpec", "Section", "Manifest", "Source"]

_FORMATS = ("json", "binary")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


@dataclasses.dataclass
class Source:
    """The root ``source`` block (spec § 3.1)."""

    program: str
    version: str
    calculation: str


@dataclasses.dataclass
class MemberSpec:
    """One entry of a section's ``members`` object (spec § 4.2).

    ``format`` is ``"json"``, ``"binary"`` (format binary with a dtype: a typed
    array) or ``"opaque"`` (format binary without one).
    """

    path: Optional[str] = None
    format: Optional[str] = None
    dtype: Optional[str] = None
    shape: Optional[List[int]] = None
    sha256: Optional[str] = None
    size: Optional[int] = None
    media_type: Optional[str] = None
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_json(cls, j: Any) -> "MemberSpec":
        if not isinstance(j, dict):
            raise TypeError("MemberSpec.from_json: not a JSON object")
        m = cls()
        for key, v in j.items():
            typed = False
            if key in ("path", "dtype", "sha256", "media_type") and isinstance(v, str):
                setattr(m, key, v)
                typed = True
            elif key == "size" and _is_int(v) and v >= 0:
                m.size = v
                typed = True
            elif key == "shape" and isinstance(v, list) and all(_is_int(d) for d in v):
                m.shape = list(v)
                typed = True
            elif key == "format" and v in _FORMATS:
                typed = True          # resolved below, once dtype is known
            if not typed:
                m.extra[key] = copy.deepcopy(v)
        fmt = j.get("format")
        if fmt in _FORMATS:
            m.format = "json" if fmt == "json" else ("binary" if m.dtype is not None
                                                     else "opaque")
        return m

    def to_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.path is not None:
            out["path"] = self.path
        if self.format is not None:
            out["format"] = "json" if self.format == "json" else "binary"
        if self.dtype is not None:
            out["dtype"] = self.dtype
        if self.shape is not None:
            out["shape"] = list(self.shape)
        if self.sha256 is not None:
            out["sha256"] = self.sha256
        if self.size is not None:
            out["size"] = self.size
        if self.media_type is not None:
            out["media_type"] = self.media_type
        out.update(copy.deepcopy(self.extra))
        return out


_SECTION_STRINGS = ("id", "kind", "label", "component", "structure_ref",
                    "run_ref", "group")


@dataclasses.dataclass
class Section:
    """One entry of the manifest's ``sections`` array (spec § 4.1).

    ``members`` maps role to spec in manifest order; it is None when the
    section has no ``members`` object of member-spec objects (``extra`` then
    holds it as is). ``extra`` also holds the kind-specific peer fields
    (``operand_a``, ``ao_metadata``, ``program``, ``chains``, ...).
    """

    id: Optional[str] = None
    kind: Optional[str] = None
    label: Optional[str] = None
    component: Optional[str] = None
    critical: Optional[bool] = None
    structure_ref: Optional[str] = None
    run_ref: Optional[str] = None
    group: Optional[str] = None
    members: Optional[Dict[str, MemberSpec]] = None
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def member(self, role: str) -> Optional[MemberSpec]:
        """The spec of member ``role``, or None."""
        return (self.members or {}).get(role)

    @classmethod
    def from_json(cls, j: Any) -> "Section":
        if not isinstance(j, dict):
            raise TypeError("Section.from_json: not a JSON object")
        s = cls()
        for key, v in j.items():
            typed = False
            if key in _SECTION_STRINGS and isinstance(v, str):
                setattr(s, key, v)
                typed = True
            elif key == "critical" and isinstance(v, bool):
                s.critical = v
                typed = True
            elif (key == "members" and isinstance(v, dict)
                  and all(isinstance(m, dict) for m in v.values())):
                s.members = {role: MemberSpec.from_json(m) for role, m in v.items()}
                typed = True
            if not typed:
                s.extra[key] = copy.deepcopy(v)
        return s

    def to_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key in ("id", "kind", "label", "component"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        if self.critical is not None:
            out["critical"] = self.critical
        for key in ("structure_ref", "run_ref", "group"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        if self.members is not None:
            out["members"] = {role: m.to_json() for role, m in self.members.items()}
        out.update(copy.deepcopy(self.extra))
        return out


_ROOT_BLOCKS = ("provenance", "metadata", "viewer_defaults", "thermochemistry",
                "dipole_moment", "constraints", "energies", "extensions")


@dataclasses.dataclass
class Manifest:
    """The whole ``manifest.json`` (spec § 3).

    ``source`` is typed when it is an object of exactly the three strings;
    the root blocks are kept as dicts when they are objects; ``sections`` is
    None when it is not an array of objects (``extra`` then holds it).
    """

    qvf_version: Optional[int] = None
    schema_uri: Optional[str] = None
    byte_order: Optional[str] = None
    source: Optional[Source] = None
    provenance: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    viewer_defaults: Optional[Dict[str, Any]] = None
    thermochemistry: Optional[Dict[str, Any]] = None
    dipole_moment: Optional[Dict[str, Any]] = None
    constraints: Optional[Dict[str, Any]] = None
    energies: Optional[Dict[str, Any]] = None
    extensions: Optional[Dict[str, Any]] = None
    sections: Optional[List[Section]] = None
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def section(self, section_id: str) -> Optional[Section]:
        """The section with this id (the first, should ids repeat), or None."""
        for s in self.sections or []:
            if s.id == section_id:
                return s
        return None

    @classmethod
    def from_json(cls, j: Any) -> "Manifest":
        if not isinstance(j, dict):
            raise TypeError("Manifest.from_json: not a JSON object")
        m = cls()
        for key, v in j.items():
            typed = False
            if key == "qvf_version" and _is_int(v):
                m.qvf_version = v
                typed = True
            elif key in ("schema_uri", "byte_order") and isinstance(v, str):
                setattr(m, key, v)
                typed = True
            elif (key == "source" and isinstance(v, dict)
                  and set(v) == {"program", "version", "calculation"}
                  and all(isinstance(x, str) for x in v.values())):
                m.source = Source(v["program"], v["version"], v["calculation"])
                typed = True
            elif (key == "sections" and isinstance(v, list)
                  and all(isinstance(s, dict) for s in v)):
                m.sections = [Section.from_json(s) for s in v]
                typed = True
            elif key in _ROOT_BLOCKS and isinstance(v, dict):
                setattr(m, key, copy.deepcopy(v))
                typed = True
            if not typed:
                m.extra[key] = copy.deepcopy(v)
        return m

    def to_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.qvf_version is not None:
            out["qvf_version"] = self.qvf_version
        for key in ("schema_uri", "byte_order"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        if self.source is not None:
            out["source"] = {"program": self.source.program,
                             "version": self.source.version,
                             "calculation": self.source.calculation}
        for key in _ROOT_BLOCKS:
            if getattr(self, key) is not None:
                out[key] = copy.deepcopy(getattr(self, key))
        if self.sections is not None:
            out["sections"] = [s.to_json() for s in self.sections]
        out.update(copy.deepcopy(self.extra))
        return out


@dataclasses.dataclass(frozen=True)
class Lattice:
    """A finite 3×3 cell stored as row vectors in angstrom (no NumPy)."""
    _rows: tuple

    def __post_init__(self):
        import math
        rows = tuple(tuple(float(value) for value in row) for row in self._rows)
        if len(rows) != 3 or any(len(row) != 3 for row in rows):
            raise ValueError("lattice must have shape [3, 3]")
        if not all(math.isfinite(value) for row in rows for value in row):
            raise ValueError("lattice must contain finite values")
        object.__setattr__(self, "_rows", rows)

    @classmethod
    def from_rows_angstrom(cls, rows):
        return cls(rows)

    @classmethod
    def from_columns_bohr(cls, columns):
        from .units import BOHR_PER_ANGSTROM
        checked = cls(columns)._rows
        return cls(tuple(tuple(checked[j][i] / BOHR_PER_ANGSTROM for j in range(3))
                         for i in range(3)))

    def rows_angstrom(self):
        return [list(row) for row in self._rows]

    def columns_bohr(self):
        from .units import BOHR_PER_ANGSTROM
        return [[self._rows[j][i] * BOHR_PER_ANGSTROM for j in range(3)] for i in range(3)]

    def volume_angstrom3(self):
        a, b, c = self._rows
        return abs(a[0] * (b[1] * c[2] - b[2] * c[1])
                   - a[1] * (b[0] * c[2] - b[2] * c[0])
                   + a[2] * (b[0] * c[1] - b[1] * c[0]))

    def volume_bohr3(self):
        from .units import BOHR_PER_ANGSTROM
        return self.volume_angstrom3() * BOHR_PER_ANGSTROM ** 3


@dataclasses.dataclass(frozen=True)
class GridSpec:
    """Volume-grid geometry, expressed in bohr; no implicit conversion."""
    origin: tuple
    voxel_vectors: tuple
    shape: tuple
    periodic: tuple = (False, False, False)
    includes_endpoint: bool = True

    def __post_init__(self):
        import math
        origin = tuple(float(x) for x in self.origin)
        vectors = Lattice(self.voxel_vectors)._rows
        shape, periodic = tuple(self.shape), tuple(self.periodic)
        if len(origin) != 3 or not all(math.isfinite(x) for x in origin):
            raise ValueError("grid origin must have three finite values")
        if len(shape) != 3 or any(not _is_int(n) or n < 1 for n in shape):
            raise ValueError("grid shape must have three positive integers")
        if len(periodic) != 3 or any(not isinstance(p, bool) for p in periodic):
            raise ValueError("grid periodic must have three booleans")
        if not isinstance(self.includes_endpoint, bool):
            raise ValueError("includes_endpoint must be boolean")
        for key, value in (("origin", origin), ("voxel_vectors", vectors),
                           ("shape", shape), ("periodic", periodic)):
            object.__setattr__(self, key, value)

    def to_json(self):
        return {"origin": list(self.origin), "voxel_vectors": [list(v) for v in self.voxel_vectors],
                "shape": list(self.shape), "periodic": list(self.periodic),
                "includes_endpoint": self.includes_endpoint}


__all__ += ["Lattice", "GridSpec"]
