"""qvf_units — the QVF unit vocabulary and the length and energy conversions.

QVF names every declared unit with a **unit name** from a controlled
vocabulary (spec § 4.3, "Unit names"). The JSON Schema is the single source
of truth for it: ``$defs/UnitName`` lists the unit names and
``$defs/LegacyUnitName`` the deprecated spellings that a ``{value, units}``
object still accepts. ``scripts/gen_kinds.py`` generates both, and the units
each payload definition fixes, into ``qvf_kinds``, which this module reads, so
it cannot disagree with the schema (a test regenerates the tables and
compares).

Writers *declare* units and never convert. :func:`convert` is for code that
reads a declared unit and needs another one::

    from qvf_units import UNITS, canonical, convert, is_unit
    is_unit("ev")                       # True
    is_unit("eV")                       # False: a legacy spelling, not a name
    canonical("Eh")                     # "hartree"
    convert(1.0, "hartree", "ev")       # 27.211386245988
    convert(1.0, "angstrom", "bohr")    # 1.8897261246 (BOHR_PER_ANGSTROM)
    convert(300.0, "nm", "ev")          # photon energy of a 300 nm line

License: Apache-2.0.
"""

from __future__ import annotations

from typing import Any, Mapping

import qvf_kinds
from qvf_writer import BOHR_PER_ANGSTROM

__all__ = [
    "UNITS", "LEGACY_UNITS", "is_unit", "canonical", "convert", "fixed_units",
    "BOHR_PER_ANGSTROM", "HARTREE_IN_EV", "HARTREE_IN_KJ_PER_MOL",
    "HARTREE_IN_KCAL_PER_MOL", "HARTREE_IN_CM1", "EV_NM", "KJ_PER_KCAL",
]


#: The unit names of spec § 4.3, in the order of the schema's ``$defs/UnitName``.
UNITS: tuple[str, ...] = tuple(qvf_kinds.UNITS)
#: The deprecated spellings a ``{value, units}`` object accepts
#: (``$defs/LegacyUnitName``), in schema order.
LEGACY_UNITS: tuple[str, ...] = tuple(qvf_kinds.LEGACY_UNITS)

_UNIT_SET = frozenset(UNITS)
# The unit name each legacy spelling stands for (spec § 4.3, "Legacy spellings").
_LEGACY_CANONICAL = dict(qvf_kinds.LEGACY_CANONICAL)


def is_unit(name: Any) -> bool:
    """True if ``name`` is a unit name of spec § 4.3 (case-sensitive).

    A legacy spelling such as ``"eV"`` is not a unit name; :func:`canonical`
    maps it to one.
    """
    return isinstance(name, str) and name in _UNIT_SET


def canonical(name: Any) -> str:
    """The unit name for a unit name or a legacy spelling.

    ``canonical("Eh")`` and ``canonical("hartree")`` are both ``"hartree"``.
    Anything else raises ``ValueError``.
    """
    if is_unit(name):
        return name
    if isinstance(name, str) and name in _LEGACY_CANONICAL:
        return _LEGACY_CANONICAL[name]
    raise ValueError(f"{name!r} is not a QVF unit name (spec § 4.3)")


def fixed_units(defname: str) -> dict[str, str]:
    """The unit each key of a payload's ``units`` object is fixed to.

    ``defname`` is a payload definition of the schema, e.g.
    ``"VolumeGridPayload"`` → ``{"origin": "bohr", "voxel_vectors": "bohr"}``.
    Read from the ``const`` entries of the definition's ``units`` property,
    following ``allOf`` references; keys without a fixed unit are absent.
    """
    if defname not in qvf_kinds.SCHEMA_DEFS:
        raise KeyError(f"no $defs/{defname} in the schema")
    return dict(qvf_kinds.FIXED_UNITS.get(defname, {}))


# --- conversions ---------------------------------------------------------
# CODATA 2018 recommended values. The SI defining constants h, c, e and N_A
# are exact since 2019, so the factors below that follow from them alone are
# exact up to the printed digits.

#: Hartree energy in eV: E_h = 27.211386245988 eV (CODATA 2018).
HARTREE_IN_EV = 27.211386245988
#: E_h N_A in kJ/mol: 4.3597447222071e-18 J (CODATA 2018) × 6.02214076e23
#: mol⁻¹ (exact) = 2625.4996394799 kJ/mol.
HARTREE_IN_KJ_PER_MOL = 2625.4996394799
#: The thermochemical calorie: 1 kcal = 4.184 kJ (exact).
KJ_PER_KCAL = 4.184
#: E_h N_A in kcal/mol: 2625.4996394799 / 4.184 = 627.5094740631 kcal/mol.
HARTREE_IN_KCAL_PER_MOL = HARTREE_IN_KJ_PER_MOL / KJ_PER_KCAL
#: E_h / (h c) in cm⁻¹: 2.1947463136320e7 m⁻¹ (CODATA 2018) = 219474.6313632 cm⁻¹.
HARTREE_IN_CM1 = 219474.6313632
#: h c / e in eV·nm: 6.62607015e-34 J s × 299792458 m/s / 1.602176634e-19 C
#: = 1239.841984332 eV·nm (exact constants), the photon energy–wavelength
#: relation E[eV] = 1239.841984332 / λ[nm].
EV_NM = 1239.841984332

# Bohr per unit of each length unit; BOHR_PER_ANGSTROM is the writer's
# CODATA 2018 value (1 / 0.529177210903, ten decimals).
_BOHR_PER = {"bohr": 1.0, "angstrom": BOHR_PER_ANGSTROM}
# Units of each energy-like unit per hartree (cm⁻¹ through E = h c ν̃).
_PER_HARTREE = {
    "hartree": 1.0,
    "ev": HARTREE_IN_EV,
    "kj_per_mol": HARTREE_IN_KJ_PER_MOL,
    "kcal_per_mol": HARTREE_IN_KCAL_PER_MOL,
    "cm-1": HARTREE_IN_CM1,
}


def convert(value: Any, from_unit: str, to_unit: str) -> Any:
    """Convert ``value`` from ``from_unit`` to ``to_unit``.

    Handles the length pair ``angstrom`` ↔ ``bohr`` and the energies
    ``hartree``, ``ev``, ``kcal_per_mol``, ``kj_per_mol`` and ``cm-1`` (as an
    energy, E = h c ν̃), plus ``nm`` as a photon wavelength (E = h c / λ) to
    or from any of those energies. Molar units are per mole of particles, so
    1 hartree converts to 2625.4996394799 kJ/mol. Converting a unit to itself
    returns ``value`` unchanged. Legacy spellings are accepted for either
    unit. Any other pair raises ``ValueError``.

    ``value`` may be a number or anything that supports arithmetic with
    floats, such as a NumPy array. A wavelength or energy of zero has no
    counterpart across the ``nm`` relation.
    """
    src, dst = canonical(from_unit), canonical(to_unit)
    if src == dst:
        return value
    if src in _BOHR_PER and dst in _BOHR_PER:
        return value * _BOHR_PER[src] / _BOHR_PER[dst]
    if src in _PER_HARTREE and dst in _PER_HARTREE:
        return value / _PER_HARTREE[src] * _PER_HARTREE[dst]
    if src == "nm" and dst in _PER_HARTREE:
        return convert(EV_NM / value, "ev", dst)
    if dst == "nm" and src in _PER_HARTREE:
        return EV_NM / convert(value, src, "ev")
    raise ValueError(
        f"cannot convert {from_unit!r} to {to_unit!r}: convert() handles "
        f"angstrom and bohr, and the energies hartree, ev, kcal_per_mol, "
        f"kj_per_mol, cm-1 and nm (a photon wavelength)")


def _check_declared(units: Mapping[str, Any], what: str,
                    defname: str | None = None) -> dict[str, str]:
    """A ``units`` declaration as a writer emits it (spec § 4.3, "Declared
    units"): every value is a unit name, and a key whose unit the schema
    fixes for ``defname`` names that unit. Raises ``ValueError`` otherwise."""
    fixed = fixed_units(defname) if defname else {}
    out: dict[str, str] = {}
    for key, name in units.items():
        if not is_unit(name):
            raise ValueError(f"{what}: declared unit {name!r} for {key!r} is "
                             f"not a QVF unit name (spec § 4.3)")
        want = fixed.get(key)
        if want is not None and name != want:
            raise ValueError(f"{what}: units[{key!r}] must be {want!r}; spec "
                             f"§ 4.3 fixes that unit and a declaration only "
                             f"restates it (got {name!r})")
        out[str(key)] = name
    return out
