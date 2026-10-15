// qvf/units.hpp — the QVF unit vocabulary and the length and energy
// conversions. Header-only; part of the zero-dependency QVF library.
//
// QVF names every declared unit with a unit name from a controlled
// vocabulary (spec § 4.3, "Unit names"); the JSON Schema lists the names as
// $defs/UnitName. The Unit enum, unit_name() and parse_unit() are generated
// from the schema into qvf/kinds_generated.hpp (scripts/gen_kinds.py) and
// re-exported here; this header adds the legacy spellings and the
// conversions. Writers declare units and never convert; convert() is for code
// that reads a declared unit and needs another. License: Apache-2.0.
#ifndef QVF_UNITS_HPP
#define QVF_UNITS_HPP

#include <cstddef>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>

#include "qvf/kinds_generated.hpp"

namespace qvf {

// The unit names of QVF spec § 4.3, in vocabulary (schema) order:
// Unit::Angstrom ("angstrom"), Unit::ElectronVolt ("ev"), Unit::Wavenumber
// ("cm-1"), ... (see qvf/kinds_generated.hpp).
using gen::Unit;
using gen::kUnitCount;
// The unit name of `u`, e.g. "cm-1" for Unit::Wavenumber.
using gen::unit_name;
// The unit `name` names, or std::nullopt when it is not a unit name. Names
// are case-sensitive, and a legacy spelling ("eV") is not a unit name.
using gen::parse_unit;

// Like parse_unit(), but also maps the legacy spellings "Eh", "Hartree"
// (Unit::Hartree) and "eV" (Unit::ElectronVolt), which the units of a
// {value, units} object may still carry ($defs/LegacyUnitName).
inline std::optional<Unit> canonical_unit(std::string_view name) {
    if (std::optional<Unit> u = parse_unit(name)) return u;
    for (const auto& legacy : gen::kLegacyUnitSpellings)
        if (legacy.spelling == name) return legacy.unit;
    return std::nullopt;
}

// --- conversions ------------------------------------------------------------
// CODATA 2018 recommended values. The SI defining constants h, c, e and N_A
// are exact since 2019, so the factors below that follow from them alone are
// exact up to the printed digits.

// Bohr per Ångström: the reciprocal of CODATA 2018's bohr radius,
// 1 bohr = 0.529177210903 Å (1 / 0.529177210903 = 1.88972612462577...), rounded
// to ten decimals. The QVF spec (§ 4.3, "Lattice conventions") uses this value.
inline constexpr double kBohrPerAngstrom = 1.8897261246;
// Hartree energy in eV: E_h = 27.211386245988 eV (CODATA 2018).
inline constexpr double kHartreeInEv = 27.211386245988;
// E_h N_A in kJ/mol: 4.3597447222071e-18 J (CODATA 2018) x 6.02214076e23 /mol.
inline constexpr double kHartreeInKjPerMol = 2625.4996394799;
// The thermochemical calorie: 1 kcal = 4.184 kJ (exact).
inline constexpr double kKjPerKcal = 4.184;
// E_h N_A in kcal/mol, 627.5094740631.
inline constexpr double kHartreeInKcalPerMol = kHartreeInKjPerMol / kKjPerKcal;
// E_h / (h c) in cm^-1: 2.1947463136320e7 /m (CODATA 2018).
inline constexpr double kHartreeInWavenumber = 219474.6313632;
// h c / e in eV nm (exact constants): E[eV] = 1239.841984332 / lambda[nm].
inline constexpr double kEvNanometer = 1239.841984332;

namespace detail {
// Bohr per unit for the lengths; 0 for any other unit.
constexpr double bohr_per(Unit u) {
    return u == Unit::Bohr ? 1.0 : u == Unit::Angstrom ? kBohrPerAngstrom : 0.0;
}
// Units per hartree for the energies (cm^-1 through E = h c nu~); 0 otherwise.
constexpr double per_hartree(Unit u) {
    switch (u) {
        case Unit::Hartree: return 1.0;
        case Unit::ElectronVolt: return kHartreeInEv;
        case Unit::KjPerMol: return kHartreeInKjPerMol;
        case Unit::KcalPerMol: return kHartreeInKcalPerMol;
        case Unit::Wavenumber: return kHartreeInWavenumber;
        default: return 0.0;
    }
}
}  // namespace detail

// True when convert() handles the pair: a unit to itself, angstrom <-> bohr,
// and the energies hartree, ev, kcal_per_mol, kj_per_mol, cm-1 among
// themselves and with nm (a photon wavelength, E = h c / lambda).
constexpr bool can_convert(Unit from, Unit to) {
    if (from == to) return true;
    if (detail::bohr_per(from) != 0.0 && detail::bohr_per(to) != 0.0) return true;
    const bool from_energy = detail::per_hartree(from) != 0.0;
    const bool to_energy = detail::per_hartree(to) != 0.0;
    return (from_energy || from == Unit::Nanometer) &&
           (to_energy || to == Unit::Nanometer);
}

// `value` in `from` converted to `to`; the same conversions as the Python
// qvf_units.convert(). Molar units are per mole of particles, so 1 hartree is
// 2625.4996394799 kJ/mol. Throws std::invalid_argument for a pair
// can_convert() rejects. A wavelength or energy of zero has no counterpart
// across the nm relation (the result is infinite).
inline double convert(double value, Unit from, Unit to) {
    if (!can_convert(from, to))
        throw std::invalid_argument("qvf::convert: cannot convert " +
                                    std::string(unit_name(from)) + " to " +
                                    std::string(unit_name(to)));
    if (from == to) return value;
    if (detail::bohr_per(from) != 0.0)
        return value * detail::bohr_per(from) / detail::bohr_per(to);
    if (from == Unit::Nanometer)
        return convert(kEvNanometer / value, Unit::ElectronVolt, to);
    if (to == Unit::Nanometer)
        return kEvNanometer / convert(value, from, Unit::ElectronVolt);
    return value / detail::per_hartree(from) * detail::per_hartree(to);
}

}  // namespace qvf

#endif  // QVF_UNITS_HPP
