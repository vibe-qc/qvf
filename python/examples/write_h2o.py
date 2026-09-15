#!/usr/bin/env python3
"""Write a QVF archive for a (fictional) H2O / RHF / STO-3G calculation.

Run:  python write_h2o.py [out.qvf]
Then: python ../qvf_reader.py out.qvf

Demonstrates the ORCA-relevant sections: structure, wavefunction.gto (the
GBW-equivalent basis + MO coefficients), an IR spectrum, atom properties, an SCF
trace, provenance, and citations. The numbers are illustrative, not a real SCF.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qvf_writer import QvfWriter  # noqa: E402


def main(out: str = "h2o.qvf") -> None:
    w = QvfWriter(program="my-code", version="1.0.0", calculation="h2o/rhf/sto-3g")

    # --- geometry (Å) ---------------------------------------------------
    atoms = [
        {"symbol": "O", "position": [0.000000, 0.000000, 0.117300], "atomic_number": 8},
        {"symbol": "H", "position": [0.000000, 0.757200, -0.469200], "atomic_number": 1},
        {"symbol": "H", "position": [0.000000, -0.757200, -0.469200], "atomic_number": 1},
    ]
    w.add_structure(atoms)
    w.add_bonds([{"i": 0, "j": 1, "order": 1.0}, {"i": 0, "j": 2, "order": 1.0}])

    # --- wavefunction.gto (STO-3G shells; illustrative) -----------------
    # These are the raw published .g94 STO-3G values, which already apply to
    # N_i-normalized primitives exactly as spec Appendix A.1 requires -- so
    # no divide is needed and the flag stays False. Set
    # coeffs_are_libint_normalized=True only for engine-native coefficients
    # stored pre-multiplied by N_i (libint / libcint / GBW-style storage).
    # O: 1s, 2s, 2p; H: 1s.
    shells = [
        {"center": 0, "l": 0, "exponents": [130.70932, 23.808861, 6.4436083],
         "coefficients": [0.15432897, 0.53532814, 0.44463454]},
        {"center": 0, "l": 0, "exponents": [5.0331513, 1.1695961, 0.3803890],
         "coefficients": [-0.09996723, 0.39951283, 0.70011547]},
        {"center": 0, "l": 1, "exponents": [5.0331513, 1.1695961, 0.3803890],
         "coefficients": [0.15591627, 0.60768372, 0.39195739]},
        {"center": 1, "l": 0, "exponents": [3.4252509, 0.6239137, 0.1688554],
         "coefficients": [0.15432897, 0.53532814, 0.44463454]},
        {"center": 2, "l": 0, "exponents": [3.4252509, 0.6239137, 0.1688554],
         "coefficients": [0.15432897, 0.53532814, 0.44463454]},
    ]
    # n_ao = 1 + 1 + 3 + 1 + 1 = 7 (spherical p contributes 3)
    n_ao = 7
    rng = np.random.default_rng(0)
    C = rng.standard_normal((n_ao, n_ao))  # illustrative MO coefficients
    energies = [-20.24, -1.27, -0.62, -0.45, -0.39, 0.60, 0.74]
    occ = [2, 2, 2, 2, 2, 0, 0]
    w.add_wavefunction_gto(shells, mo_coefficients=C, energies=energies,
                           occupations=occ, coeffs_are_libint_normalized=False)

    # --- IR spectrum ----------------------------------------------------
    w.add_spectrum("spectra.ir", frequencies=[1595.0, 3657.0, 3756.0],
                   intensities=[67.0, 5.0, 42.0], label="IR (harmonic)")

    # --- atom properties ------------------------------------------------
    w.add_atom_properties(mulliken_charge=[-0.68, 0.34, 0.34],
                          loewdin_charge=[-0.41, 0.205, 0.205])

    # --- SCF trace ------------------------------------------------------
    w.add_scf_history([
        {"iter": 1, "energy_eh": -74.90, "delta_e": 1.0, "diis_error": 1e-1},
        {"iter": 2, "energy_eh": -74.962, "delta_e": -6.2e-2, "diis_error": 1e-3},
        {"iter": 3, "energy_eh": -74.9630, "delta_e": -1.0e-3, "diis_error": 1e-6},
    ])

    # --- provenance + citations ----------------------------------------
    w.set_provenance(method="RHF", basis="STO-3G", charge=0, multiplicity=1,
                     n_electrons=10, scf_converged=True, n_scf_iterations=3,
                     scf_energy_eh=-74.9630)
    w.set_dipole_moment(total_debye=1.86, vector_debye=[0.0, 0.0, 1.86],
                        origin="center_of_mass")
    w.add_citations("@article{example2026,\n  title = {A calculation},\n"
                    "  author = {Anon},\n  year = {2026}\n}\n")

    path = w.write(out)
    print(f"wrote {path} with {len(w.build_manifest()['sections'])} sections")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "h2o.qvf")
