/* qvf_c.h — C ABI for the QVF writer library.
 *
 * A thin, stable extern "C" wrapper over qvf::QvfWriter so that C, Fortran (via
 * ISO_C_BINDING), Rust, Julia, and other languages can emit .qvf archives
 * without a C++ interface. All state lives in one opaque handle.
 *
 * Complex/nested payloads (provenance, NMR/EPR spectra, vendor sections) are
 * passed as JSON strings the caller builds; the library emits them verbatim, so
 * no JSON parser crosses the boundary. Numeric/array data is passed as plain
 * pointers.
 *
 * Return convention: functions return 0 on success, non-zero on error; call
 * qvf_last_error() for a message. Positions are Ångström, wavefunction
 * exponents bohr^-2, energies Hartree — see the QVF spec for all units.
 *
 * License: Apache-2.0.
 */
#ifndef QVF_C_H
#define QVF_C_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct qvf_writer qvf_writer; /* opaque handle */

/* Create / destroy. Returns NULL on allocation failure. */
qvf_writer* qvf_create(const char* program, const char* version,
                       const char* calculation);
void qvf_destroy(qvf_writer* w);

/* Last error message for `w` (empty string if none). Valid until the next call
 * on `w`. */
const char* qvf_last_error(qvf_writer* w);

/* --- structure -----------------------------------------------------------
 * symbols: array of n_atoms C strings (may be NULL to derive from Z).
 * atomic_numbers: array of n_atoms ints (may be NULL to derive from symbols).
 * positions: n_atoms*3 doubles, row-major (x,y,z per atom), Ångström.
 */
int qvf_add_structure(qvf_writer* w, const char* const* symbols,
                      const int* atomic_numbers, const double* positions,
                      int n_atoms);

/* --- wavefunction.gto (restricted) ---------------------------------------
 * Shells are given as parallel arrays of length n_shells; the per-shell
 * exponent/coefficient runs are concatenated into exponents_flat/coeffs_flat
 * (total length = sum of shell_nprim). mo_coeffs is [n_mo * n_ao] row-major
 * (rows are MOs). energies/occupations are length n_mo (may be NULL).
 * If coeffs_are_libint_normalized != 0, coefficients are divided by the
 * primitive norm on write (see the spec, Appendix A). pure != 0 = spherical.
 */
int qvf_add_wavefunction_gto(
    qvf_writer* w, int n_shells, const int* shell_center, const int* shell_l,
    const int* shell_nprim, const double* exponents_flat,
    const double* coeffs_flat, int pure, int coeffs_are_libint_normalized,
    int n_mo, int n_ao, const double* mo_coeffs, const double* energies,
    const double* occupations);

/* --- spectra -------------------------------------------------------------
 * Simple frequency/intensity kinds (spectra.ir/raman/uvvis/ecd/vcd/generic). */
int qvf_add_spectrum_xy(qvf_writer* w, const char* kind, const double* freqs,
                        const double* intensities, int n);
/* Object-shaped spectra (spectra.nmr / spectra.epr): payload is a JSON object
 * string emitted as the `spectrum` member verbatim. */
int qvf_add_spectrum_json(qvf_writer* w, const char* kind,
                          const char* spectrum_json);

/* --- analysis / provenance ----------------------------------------------- */
/* Any of the three arrays may be NULL; each present one is length n_atoms. */
int qvf_add_atom_properties(qvf_writer* w, const double* mulliken,
                            const double* loewdin, const double* spin_population,
                            int n_atoms);
/* iterations_json is a JSON array string of iteration records. */
int qvf_add_scf_history_json(qvf_writer* w, const char* iterations_json);
int qvf_add_citations(qvf_writer* w, const char* bibtex);
/* Self-contained record of one program invocation (kind run.record).
 * program is required; at least one of input_text / log_text must be
 * non-NULL/non-empty (both UTF-8). Optional strings may be NULL. Pass
 * exit_status via has_exit_status != 0; sequence < 0 omits it. */
int qvf_add_run_record(qvf_writer* w, const char* program,
                       const char* input_text, const char* log_text,
                       const char* program_version, const char* command,
                       int has_exit_status, int exit_status,
                       const char* started_utc, const char* finished_utc,
                       int sequence);
/* Declarative job specification (kind job.spec, spec 5.9). job_type is
 * required: "molecular" or "periodic". Optional strings may be NULL. Pass
 * charge via has_charge != 0; multiplicity < 1 omits it; kpoints is NULL or
 * int[3] (each >= 1). tasks_json is NULL or a JSON array string of task
 * identifiers; options_json is NULL or a JSON object string of extra engine
 * keywords (both emitted verbatim). */
int qvf_add_job_spec(qvf_writer* w, const char* job_type,
                     const char* method, const char* basis,
                     const char* functional,
                     int has_charge, int charge, int multiplicity,
                     const int* kpoints,
                     const char* tasks_json, const char* options_json);
/* provenance_json is a JSON object string merged at the manifest root. */
int qvf_set_provenance_json(qvf_writer* w, const char* provenance_json);

/* --- vendor escape hatch (x_<vendor>.*) ----------------------------------
 * Adds a single JSON member `role` carrying `payload_json` (emitted verbatim).
 * critical != 0 sets the section's critical flag (declare the namespace via
 * qvf_set_extensions_json). One member per call. */
int qvf_add_vendor_section(qvf_writer* w, const char* kind, const char* role,
                           const char* payload_json, int critical);
int qvf_set_extensions_json(qvf_writer* w, const char* extensions_json);

/* --- output --------------------------------------------------------------
 * Writes {path} (".qvf" appended if missing). Returns 0 on success. */
int qvf_write(qvf_writer* w, const char* path);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* QVF_C_H */
