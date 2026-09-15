// qvf/qvf.hpp — public API for the zero-dependency QVF writer library.
//
// QVF ("Quantum Visualization Format") is a ZIP container with a mandatory
// manifest.json plus typed JSON / binary members. This library lets any C++
// code emit conforming .qvf archives. It depends only on the C++17 standard
// library — ZIP, CRC-32, SHA-256 and JSON emission are all self-contained.
//
// See spec/qvf-format-spec.md for the format; docs/library_guide.md for usage.
// License: Apache-2.0.
#ifndef QVF_QVF_HPP
#define QVF_QVF_HPP

#include <array>
#include <cstdint>
#include <set>
#include <string>
#include <vector>

#include "qvf/json.hpp"

namespace qvf {

// ---------------------------------------------------------------------------
// Value types
// ---------------------------------------------------------------------------

struct Source {
    std::string program;
    std::string version;
    std::string calculation;
};

struct Atom {
    std::string symbol;
    int atomic_number = 0;
    std::array<double, 3> position{{0, 0, 0}};  // Ångström
};

struct Bond {
    int i = 0;
    int j = 0;
    double order = 1.0;
};

// Binary member dtypes permitted by the schema.
enum class DType {
    Int8, Int16, Int32, Int64, UInt8, UInt16, UInt32, UInt64, Float32, Float64
};

// A little-endian, C-contiguous binary payload. Build via the tensor_* helpers,
// which serialize host-endian-independently.
struct Tensor {
    DType dtype = DType::Float64;
    std::vector<int64_t> shape;
    std::vector<uint8_t> bytes;
};

Tensor tensor_f64(const std::vector<double>& v, std::vector<int64_t> shape);
Tensor tensor_f32(const std::vector<double>& v, std::vector<int64_t> shape);
Tensor tensor_i32(const std::vector<int32_t>& v, std::vector<int64_t> shape);
Tensor tensor_i64(const std::vector<int64_t>& v, std::vector<int64_t> shape);

// Row-major dense matrix of doubles (rows are MOs for wavefunction.gto).
struct Matrix {
    int64_t rows = 0;
    int64_t cols = 0;
    std::vector<double> data;  // size rows*cols, row-major
};

struct Shell {
    int center = 0;                     // 0-based atom index
    int l = 0;                          // shell angular momentum
    std::vector<double> exponents;      // bohr^-2
    std::vector<double> coefficients;   // on N_i-normalized primitives
                                        // (spec Appendix A.1)
    bool pure = true;                   // true = spherical, false = Cartesian
};

struct WavefunctionGTO {
    std::vector<Shell> shells;
    std::string structure_ref = "structure";
    std::string orbital_kind = "canonical";
    bool pure = true;

    // Restricted: fill mo_coefficients. Unrestricted: set unrestricted=true and
    // fill the alpha/beta matrices instead.
    bool unrestricted = false;
    Matrix mo_coefficients;                 // [n_mo, n_ao]
    std::vector<double> energies;           // Hartree
    std::vector<double> occupations;
    Matrix mo_coefficients_alpha;
    Matrix mo_coefficients_beta;
    std::vector<double> energies_alpha, occupations_alpha;
    std::vector<double> energies_beta, occupations_beta;

    // Optional Γ-point tag.
    bool has_kpoint = false;
    std::array<double, 3> kpoint{{0, 0, 0}};

    // Divide each coefficient by the primitive norm N_i before writing (set
    // this when your engine stores libint/libcint/GBW-style coefficients that
    // are pre-multiplied by N_i). See spec Appendix A.
    bool coeffs_are_libint_normalized = false;

    std::string section_id = "wf";
};

struct Spectrum {
    std::vector<double> frequencies;
    std::vector<double> intensities;
};

// A volumetric grid descriptor (bohr). shape is taken from the data tensor.
struct Grid {
    std::array<double, 3> origin{{0, 0, 0}};
    std::array<std::array<double, 3>, 3> voxel_vectors{{{{1, 0, 0}}, {{0, 1, 0}}, {{0, 0, 1}}}};
};

// One program invocation's self-contained record (kind run.record): the
// verbatim input handed to a quantum-chemistry code and/or the full
// log/output it produced. `program` names the code that ran — which may
// differ from the archive-level Source when the QVF is written by a
// converter. `input_text` / `log_text` are stored as opaque UTF-8 bytes;
// empty optional strings mean "omit the field".
struct RunRecord {
    std::string program;               // REQUIRED, e.g. "orca", "vibe-qc"
    std::string input_text;            // verbatim main input (UTF-8)
    std::string log_text;              // full log/output (UTF-8)
    std::string program_version;
    std::string command;               // launch command line, one string
    bool has_exit_status = false;
    int exit_status = 0;
    std::string started_utc;           // ISO 8601 UTC
    std::string finished_utc;
    int sequence = -1;                 // >= 0 to emit (multi-run ordering)
    Json files;                        // optional role -> {filename, ...} index
    // Auxiliary files: role suffix -> raw bytes, stored as attachment.<suffix>.
    std::vector<std::pair<std::string, std::vector<uint8_t>>> attachments;
};

// Normalization factor for the *axial* Cartesian Gaussian primitive of a
// shell. Depends only on l, not on (l_x, l_y, l_z), so for `pure: false`
// shells the primitives are not individually unit-normalized (<xy|xy> = 1/3
// for a d shell). Consumers must not add a per-component correction on top
// of it -- see spec Appendix A.1.
double primitive_norm(double alpha, int l);

// ---------------------------------------------------------------------------
// Writer
// ---------------------------------------------------------------------------

class QvfWriter {
public:
    explicit QvfWriter(Source source);

    // --- root metadata (each takes a qvf::Json object; see docs) ---
    void set_provenance(Json provenance);
    void set_thermochemistry(Json thermochemistry);
    void set_dipole_moment(Json dipole);
    void set_constraints(Json constraints);
    void set_extensions(Json extensions);
    void set_viewer_defaults(Json viewer_defaults);

    // --- structure & connectivity ---
    // `pbc` says which axes are periodic and needs no particular ordering; row i
    // of `lattice_vectors` pairs with pbc[i]. A row whose axis is aperiodic is
    // bookkeeping, not a cell edge (QVF spec § 5.1). Throws if pbc marks a
    // periodic axis with no lattice to span it.
    std::string add_structure(const std::vector<Atom>& atoms,
                              const std::array<bool, 3>& pbc = {{false, false, false}},
                              const std::vector<std::array<double, 3>>& lattice_vectors = {},
                              const std::vector<Bond>& bonds = {},
                              const std::string& section_id = "structure");
    std::string add_bonds(const std::vector<Bond>& pairs,
                          const std::string& section_id = "bonds");
    std::string add_bond_orders(const std::string& method,
                                const Json& pairs,
                                const std::string& section_id = "bond_orders");

    // --- wavefunction (GBW-equivalent) ---
    std::string add_wavefunction_gto(const WavefunctionGTO& wf);

    // --- spectra ---
    std::string add_spectrum(const std::string& kind, const Spectrum& spectrum,
                             const std::string& label = "",
                             const std::string& section_id = "");
    // NMR and other object-shaped spectra: pass the full JSON payload.
    std::string add_spectrum(const std::string& kind, const Json& payload,
                             const std::string& label = "",
                             const std::string& section_id = "");

    // --- analysis / provenance ---
    std::string add_atom_properties(const std::vector<double>& mulliken = {},
                                    const std::vector<double>& loewdin = {},
                                    const std::vector<double>& spin_population = {},
                                    const std::string& section_id = "atom_properties");
    std::string add_scf_history(const Json& iterations,
                                const std::string& section_id = "scf_history");
    std::string add_citations(const std::string& bibtex,
                              const std::string& section_id = "citations");
    // Self-contained record of one program invocation (input + log +
    // attachments). Requires record.program and at least one of
    // record.input_text / record.log_text.
    std::string add_run_record(const RunRecord& record,
                               const std::string& section_id = "run_record");
    // Declarative specification of the calculation the archive requests
    // (kind job.spec, spec § 5.9). `spec` is the JobSpecPayload JSON object;
    // it must carry job_type = "molecular" | "periodic". Pair with
    // set_provenance({... run_status: "pending" ...}) for an archive that
    // describes a job not yet run.
    std::string add_job_spec(const Json& spec,
                             const std::string& section_id = "job_spec");

    // --- vendor escape hatch (x_<vendor>.*) ---
    // json_members: object mapping role -> JSON payload.
    std::string add_vendor_section(const std::string& kind,
                                   const Json& json_members,
                                   bool critical = false,
                                   const std::string& schema_uri = "",
                                   const std::string& section_id = "");

    // --- volumes & basis AO (data is a 3-D Tensor; grid shape taken from it) ---
    // kind is one of volume.density/orbital/spin/elf/generic/potential/rdg.
    std::string add_volume(const std::string& kind, const Grid& grid,
                           const Tensor& data, const std::string& label = "",
                           const std::string& component = "",
                           const std::string& section_id = "");
    std::string add_volume_difference(const Grid& grid, const Tensor& data,
                                      const std::string& operand_a,
                                      const std::string& operand_b,
                                      const std::string& description = "",
                                      const std::string& label = "",
                                      const std::string& section_id = "diff");
    std::string add_basis_ao(const Json& ao_metadata, const Grid& grid,
                             const Tensor& data, const std::string& label = "",
                             const std::string& section_id = "");

    // --- bands & DOS ---
    std::string add_bands(const Json& kpath, const Tensor& eigenvalues,
                          const Tensor* projections = nullptr,
                          const std::string& section_id = "bands");
    // section_meta merges extra section-level peer fields (smearing, channels,
    // fermi_energy_ev, n_spin, ...) onto the section object per the schema.
    std::string add_dos_total(const Tensor& energies, const Tensor& dos,
                              const Json& section_meta = Json::object(),
                              const std::string& section_id = "dos_total");
    std::string add_dos_projected(const Tensor& energies, const Tensor& projections,
                                  const Json& section_meta = Json::object(),
                                  const std::string& section_id = "dos_projected");
    std::string add_dos_coop_cohp(const std::string& kind, const Tensor& energies,
                                  const Tensor& projections, const Tensor& integrated,
                                  const Json& meta,
                                  const std::string& section_id = "");

    // --- trajectories / reactions / scans / vibrations ---
    std::string add_trajectory(const Json& metadata, const Tensor& coords,
                               const std::string& section_id = "trajectory");
    // `lattice` (optional, may be nullptr) marks the path periodic: float64
    // [3,3] (fixed cell) or [n_frames,3,3] (variable cell), columns = a,b,c, in
    // bohr. Presence — not the manifest version — signals a periodic path.
    std::string add_reaction_path(const Json& metadata, const Tensor& coords,
                                  const Tensor* lattice = nullptr,
                                  const std::string& section_id = "reaction_path");
    std::string add_reaction_waypoints(const std::string& trajectory_ref,
                                       const Json& waypoints,
                                       const std::string& section_id = "reaction_waypoints");
    std::string add_scan_surface(const Json& metadata, const Tensor& axis_a,
                                 const Tensor& axis_b, const Tensor& energies,
                                 const Tensor* geometries = nullptr,
                                 const std::string& section_id = "scan_surface");
    std::string add_vibrations(const Json& metadata, const Tensor& displacements,
                               const std::string& section_id = "vibrations");

    // --- symmetry & periodic kinds ---
    std::string add_structure_symmetry(const Json& data,
                                       const std::string& section_id = "symmetry");
    std::string add_fermi_surface(const Json& mesh, const Tensor& energies,
                                  const std::string& section_id = "fermi_surface");
    std::string add_phonon_bands(const Json& qpath, const Tensor& frequencies,
                                 const Tensor* eigenvectors = nullptr,
                                 const std::string& section_id = "phonon_bands");
    std::string add_phonon_dos(const Json& meta, const Tensor& frequencies,
                               const Tensor& dos, const Tensor* projected = nullptr,
                               const std::string& section_id = "phonon_dos");
    std::string add_equation_of_state(const Tensor& volumes, const Tensor& energies,
                                      const Json& fit, const std::string& section_id = "eos");
    std::string add_topology_qtaim(const Json& critical_points,
                                   const std::string& section_id = "qtaim");

    // --- output ---
    Json build_manifest() const;
    std::vector<uint8_t> to_bytes();
    std::string write(const std::string& path);

private:
    std::string reserve_id(const std::string& id);
    void add_file(const std::string& path, std::vector<uint8_t> bytes);
    Json json_member(const std::string& path, const Json& obj);
    Json binary_member(const std::string& path, const Tensor& t, bool with_shape = true);

    Source source_;
    Json root_ = Json::object();          // optional root blocks
    Json sections_ = Json::array();
    std::vector<std::pair<std::string, std::vector<uint8_t>>> files_;
    std::set<std::string> ids_;
    std::set<std::string> paths_;
};

}  // namespace qvf

#endif  // QVF_QVF_HPP
