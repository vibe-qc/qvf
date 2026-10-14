/* qvf_c.h — C ABI for the QVF writer library.
 *
 * A thin, stable extern "C" wrapper over qvf::QvfWriter so that C, Fortran (via
 * ISO_C_BINDING), Rust, Julia, and other languages can emit .qvf archives
 * without a C++ interface. All state lives in one opaque handle.
 *
 * Complex/nested payloads (provenance, NMR/EPR spectra, vendor sections) are
 * passed as JSON strings the caller builds; the library emits them verbatim
 * (provenance is checked first, see qvf_set_provenance_json), so no JSON
 * parser crosses the boundary. Numeric/array data is passed as plain pointers.
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
#include <stdint.h>

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

/* --- wavefunction.gto (unrestricted) -------------------------------------
 * The shells as for qvf_add_wavefunction_gto; separate alpha and beta sets:
 * mo_coeffs_alpha is [n_mo_alpha * n_ao] and mo_coeffs_beta [n_mo_beta * n_ao]
 * row-major (rows are MOs); each energies / occupations array (may be NULL)
 * has n_mo_alpha or n_mo_beta entries, occupations 0 to 1. Both this and
 * qvf_add_wavefunction_gto create the section "wf". */
int qvf_add_wavefunction_gto_unrestricted(
    qvf_writer* w, int n_shells, const int* shell_center, const int* shell_l,
    const int* shell_nprim, const double* exponents_flat,
    const double* coeffs_flat, int pure, int coeffs_are_libint_normalized,
    int n_ao, int n_mo_alpha, const double* mo_coeffs_alpha,
    const double* energies_alpha, const double* occupations_alpha,
    int n_mo_beta, const double* mo_coeffs_beta, const double* energies_beta,
    const double* occupations_beta);

/* The AO overlap matrix of the already added wavefunction.gto section
 * `section_id` (NULL means "wf"): overlap is n_ao * n_ao doubles, row-major,
 * in the AO order of the section's basis, for the AOs as written (after any
 * N_i division). Producers SHOULD write it: validators compare its diagonal
 * with spec Appendix A.1 (E_NORMALIZATION). An n_ao other than the basis's, or
 * a section that already has an overlap member, is an error. */
int qvf_set_wavefunction_overlap(qvf_writer* w, const char* section_id, int n_ao,
                                 const double* overlap);

/* Effective core potentials of the already added wavefunction.gto section
 * `section_id` (NULL means "wf"), written as its basis payload's `ecp`,
 * replacing any earlier one. ecp_json is a JSON array string of
 * {"center", "n_core_electrons", "label"?, "projectors"?: [{"l", "exponents",
 * "coefficients", "powers", "local"?}]}: at most one entry per atom; each
 * projector a radial function sum_i c_i r^(n_i - 2) exp(-a_i r^2), at most one
 * of them local (local: true, the highest l of the centre). Invalid JSON or a
 * malformed entry is an error and changes nothing (QVF spec 5.3). */
int qvf_set_wavefunction_ecp_json(qvf_writer* w, const char* section_id,
                                  const char* ecp_json);

/* --- volumes (QVF spec 5.2) ----------------------------------------------
 * Any volume.* kind except volume.series. grid_json is a JSON object string:
 * "origin" (3 numbers, bohr) and "voxel_vectors" (3 x 3 numbers, bohr per
 * step) are required; "units" (object of unit names), "periodic" (3
 * booleans), "includes_endpoint" (boolean) and "structure_ref" (the id of an
 * added structure section) are optional; "shape", when given, must equal the
 * spatial extents of `shape`. Any other key is an error. dtype is "float32"
 * (also for NULL or "") or "float64", and `data` points to prod(shape) values
 * of that C type (float or double), row-major, in host byte order; the
 * library writes them little-endian. rank and shape are those of the data:
 * rank 3 [nx, ny, nz] for the scalar kinds, rank 4 [nx, ny, nz, 3] for
 * volume.vector and [nx, ny, nz, 2] for volume.complex (last axis [re, im]).
 * label may be NULL. */
int qvf_add_volume(qvf_writer* w, const char* kind, const char* grid_json,
                   const char* dtype, int rank, const int64_t* shape,
                   const void* data, const char* label);
/* volume.series: shape4 is [n, nx, ny, nz] (n slabs on one grid) and
 * axis_json the JSON object string of the `axis` member: "kind" ("time",
 * "frame", "state" or "custom"), "values" (n numbers), optional "units",
 * "labels" (n strings) and "trajectory_ref" (an added trajectory or
 * reaction.path section). grid_json, dtype, data and label as for
 * qvf_add_volume. */
int qvf_add_volume_series(qvf_writer* w, const char* grid_json,
                          const char* axis_json, const char* dtype,
                          const int64_t* shape4, const void* data,
                          const char* label);

/* --- wavefunction.bloch (QVF spec 5.3.1, provisional) ---------------------
 * k-resolved Bloch orbitals of a periodic system. The shell arrays, pure and
 * coeffs_are_libint_normalized are as for qvf_add_wavefunction_gto; n_ao must
 * equal the AO count of the shells. kpoints_frac: n_k * 3 doubles, the
 * k-points in fractional reciprocal-lattice coordinates. weights_or_null:
 * NULL or n_k non-negative doubles summing to 1 within 1e-6. n_spin: 1
 * (restricted) or 2 (unrestricted). coeffs_re_im: n_k*n_spin*n_mo*n_ao*2
 * doubles, row-major [n_k, n_spin, n_mo, n_ao, 2] with the last axis (real,
 * imaginary). energies (hartree) and occupations (electrons per orbital, not
 * weighted by k): n_k*n_spin*n_mo doubles each, [n_k, n_spin, n_mo]. The
 * basis names the structure section "structure", which must be periodic.
 * Section id "wf_bloch". */
int qvf_add_wavefunction_bloch(
    qvf_writer* w, int n_shells, const int* shell_center, const int* shell_l,
    const int* shell_nprim, const double* exponents_flat,
    const double* coeffs_flat, int pure, int coeffs_are_libint_normalized,
    int n_k, const double* kpoints_frac, const double* weights_or_null,
    int n_spin, int n_mo, int n_ao, const double* coeffs_re_im,
    const double* energies, const double* occupations);

/* --- spectra -------------------------------------------------------------
 * Simple frequency/intensity kinds (spectra.ir/raman/uvvis/ecd/vcd/generic). */
int qvf_add_spectrum_xy(qvf_writer* w, const char* kind, const double* freqs,
                        const double* intensities, int n);
/* Object-shaped spectra (spectra.nmr / spectra.epr): payload is a JSON object
 * string emitted as the `spectrum` member verbatim. */
int qvf_add_spectrum_json(qvf_writer* w, const char* kind,
                          const char* spectrum_json);

/* --- analysis / provenance ----------------------------------------------- */
/* atom_properties (QVF spec 5.7). The scalar roles, each n_atoms doubles:
 * "mulliken_charge", "loewdin_charge", "hirshfeld_charge", "iao_charge"
 * (intrinsic atomic orbital charges), "spin_population", "cm5_charge",
 * "chelpg_charge", "resp_charge", "esp_charge", "nbo_charge", "mbis_charge",
 * "bader_charge", "ddec_charge", "valence", "bonded_valence", "fukui_plus",
 * "fukui_minus", "fukui_zero", "dual_descriptor", "atomic_energy_eh",
 * "atomic_volume_bohr3" and "nmr_shielding_iso_ppm". The vector roles, each
 * n_atoms * 3 doubles (x, y, z per atom, row-major): "magnetic_moment" and
 * "force_eh_bohr" (the energy gradient in hartree/bohr, not the force).
 * "custom.<name>" (<name> in [A-Za-z0-9_]+) is a scalar or vector role of your
 * own once qvf_set_atom_properties_meta_json has described it. All roles of
 * the section have the same n_atoms.
 *
 * Mulliken, Loewdin and spin populations in one call: any of the three arrays
 * may be NULL, at least one must be given, and each present one is length
 * n_atoms. Creates the atom_properties section. */
int qvf_add_atom_properties(qvf_writer* w, const double* mulliken,
                            const double* loewdin, const double* spin_population,
                            int n_atoms);
/* Any one scalar role: appends `role` (n_atoms > 0 values) to the
 * atom_properties section, creating the section on the first call, so it also
 * adds to a section made by qvf_add_atom_properties. An unknown role, a vector
 * role, a custom role without a "scalar" meta entry, a role the section
 * already has, or an n_atoms that differs from its other roles is an error. */
int qvf_add_atom_property(qvf_writer* w, const char* role,
                          const double* values, int n_atoms);
/* The same for a vector role: `values_n_atoms_x3` holds n_atoms * 3 doubles,
 * (x, y, z) per atom, row-major, written as float64 [n_atoms, 3]. Accepts
 * "magnetic_moment", "force_eh_bohr" and a custom role whose meta entry has
 * kind "vector". Errors as for qvf_add_atom_property. */
int qvf_add_atom_vector_property(qvf_writer* w, const char* role,
                                 const double* values_n_atoms_x3, int n_atoms);
/* Describe custom roles: `meta_json` is a JSON object mapping "custom.<name>"
 * to {"units": "...", "description": "...", "kind": "scalar" | "vector"}.
 * Call it before adding the roles it describes; repeated calls merge, and a
 * repeated role replaces its entry. The writer emits the section's `meta`
 * member from the entries of the custom roles the section carries. Invalid
 * JSON or a malformed entry is an error and changes nothing. */
int qvf_set_atom_properties_meta_json(qvf_writer* w, const char* meta_json);
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
 * keywords (both emitted verbatim). The newer fields of the payload
 * (structure_ref, solvation, dispersion, relativistic, scf, geometry,
 * resources) have no argument here: use qvf_add_job_spec_json. */
int qvf_add_job_spec(qvf_writer* w, const char* job_type,
                     const char* method, const char* basis,
                     const char* functional,
                     int has_charge, int charge, int multiplicity,
                     const int* kpoints,
                     const char* tasks_json, const char* options_json);
/* The same section from the whole payload: spec_json is the JobSpecPayload as
 * a JSON object string (QVF spec 5.9), e.g.
 *   {"job_type": "periodic", "method": "rks", "structure_ref": "structure",
 *    "dispersion": "d3bj", "scf": {"convergence": 1e-8, "max_iterations": 100},
 *    "resources": {"n_cores": 16, "walltime_s": 86400}}
 * It is parsed (malformed JSON, a non-object, a job_type other than
 * "molecular" or "periodic", or a wrong typed field is an error and adds
 * nothing) and written with the section id "job_spec". resources are hints. */
int qvf_add_job_spec_json(qvf_writer* w, const char* spec_json);
/* provenance_json is a JSON object string merged at the manifest root. The
 * string is parsed (malformed JSON or a non-object is an error) and a
 * top-level "hostname" key is dropped: that field is deprecated (QVF spec
 * 3.2). The typed fields are checked, and a wrong one is an error: "software"
 * (an array of {"name", "version", "url"} objects, "name" non-empty),
 * "git_commit" (7 to 64 hexadecimal characters), "n_threads" and
 * "n_mpi_ranks" (integers >= 1), "n_gpus" (an integer >= 0) and
 * "started_utc" / "finished_utc" (UTC strings YYYY-MM-DDThh:mm:ssZ). Without
 * a hostname key the string is emitted verbatim. */
int qvf_set_provenance_json(qvf_writer* w, const char* provenance_json);
/* Root energies block (QVF spec 3.6): energies_json is a JSON object string,
 * e.g. {"total": {"value": -76.02, "units": "hartree"}, "method": "rhf"},
 * emitted verbatim. An energy stated for the method provenance.method names
 * must agree with provenance.scf_energy within 1e-8 hartree. */
int qvf_set_energies_json(qvf_writer* w, const char* energies_json);

/* --- energy derivatives (QVF spec 5.10, 5.11) ----------------------------
 * forces: gradient is n_atoms*3 doubles, row-major, the energy GRADIENT dE/dR
 * in hartree/bohr (the forces are its negative), in the atom order of the
 * structure. stress_or_null is NULL or 9 doubles, the row-major [3, 3] stress
 * tensor (1/V) dE/d(strain) in hartree/bohr^3 of a periodic system. */
int qvf_add_forces(qvf_writer* w, int n_atoms, const double* gradient,
                   const double* stress_or_null);
/* hessian: matrix is (3*n_atoms)^2 doubles, the row-major [3N, 3N] Cartesian
 * Hessian in hartree/bohr^2, index 3*atom + xyz (x, y, z). */
int qvf_add_hessian(qvf_writer* w, int n_atoms, const double* matrix);

/* --- excited states (QVF spec 5.12) ---------------------------------------
 * states_json is a JSON array string of state objects in ascending order of
 * "index" (integer >= 1, unique), each with "excitation_energy" ({value,
 * units} or a number in eV) and optionally "total_energy" ({value, units} or
 * a number in hartree), "multiplicity", "symmetry", "oscillator_strength",
 * "rotatory_strength_cgs" (1e-40 esu^2 cm^2), "transition_dipole" and
 * "transition_magnetic_dipole" (3 numbers, atomic units), "contributions"
 * ([{"from_mo", "to_mo", "spin"?, "weight"}]), "nto_ref" and "density_ref"
 * (ids of sections added before). meta_json is NULL or a JSON object string
 * (method, reference_state, n_states, tda, spin_flip, units).
 * wavefunction_ref is NULL or the id of the added wavefunction.gto of the
 * reference state, whose orbital rows the contributions must index. The
 * section id is "excited_states". Malformed JSON or a rule broken is an
 * error and writes nothing. */
int qvf_add_excited_states_json(qvf_writer* w, const char* states_json,
                                const char* meta_json,
                                const char* wavefunction_ref);

/* --- trajectory (QVF spec 5.5) -------------------------------------------
 * metadata_json is a JSON object string, the trajectory metadata: the atoms
 * ("symbols", "atomic_numbers" or "atoms") and optionally "energies", "kind"
 * ("md", "optimization", ...), "pbc", "ensemble", "timestep_fs" and "units".
 * coords_f64 is n_frames * n_atoms * 3 doubles, row-major (frame, atom,
 * x/y/z), in Angstrom; when the metadata sets "precision": "float32" they are
 * stored as float32 (long MD runs). lattice_rows_or_null is NULL or the cell
 * in the STRUCTURE convention, rows in Angstrom (row i is the lattice vector
 * of axis i), NOT the columns in bohr of a reaction path: 9 doubles, one
 * fixed [3, 3] cell, when lattice_per_frame is 0, or 9 * n_frames doubles,
 * [n_frames, 3, 3], otherwise; the metadata must then carry "pbc", and a
 * true "pbc" entry needs the lattice. velocities_or_null (Angstrom/fs) and
 * gradient_or_null (the energy gradient dE/dR in hartree/bohr; the forces
 * are its negative) are NULL or n_frames * n_atoms * 3 doubles; times_or_null
 * (fs) and energies_or_null (hartree; equal to the metadata "energies" within
 * 1e-10 when both are given) are NULL or n_frames doubles. The section id is
 * "trajectory". Every check runs before anything is written. */
int qvf_add_trajectory(qvf_writer* w, const char* metadata_json, int n_frames,
                       int n_atoms, const double* coords_f64,
                       const double* lattice_rows_or_null, int lattice_per_frame,
                       const double* velocities_or_null,
                       const double* gradient_or_null, const double* times_or_null,
                       const double* energies_or_null);

/* --- property kinds (QVF spec 5.13) --------------------------------------
 * Each call adds one section whose single JSON member `properties` is the
 * object string `properties_json`, written verbatim after it has been parsed
 * and checked: an unknown key (keys beginning "x_" are allowed), a block or
 * matrix of the wrong shape, a missing required field, a value outside an
 * enumeration, a symmetry or sum rule of the payload, or a `units` declaration
 * that is not a unit name or contradicts the fixed unit is an error, and
 * nothing is written. Units are fixed and nothing is converted.
 *
 * qvf_add_electric_properties_json (kind properties.electric): at least one of
 *   "dipole" {"vector": [x, y, z], "total", "units": "debye"} (debye),
 *   "quadrupole" {"matrix": 3x3, "traceless": bool, "convention":
 *   "buckingham" | "cartesian"} (debye-angstrom), "octupole" {"tensor": 27
 *   numbers, row-major [3, 3, 3]} (debye-angstrom^2), "polarizability"
 *   {"matrix": 3x3, "frequency_ev", "isotropic"} and "hyperpolarizability"
 *   {"tensor": 27 numbers, "frequencies_ev": [w1, w2]} (atomic units); also
 *   "origin" and "units". A dipole that the root dipole_moment also states
 *   must agree with it within 1e-6 debye.
 * qvf_add_elastic_properties_json (kind properties.elastic): "stiffness" (6x6,
 *   Voigt order xx yy zz yz xz xy, GPa, symmetric) is required; "compliance"
 *   (6x6, 1/GPa), "bulk_modulus_gpa", "shear_modulus_gpa",
 *   "youngs_modulus_gpa", "poisson_ratio", "average" ("voigt" | "reuss" |
 *   "hill") and "units" are optional.
 * qvf_add_dielectric_properties_json (kind properties.dielectric):
 *   "electronic" (3x3) is required; "ionic", "static" (3x3, static = electronic
 *   + ionic within 1e-6), "born_charges" (array of 3x3, one per atom, in e),
 *   "piezoelectric" (3x6, C/m^2) and "units" are optional. */
int qvf_add_electric_properties_json(qvf_writer* w, const char* properties_json);
int qvf_add_elastic_properties_json(qvf_writer* w, const char* properties_json);
int qvf_add_dielectric_properties_json(qvf_writer* w, const char* properties_json);

/* metadata_json is a JSON object string: the root `metadata` block (QVF spec
 * 3.5), replacing any earlier one. Malformed JSON or a non-object is an error.
 * The writer adds `created_utc` (now, UTC) and a random `uuid` when the object
 * lacks them, as it does for an archive with no metadata block at all. */
int qvf_set_metadata_json(qvf_writer* w, const char* metadata_json);

/* --- section references and grouping (QVF spec 4.1) ----------------------
 * Annotates the already added section `id`: structure_ref names the
 * `structure` section it describes, run_ref the `run.record` section of the
 * run that produced it, and group is a free display label. NULL (or an empty
 * string) leaves that field unset. A reference that names no section, or a
 * section of the wrong kind, is an error and sets nothing. */
int qvf_annotate_section(qvf_writer* w, const char* id,
                         const char* structure_ref, const char* run_ref,
                         const char* group);

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
