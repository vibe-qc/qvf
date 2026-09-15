/* write_h2o_c.c — a pure-C driver of the QVF writer via the extern "C" ABI.
 *
 * Demonstrates how a C (or Fortran-via-ISO_C_BINDING) code emits a .qvf without
 * touching C++. Build via the toolkit CMake; run:  ./write_h2o_c [out.qvf]
 * then validate:  python ../python/qvf_reader.py out.qvf
 */
#include <stdio.h>
#include <stdlib.h>

#include "qvf/qvf_c.h"

int main(int argc, char** argv) {
    const char* out = argc > 1 ? argv[1] : "h2o_c.qvf";

    qvf_writer* w = qvf_create("my-code", "1.0.0", "h2o/rhf/sto-3g");
    if (!w) {
        fprintf(stderr, "qvf_create failed\n");
        return 1;
    }

    /* structure (Angstrom) */
    const char* symbols[3] = {"O", "H", "H"};
    int Z[3] = {8, 1, 1};
    double pos[9] = {0.0, 0.0,  0.1173,
                     0.0, 0.7572, -0.4692,
                     0.0, -0.7572, -0.4692};
    qvf_add_structure(w, symbols, Z, pos, 3);

    /* a minimal wavefunction (one s shell; coeffs on unit-normalized primitive) */
    int   shell_center[1] = {0};
    int   shell_l[1]      = {0};
    int   shell_nprim[1]  = {1};
    double exponents[1]   = {1.0};
    double coeffs[1]      = {1.0};
    double mo[1]          = {1.0};
    double energies[1]    = {-0.5};
    double occ[1]         = {2.0};
    qvf_add_wavefunction_gto(w, 1, shell_center, shell_l, shell_nprim,
                             exponents, coeffs, /*pure=*/1,
                             /*coeffs_are_libint_normalized=*/0,
                             /*n_mo=*/1, /*n_ao=*/1, mo, energies, occ);

    /* IR spectrum */
    double freq[3] = {1595.0, 3657.0, 3756.0};
    double inten[3] = {67.0, 5.0, 42.0};
    qvf_add_spectrum_xy(w, "spectra.ir", freq, inten, 3);

    /* Mulliken charges */
    double mulliken[3] = {-0.68, 0.34, 0.34};
    qvf_add_atom_properties(w, mulliken, NULL, NULL, 3);

    /* object-shaped EPR spectrum via a JSON string */
    qvf_add_spectrum_json(
        w, "spectra.epr",
        "{\"g_tensor\":{\"principal\":[2.0023,2.0021,2.0089],\"isotropic\":2.0044}}");

    /* provenance (root) via a JSON string */
    qvf_set_provenance_json(
        w, "{\"method\":\"RHF\",\"basis\":\"STO-3G\",\"scf_converged\":true}");

    qvf_add_citations(w, "@article{ex,title={T},author={A},year={2026}}");

    if (qvf_write(w, out) != 0) {
        fprintf(stderr, "qvf_write failed: %s\n", qvf_last_error(w));
        qvf_destroy(w);
        return 1;
    }
    printf("wrote %s\n", out);
    qvf_destroy(w);
    return 0;
}
