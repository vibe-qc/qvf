"""Calculate H2 with PySCF, export QVF and verify the installed reader.

Usage: python pyscf_to_qvf.py [h2.qvf]
Requires qvf-writer[pyscf,validate]. Refuses to overwrite an existing file.
"""
from pathlib import Path
import sys

import jsonschema  # Require full structural validation, not only semantic checks.
import numpy as np
from pyscf import gto, lib, scf
from qvf import Reader, __version__, validate_qvf
from qvf.adapters.pyscf import write_scf


def main():
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "h2.qvf")
    lib.num_threads(1)
    mol = gto.M(atom="H 0 0 0; H 0 0 0.74", unit="Angstrom",
                basis="sto-3g", verbose=0)
    mf = scf.RHF(mol).run(conv_tol=1e-10)
    if not mf.converged:
        raise RuntimeError("SCF did not converge; no archive written")
    # Exclusive creation also protects an existing output against accidental reruns.
    with target.open("xb") as output:
        ids = write_scf(mf, output)
    report = validate_qvf(target)
    if not report["ok"] or report["findings"]:
        raise RuntimeError(report)
    with Reader(target) as reader:
        sid = ids["wavefunction"]
        coefficients = reader.get(sid).coefficients().numpy()
        overlap = reader.tensor(sid, "overlap").numpy()
        error = float(np.max(np.abs(
            coefficients @ overlap @ coefficients.T - np.eye(mol.nao_nr()))))
        stored_energy = reader.raw_manifest["provenance"]["scf_energy"]["value"]
        np.testing.assert_allclose(stored_energy, mf.e_tot, rtol=0, atol=1e-12)
        np.testing.assert_allclose(coefficients @ overlap @ coefficients.T,
                                   np.eye(mol.nao_nr()), rtol=0, atol=1e-10)
    print(f"qvf-writer {__version__}")
    print(f"RHF/STO-3G total energy: {mf.e_tot:.10f} hartree")
    print(f"MO coefficient shape: {coefficients.shape} (orbitals, AOs)")
    print(f"Maximum orbital orthonormality error: {error:.3e}")
    print(f"Validation: PASS (zero findings); wrote {target.name}")


if __name__ == "__main__":
    main()
