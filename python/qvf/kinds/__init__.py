"""Lazy section views: typed member metadata, explicit JSON/tensor access.

All canonical and vendor sections have a SectionView. Structure, volume and
GTO views additionally expose their commonly used members as named properties.
No payload is loaded until an accessor is called.
"""
from __future__ import annotations

import dataclasses
from typing import ClassVar
from ..model import Section


@dataclasses.dataclass(frozen=True)
class SectionView:
    reader: object
    section: Section
    kind: ClassVar[str | None] = None

    @classmethod
    def from_reader(cls, reader, section):
        if cls.kind is not None and section.kind != cls.kind:
            raise TypeError(f"expected {cls.kind}, got {section.kind}")
        return cls(reader, section)

    def json(self, role, *, verify=True):
        return self.reader.json(self.section, role, verify=verify)

    def tensor(self, role, *, verify=True):
        return self.reader.tensor(self.section, role, verify=verify)

    def to_writer(self, writer):
        """Copy this section through bounded member streams, verifying hashes."""
        section = Section.from_json(self.section.to_json())
        section.members = {}
        sid = writer.add_section(section)
        for role, member in (self.section.members or {}).items():
            if member.format == "json":
                writer.add_json(sid, role, self.json(role))
            elif member.format == "binary":
                with writer.begin_binary(sid, role, member.dtype, member.shape) as sink:
                    self.reader.tensor_into(self.section, role, sink)
            else:
                writer.add_opaque(sid, role, self.reader.read_member(member),
                                  media_type=member.media_type)
        return sid


class Structure(SectionView):
    kind = "structure"

    @property
    def atoms(self):
        return self.json("structure")["atoms"]

    @property
    def lattice(self):
        from ..model import Lattice
        matrix = self.json("structure").get("lattice_vectors")
        return Lattice.from_rows_angstrom(matrix) if matrix is not None else None


class Volume(SectionView):
    @classmethod
    def from_reader(cls, reader, section):
        if not section.kind or not section.kind.startswith("volume."):
            raise TypeError(f"expected a volume kind, got {section.kind}")
        return cls(reader, section)

    @property
    def grid(self):
        return self.json("grid")

    @property
    def data(self):
        return self.tensor("data")


class WavefunctionGTO(SectionView):
    kind = "wavefunction.gto"

    @property
    def basis(self):
        return self.json("basis")

    @property
    def mo_metadata(self):
        return self.json("mo_metadata")

    def coefficients(self, spin=None):
        if spin not in (None, "alpha", "beta"):
            raise ValueError("spin must be alpha, beta, or None")
        return self.tensor("mo_coefficients" + ("_" + spin if spin else ""))


def from_reader(reader, section):
    view_type = {"structure": Structure, "wavefunction.gto": WavefunctionGTO}.get(section.kind)
    if view_type is None:
        view_type = Volume if section.kind and section.kind.startswith("volume.") else SectionView
    return view_type.from_reader(reader, section)
