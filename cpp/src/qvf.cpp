// qvf.cpp — implementation of the QVF writer library. License: Apache-2.0.
#include "qvf/qvf.hpp"

#include <cmath>
#include <cstring>
#include <fstream>
#include <stdexcept>

#include "qvf_sha256.hpp"
#include "qvf_zip.hpp"

namespace qvf {

// ---------------------------------------------------------------------------
// dtype helpers
// ---------------------------------------------------------------------------

static const char* dtype_name(DType d) {
    switch (d) {
        case DType::Int8: return "int8";
        case DType::Int16: return "int16";
        case DType::Int32: return "int32";
        case DType::Int64: return "int64";
        case DType::UInt8: return "uint8";
        case DType::UInt16: return "uint16";
        case DType::UInt32: return "uint32";
        case DType::UInt64: return "uint64";
        case DType::Float32: return "float32";
        case DType::Float64: return "float64";
    }
    return "float64";
}

static size_t dtype_itemsize(DType d) {
    switch (d) {
        case DType::Int8: case DType::UInt8: return 1;
        case DType::Int16: case DType::UInt16: return 2;
        case DType::Int32: case DType::UInt32: case DType::Float32: return 4;
        case DType::Int64: case DType::UInt64: case DType::Float64: return 8;
    }
    return 8;
}

static void put_le(std::vector<uint8_t>& out, uint64_t v, int nbytes) {
    for (int i = 0; i < nbytes; ++i)
        out.push_back(static_cast<uint8_t>((v >> (8 * i)) & 0xFF));
}

Tensor tensor_f64(const std::vector<double>& v, std::vector<int64_t> shape) {
    Tensor t;
    t.dtype = DType::Float64;
    t.shape = std::move(shape);
    t.bytes.reserve(v.size() * 8);
    for (double x : v) {
        uint64_t bits;
        std::memcpy(&bits, &x, 8);
        put_le(t.bytes, bits, 8);
    }
    return t;
}

Tensor tensor_f32(const std::vector<double>& v, std::vector<int64_t> shape) {
    Tensor t;
    t.dtype = DType::Float32;
    t.shape = std::move(shape);
    t.bytes.reserve(v.size() * 4);
    for (double x : v) {
        float f = static_cast<float>(x);
        uint32_t bits;
        std::memcpy(&bits, &f, 4);
        put_le(t.bytes, bits, 4);
    }
    return t;
}

Tensor tensor_i32(const std::vector<int32_t>& v, std::vector<int64_t> shape) {
    Tensor t;
    t.dtype = DType::Int32;
    t.shape = std::move(shape);
    t.bytes.reserve(v.size() * 4);
    for (int32_t x : v) put_le(t.bytes, static_cast<uint32_t>(x), 4);
    return t;
}

Tensor tensor_i64(const std::vector<int64_t>& v, std::vector<int64_t> shape) {
    Tensor t;
    t.dtype = DType::Int64;
    t.shape = std::move(shape);
    t.bytes.reserve(v.size() * 8);
    for (int64_t x : v) put_le(t.bytes, static_cast<uint64_t>(x), 8);
    return t;
}

double primitive_norm(double alpha, int l) {
    double radial = std::pow(2.0 * alpha / M_PI, 0.75);
    double angular = std::pow(4.0 * alpha, l / 2.0);
    double df = 1.0;
    for (int k = 1; k < 2 * l; k += 2) df *= k;  // (2l-1)!!
    return radial * angular / std::sqrt(df);
}

// Minimal Z -> symbol table (0..118).
static std::string symbol_for(int z) {
    static const char* S[] = {
        "X","H","He","Li","Be","B","C","N","O","F","Ne","Na","Mg","Al","Si","P",
        "S","Cl","Ar","K","Ca","Sc","Ti","V","Cr","Mn","Fe","Co","Ni","Cu","Zn",
        "Ga","Ge","As","Se","Br","Kr","Rb","Sr","Y","Zr","Nb","Mo","Tc","Ru","Rh",
        "Pd","Ag","Cd","In","Sn","Sb","Te","I","Xe","Cs","Ba","La","Ce","Pr","Nd",
        "Pm","Sm","Eu","Gd","Tb","Dy","Ho","Er","Tm","Yb","Lu","Hf","Ta","W","Re",
        "Os","Ir","Pt","Au","Hg","Tl","Pb","Bi","Po","At","Rn","Fr","Ra","Ac","Th",
        "Pa","U","Np","Pu","Am","Cm","Bk","Cf","Es","Fm","Md","No","Lr","Rf","Db",
        "Sg","Bh","Hs","Mt","Ds","Rg","Cn","Nh","Fl","Mc","Lv","Ts","Og"};
    if (z >= 0 && z < static_cast<int>(sizeof(S) / sizeof(S[0]))) return S[z];
    return "X";
}

static bool is_valid_id(const std::string& s) {
    if (s.empty()) return false;
    for (char c : s)
        if (!(std::isalnum(static_cast<unsigned char>(c)) || c == '_' ||
              c == '.' || c == '-'))
            return false;
    return true;
}

// ---------------------------------------------------------------------------
// QvfWriter
// ---------------------------------------------------------------------------

QvfWriter::QvfWriter(Source source) : source_(std::move(source)) {
    if (source_.program.empty() || source_.version.empty())
        throw std::runtime_error("source.program and source.version are required");
}

std::string QvfWriter::reserve_id(const std::string& id) {
    if (!is_valid_id(id))
        throw std::runtime_error("invalid section id: " + id);
    if (ids_.count(id)) throw std::runtime_error("duplicate section id: " + id);
    ids_.insert(id);
    return id;
}

void QvfWriter::add_file(const std::string& path, std::vector<uint8_t> bytes) {
    if (paths_.count(path)) throw std::runtime_error("duplicate member path: " + path);
    if (path.empty() || path.front() == '/' ||
        path.find("/../") != std::string::npos || path.rfind("../", 0) == 0)
        throw std::runtime_error("illegal member path: " + path);
    paths_.insert(path);
    files_.emplace_back(path, std::move(bytes));
}

Json QvfWriter::json_member(const std::string& path, const Json& obj) {
    std::string dumped = obj.dump(2);
    std::vector<uint8_t> bytes(dumped.begin(), dumped.end());
    std::string sha = detail::Sha256::hex_of(bytes);
    add_file(path, std::move(bytes));
    Json m = Json::object();
    m.set("path", path).set("format", "json").set("sha256", sha);
    return m;
}

Json QvfWriter::binary_member(const std::string& path, const Tensor& t,
                              bool with_shape) {
    // Sanity: byte length must equal itemsize * prod(shape).
    size_t n = 1;
    for (int64_t d : t.shape) n *= static_cast<size_t>(d);
    if (with_shape && t.bytes.size() != dtype_itemsize(t.dtype) * n)
        throw std::runtime_error("binary member byte length != itemsize*prod(shape): "
                                 + path);
    std::string sha = detail::Sha256::hex_of(t.bytes);
    std::vector<uint8_t> bytes = t.bytes;
    add_file(path, std::move(bytes));
    Json m = Json::object();
    m.set("path", path).set("format", "binary");
    if (with_shape) {
        m.set("dtype", std::string(dtype_name(t.dtype)));
        Json shape = Json::array();
        for (int64_t d : t.shape) shape.push_back(Json(static_cast<long long>(d)));
        m.set("shape", shape);
    }
    m.set("sha256", sha);
    return m;
}

// -- root metadata ----------------------------------------------------------

void QvfWriter::set_provenance(Json v) { root_.set("provenance", std::move(v)); }
void QvfWriter::set_thermochemistry(Json v) { root_.set("thermochemistry", std::move(v)); }
void QvfWriter::set_dipole_moment(Json v) { root_.set("dipole_moment", std::move(v)); }
void QvfWriter::set_constraints(Json v) { root_.set("constraints", std::move(v)); }
void QvfWriter::set_extensions(Json v) { root_.set("extensions", std::move(v)); }
void QvfWriter::set_viewer_defaults(Json v) { root_.set("viewer_defaults", std::move(v)); }

// -- structure --------------------------------------------------------------

std::string QvfWriter::add_structure(const std::vector<Atom>& atoms,
                                     const std::array<bool, 3>& pbc,
                                     const std::vector<std::array<double, 3>>& lattice,
                                     const std::vector<Bond>& bonds,
                                     const std::string& section_id) {
    const bool periodic = pbc[0] || pbc[1] || pbc[2];
    if (periodic && lattice.empty()) {
        throw std::runtime_error(
            "add_structure: pbc marks a periodic axis, so lattice_vectors is "
            "required (QVF spec § 5.1)");
    }
    if (!lattice.empty() && lattice.size() != 3) {
        throw std::runtime_error(
            "add_structure: lattice_vectors must be 3 row vectors");
    }
    Json atoms_json = Json::array();
    for (const auto& a : atoms) {
        Json aj = Json::object();
        std::string sym = a.symbol.empty() ? symbol_for(a.atomic_number) : a.symbol;
        Json pos = Json::array();
        for (double x : a.position) pos.push_back(Json(x));
        aj.set("symbol", sym).set("position", pos)
          .set("atomic_number", a.atomic_number);
        atoms_json.push_back(aj);
    }
    Json pbc_json = Json::array();
    for (bool p : pbc) pbc_json.push_back(Json(p));
    Json structure = Json::object();
    structure.set("atoms", atoms_json).set("pbc", pbc_json);
    if (!lattice.empty()) {
        Json lat = Json::array();
        for (const auto& row : lattice) {
            Json r = Json::array();
            for (double x : row) r.push_back(Json(x));
            lat.push_back(r);
        }
        structure.set("lattice_vectors", lat);
    } else {
        structure.set("lattice_vectors", Json(nullptr));
    }

    Json members = Json::object();
    members.set("structure", json_member(section_id + "/structure.json", structure));
    if (!bonds.empty()) {
        Json pairs = Json::array();
        for (const auto& b : bonds) {
            Json p = Json::object();
            p.set("i", b.i).set("j", b.j).set("order", b.order);
            pairs.push_back(p);
        }
        Json bj = Json::object();
        bj.set("pairs", pairs);
        members.set("bonds", json_member(section_id + "/bonds.json", bj));
    }
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "structure")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_bonds(const std::vector<Bond>& pairs,
                                 const std::string& section_id) {
    Json pj = Json::array();
    for (const auto& b : pairs) {
        Json p = Json::object();
        p.set("i", b.i).set("j", b.j).set("order", b.order);
        pj.push_back(p);
    }
    Json payload = Json::object();
    payload.set("pairs", pj);
    Json members = Json::object();
    members.set("bonds", json_member(section_id + "/connectivity.json", payload));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "bonds")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_bond_orders(const std::string& method, const Json& pairs,
                                       const std::string& section_id) {
    Json payload = Json::object();
    payload.set("method", method).set("pairs", pairs);
    Json members = Json::object();
    members.set("bond_orders", json_member(section_id + "/orders.json", payload));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "bond_orders")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

// -- wavefunction -----------------------------------------------------------

static Tensor matrix_to_tensor(const Matrix& m) {
    if (m.data.size() != static_cast<size_t>(m.rows * m.cols))
        throw std::runtime_error("Matrix data size does not match rows*cols");
    return tensor_f64(m.data, {m.rows, m.cols});
}

std::string QvfWriter::add_wavefunction_gto(const WavefunctionGTO& wf) {
    Json shells_json = Json::array();
    int64_t n_ao = 0;
    for (const auto& sh : wf.shells) {
        if (sh.exponents.size() != sh.coefficients.size())
            throw std::runtime_error("shell exponents/coefficients length mismatch");
        Json exps = Json::array(), coeffs = Json::array();
        for (size_t i = 0; i < sh.exponents.size(); ++i) {
            double c = sh.coefficients[i];
            if (wf.coeffs_are_libint_normalized)
                c /= primitive_norm(sh.exponents[i], sh.l);
            exps.push_back(Json(sh.exponents[i]));
            coeffs.push_back(Json(c));
        }
        Json sj = Json::object();
        sj.set("center", sh.center).set("l", sh.l)
          .set("exponents", exps).set("coefficients", coeffs)
          .set("pure", sh.pure);
        shells_json.push_back(sj);
        n_ao += sh.pure ? (2 * sh.l + 1) : ((sh.l + 1) * (sh.l + 2) / 2);
    }

    Json basis = Json::object();
    basis.set("structure_ref", wf.structure_ref).set("pure", wf.pure)
         .set("n_ao", static_cast<long long>(n_ao)).set("shells", shells_json);

    Json members = Json::object();
    members.set("basis", json_member(wf.section_id + "/basis.json", basis));

    auto energies_or_zeros = [](const std::vector<double>& e, int64_t n) {
        Json a = Json::array();
        for (int64_t i = 0; i < n; ++i)
            a.push_back(Json(i < static_cast<int64_t>(e.size()) ? e[i] : 0.0));
        return a;
    };

    Json mo_meta = Json::object();
    if (!wf.unrestricted) {
        Tensor C = matrix_to_tensor(wf.mo_coefficients);
        int64_t n_mo = wf.mo_coefficients.rows;
        mo_meta.set("n_mo", static_cast<long long>(n_mo))
               .set("n_ao", static_cast<long long>(n_ao))
               .set("spin", "restricted").set("orbital_kind", wf.orbital_kind)
               .set("energies", energies_or_zeros(wf.energies, n_mo))
               .set("occupations", energies_or_zeros(wf.occupations, n_mo));
        if (wf.has_kpoint) {
            Json k = Json::array();
            for (double x : wf.kpoint) k.push_back(Json(x));
            mo_meta.set("k_point", k);
        }
        members.set("mo_metadata",
                    json_member(wf.section_id + "/mo_metadata.json", mo_meta));
        members.set("mo_coefficients",
                    binary_member(wf.section_id + "/mo_coefficients.dat", C));
    } else {
        Tensor Ca = matrix_to_tensor(wf.mo_coefficients_alpha);
        Tensor Cb = matrix_to_tensor(wf.mo_coefficients_beta);
        int64_t na = wf.mo_coefficients_alpha.rows, nb = wf.mo_coefficients_beta.rows;
        Json alpha = Json::object(), beta = Json::object();
        alpha.set("n_mo", static_cast<long long>(na))
             .set("energies", energies_or_zeros(wf.energies_alpha, na))
             .set("occupations", energies_or_zeros(wf.occupations_alpha, na));
        beta.set("n_mo", static_cast<long long>(nb))
            .set("energies", energies_or_zeros(wf.energies_beta, nb))
            .set("occupations", energies_or_zeros(wf.occupations_beta, nb));
        mo_meta.set("n_ao", static_cast<long long>(n_ao))
               .set("spin", "unrestricted").set("orbital_kind", wf.orbital_kind)
               .set("alpha", alpha).set("beta", beta);
        if (wf.has_kpoint) {
            Json k = Json::array();
            for (double x : wf.kpoint) k.push_back(Json(x));
            mo_meta.set("k_point", k);
        }
        members.set("mo_metadata",
                    json_member(wf.section_id + "/mo_metadata.json", mo_meta));
        members.set("mo_coefficients_alpha",
                    binary_member(wf.section_id + "/mo_coefficients_alpha.dat", Ca));
        members.set("mo_coefficients_beta",
                    binary_member(wf.section_id + "/mo_coefficients_beta.dat", Cb));
    }

    Json section = Json::object();
    section.set("id", reserve_id(wf.section_id)).set("kind", "wavefunction.gto")
           .set("members", members);
    sections_.push_back(section);
    return wf.section_id;
}

// -- spectra ----------------------------------------------------------------

std::string QvfWriter::add_spectrum(const std::string& kind, const Spectrum& spectrum,
                                    const std::string& label,
                                    const std::string& section_id) {
    Json payload = Json::object();
    payload.set("frequencies", Json::from_doubles(spectrum.frequencies));
    payload.set("intensities", Json::from_doubles(spectrum.intensities));
    return add_spectrum(kind, payload, label, section_id);
}

std::string QvfWriter::add_spectrum(const std::string& kind, const Json& payload,
                                    const std::string& label,
                                    const std::string& section_id) {
    std::string sid = section_id;
    if (sid.empty()) {
        sid = kind;
        for (char& c : sid) if (c == '.') c = '_';
    }
    Json members = Json::object();
    members.set("spectrum", json_member("spectra/" + sid + ".json", payload));
    Json section = Json::object();
    section.set("id", reserve_id(sid)).set("kind", kind).set("members", members);
    if (!label.empty()) section.set("label", label);
    sections_.push_back(section);
    return sid;
}

// -- analysis / provenance --------------------------------------------------

std::string QvfWriter::add_atom_properties(const std::vector<double>& mulliken,
                                           const std::vector<double>& loewdin,
                                           const std::vector<double>& spin,
                                           const std::string& section_id) {
    Json members = Json::object();
    if (!mulliken.empty())
        members.set("mulliken_charge",
                    binary_member("atom_properties/mulliken_charge.bin",
                                  tensor_f64(mulliken,
                                             {static_cast<int64_t>(mulliken.size())})));
    if (!loewdin.empty())
        members.set("loewdin_charge",
                    binary_member("atom_properties/loewdin_charge.bin",
                                  tensor_f64(loewdin,
                                             {static_cast<int64_t>(loewdin.size())})));
    if (!spin.empty())
        members.set("spin_population",
                    binary_member("atom_properties/spin_population.bin",
                                  tensor_f64(spin,
                                             {static_cast<int64_t>(spin.size())})));
    if (members.type() != Json::Type::Object || !members.has("mulliken_charge"))
        if (mulliken.empty() && loewdin.empty() && spin.empty())
            throw std::runtime_error("atom_properties needs at least one array");
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "atom_properties")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_scf_history(const Json& iterations,
                                       const std::string& section_id) {
    Json payload = Json::object();
    payload.set("iterations", iterations);
    Json members = Json::object();
    members.set("iterations", json_member(section_id + "/iterations.json", payload));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "scf_history")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_citations(const std::string& bibtex,
                                     const std::string& section_id) {
    std::vector<uint8_t> bytes(bibtex.begin(), bibtex.end());
    std::string path = section_id + "/references.bib";
    std::string sha = detail::Sha256::hex_of(bytes);
    add_file(path, bytes);
    Json member = Json::object();
    member.set("path", path).set("format", "binary").set("sha256", sha);
    Json members = Json::object();
    members.set("references", member);
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "citations")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_run_record(const RunRecord& record,
                                      const std::string& section_id) {
    if (record.program.empty())
        throw std::runtime_error("run.record requires a non-empty program");
    if (record.input_text.empty() && record.log_text.empty())
        throw std::runtime_error(
            "run.record requires input_text and/or log_text");
    Json members = Json::object();
    auto opaque = [&](const std::string& role, const std::string& path,
                      std::vector<uint8_t> bytes) {
        std::string sha = detail::Sha256::hex_of(bytes);
        add_file(path, std::move(bytes));
        Json member = Json::object();
        member.set("path", path).set("format", "binary").set("sha256", sha);
        members.set(role, member);
    };
    if (!record.input_text.empty())
        opaque("input", section_id + "/input.txt",
               std::vector<uint8_t>(record.input_text.begin(),
                                    record.input_text.end()));
    if (!record.log_text.empty())
        opaque("log", section_id + "/log.txt",
               std::vector<uint8_t>(record.log_text.begin(),
                                    record.log_text.end()));
    for (const auto& att : record.attachments)
        opaque("attachment." + att.first,
               section_id + "/attachments/" + att.first, att.second);
    if (record.files.type() == Json::Type::Object)
        members.set("files",
                    json_member(section_id + "/files.json", record.files));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "run.record")
           .set("program", record.program).set("members", members);
    if (!record.program_version.empty())
        section.set("program_version", record.program_version);
    if (!record.command.empty()) section.set("command", record.command);
    if (record.has_exit_status) section.set("exit_status", record.exit_status);
    if (!record.started_utc.empty())
        section.set("started_utc", record.started_utc);
    if (!record.finished_utc.empty())
        section.set("finished_utc", record.finished_utc);
    if (record.sequence >= 0) section.set("sequence", record.sequence);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_job_spec(const Json& spec,
                                    const std::string& section_id) {
    if (spec.type() != Json::Type::Object)
        throw std::runtime_error("job.spec spec must be a JSON object");
    if (!spec.has("job_type") || !spec.at("job_type").is_string())
        throw std::runtime_error("job.spec requires a job_type string");
    const std::string& jt = spec.at("job_type").as_string();
    if (jt != "molecular" && jt != "periodic")
        throw std::runtime_error(
            "job.spec job_type must be 'molecular' or 'periodic', got: " + jt);
    Json members = Json::object();
    members.set("spec", json_member(section_id + "/spec.json", spec));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "job.spec")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

// -- vendor -----------------------------------------------------------------

std::string QvfWriter::add_vendor_section(const std::string& kind,
                                          const Json& json_members, bool critical,
                                          const std::string& schema_uri,
                                          const std::string& section_id) {
    if (kind.rfind("x_", 0) != 0)
        throw std::runtime_error("vendor kind must start with x_: " + kind);
    std::string sid = section_id;
    if (sid.empty()) {
        sid = kind;
        for (char& c : sid) if (c == '.') c = '_';
    }
    // json_members is an object mapping role -> JSON payload; each becomes a
    // JSON member under sid/<role>.json.
    Json members = Json::object();
    for (const auto& kv : json_members.items())
        members.set(kv.first, json_member(sid + "/" + kv.first + ".json", kv.second));
    if (members.size() == 0)
        throw std::runtime_error("vendor section needs at least one member");
    Json section = Json::object();
    section.set("id", reserve_id(sid)).set("kind", kind).set("members", members);
    if (critical) section.set("critical", true);
    if (!schema_uri.empty()) section.set("schema_uri", schema_uri);
    sections_.push_back(section);
    return sid;
}

// -- volumes & basis AO -----------------------------------------------------

static Json grid_json(const Grid& g, const std::vector<int64_t>& shape) {
    Json grid = Json::object();
    Json origin = Json::array();
    for (double x : g.origin) origin.push_back(Json(x));
    Json vox = Json::array();
    for (const auto& v : g.voxel_vectors) {
        Json r = Json::array();
        for (double x : v) r.push_back(Json(x));
        vox.push_back(r);
    }
    Json sh = Json::array();
    for (int64_t d : shape) sh.push_back(Json(static_cast<long long>(d)));
    grid.set("origin", origin).set("voxel_vectors", vox).set("shape", sh);
    return grid;
}

static void merge_peers(Json& section, const Json& extra) {
    if (extra.type() != Json::Type::Object) return;
    for (const auto& kv : extra.items()) section.set(kv.first, kv.second);
}

std::string QvfWriter::add_volume(const std::string& kind, const Grid& grid,
                                  const Tensor& data, const std::string& label,
                                  const std::string& component,
                                  const std::string& section_id) {
    if (data.shape.size() != 3)
        throw std::runtime_error(kind + ": data must be 3-D");
    std::string sid = section_id;
    if (sid.empty()) {
        sid = kind;
        for (char& c : sid) if (c == '.') c = '_';
        sid += "_" + std::to_string(sections_.size());
    }
    Json members = Json::object();
    members.set("grid", json_member("volumes/" + sid + "_grid.json",
                                    grid_json(grid, data.shape)));
    members.set("data", binary_member("volumes/" + sid + ".dat", data));
    Json section = Json::object();
    section.set("id", reserve_id(sid)).set("kind", kind).set("members", members);
    if (!label.empty()) section.set("label", label);
    if (!component.empty()) section.set("component", component);
    sections_.push_back(section);
    return sid;
}

std::string QvfWriter::add_volume_difference(const Grid& grid, const Tensor& data,
                                             const std::string& operand_a,
                                             const std::string& operand_b,
                                             const std::string& description,
                                             const std::string& label,
                                             const std::string& section_id) {
    if (data.shape.size() != 3)
        throw std::runtime_error("volume.difference: data must be 3-D");
    Json members = Json::object();
    members.set("grid", json_member("volumes/" + section_id + "_grid.json",
                                    grid_json(grid, data.shape)));
    members.set("data", binary_member("volumes/" + section_id + ".dat", data));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "volume.difference")
           .set("members", members)
           .set("operand_a", operand_a).set("operand_b", operand_b);
    if (!description.empty()) section.set("description", description);
    if (!label.empty()) section.set("label", label);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_basis_ao(const Json& ao_metadata, const Grid& grid,
                                    const Tensor& data, const std::string& label,
                                    const std::string& section_id) {
    if (data.shape.size() != 3)
        throw std::runtime_error("basis.ao: data must be 3-D");
    std::string sid = section_id.empty()
                          ? "ao_" + std::to_string(sections_.size()) : section_id;
    Json members = Json::object();
    members.set("grid", json_member("basis_ao/" + sid + "_grid.json",
                                    grid_json(grid, data.shape)));
    members.set("data", binary_member("basis_ao/" + sid + ".dat", data));
    Json section = Json::object();
    section.set("id", reserve_id(sid)).set("kind", "basis.ao").set("members", members)
           .set("ao_metadata", ao_metadata);
    if (!label.empty()) section.set("label", label);
    sections_.push_back(section);
    return sid;
}

// -- bands & DOS ------------------------------------------------------------

std::string QvfWriter::add_bands(const Json& kpath, const Tensor& eigenvalues,
                                 const Tensor* projections,
                                 const std::string& section_id) {
    if (eigenvalues.shape.size() != 3)
        throw std::runtime_error("bands: eigenvalues must be [n_spin, n_k, n_bands]");
    Json members = Json::object();
    members.set("kpath", json_member(section_id + "/kpath.json", kpath));
    members.set("eigenvalues",
                binary_member(section_id + "/eigenvalues.bin", eigenvalues));
    if (projections)
        members.set("projections",
                    binary_member(section_id + "/projections.bin", *projections));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "bands")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_dos_total(const Tensor& energies, const Tensor& dos,
                                     const Json& section_meta,
                                     const std::string& section_id) {
    Json members = Json::object();
    members.set("energies",
                binary_member("dos/" + section_id + "_energies.bin", energies));
    members.set("dos", binary_member("dos/" + section_id + ".bin", dos));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "dos.total")
           .set("members", members);
    merge_peers(section, section_meta);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_dos_projected(const Tensor& energies,
                                         const Tensor& projections,
                                         const Json& section_meta,
                                         const std::string& section_id) {
    Json members = Json::object();
    members.set("energies",
                binary_member("dos/" + section_id + "_energies.bin", energies));
    members.set("projections",
                binary_member("dos/" + section_id + "_projections.bin", projections));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "dos.projected")
           .set("members", members);
    merge_peers(section, section_meta);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_dos_coop_cohp(const std::string& kind,
                                         const Tensor& energies,
                                         const Tensor& projections,
                                         const Tensor& integrated, const Json& meta,
                                         const std::string& section_id) {
    if (kind != "dos.coop" && kind != "dos.cohp")
        throw std::runtime_error("kind must be dos.coop or dos.cohp");
    std::string sid = section_id;
    if (sid.empty()) { sid = kind; for (char& c : sid) if (c == '.') c = '_'; }
    Json members = Json::object();
    members.set("energies", binary_member("dos/" + sid + "_energies.bin", energies));
    members.set("projections",
                binary_member("dos/" + sid + "_projections.bin", projections));
    members.set("integrated",
                binary_member("dos/" + sid + "_integrated.bin", integrated));
    members.set("meta", json_member("dos/" + sid + "_meta.json", meta));
    Json section = Json::object();
    section.set("id", reserve_id(sid)).set("kind", kind).set("members", members);
    sections_.push_back(section);
    return sid;
}

// -- trajectories / reactions / scans / vibrations --------------------------

std::string QvfWriter::add_trajectory(const Json& metadata, const Tensor& coords,
                                      const std::string& section_id) {
    if (coords.shape.size() != 3 || coords.shape[2] != 3)
        throw std::runtime_error("trajectory coords must be [n_frames, n_atoms, 3]");
    Json members = Json::object();
    members.set("metadata", json_member(section_id + "/metadata.json", metadata));
    members.set("coords", binary_member(section_id + "/coords.bin", coords));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "trajectory")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_reaction_path(const Json& metadata, const Tensor& coords,
                                         const Tensor* lattice,
                                         const std::string& section_id) {
    if (coords.shape.size() != 3 || coords.shape[2] != 3)
        throw std::runtime_error("reaction.path coords must be [n_frames, n_atoms, 3]");
    Json members = Json::object();
    members.set("metadata", json_member(section_id + "/metadata.json", metadata));
    members.set("coords", binary_member(section_id + "/coords.bin", coords));
    if (lattice) {
        const auto& s = lattice->shape;
        bool fixed = (s.size() == 2 && s[0] == 3 && s[1] == 3);
        bool per_frame = (s.size() == 3 && s[1] == 3 && s[2] == 3);
        if (!fixed && !per_frame)
            throw std::runtime_error(
                "reaction.path lattice must be [3,3] or [n_frames,3,3]");
        if (per_frame && s[0] != coords.shape[0])
            throw std::runtime_error(
                "reaction.path per-frame lattice frame count != coords frames");
        if (lattice->dtype != DType::Float64)
            throw std::runtime_error("reaction.path lattice must be float64");
        members.set("lattice", binary_member(section_id + "/lattice.bin", *lattice));
    }
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "reaction.path")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_reaction_waypoints(const std::string& trajectory_ref,
                                              const Json& waypoints,
                                              const std::string& section_id) {
    if (!ids_.count(trajectory_ref))
        throw std::runtime_error("trajectory_ref not yet added: " + trajectory_ref);
    Json members = Json::object();
    members.set("waypoints", json_member(section_id + "/waypoints.json", waypoints));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "reaction.waypoints")
           .set("trajectory_ref", trajectory_ref).set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_scan_surface(const Json& metadata, const Tensor& axis_a,
                                        const Tensor& axis_b, const Tensor& energies,
                                        const Tensor* geometries,
                                        const std::string& section_id) {
    Json members = Json::object();
    members.set("metadata", json_member(section_id + "/metadata.json", metadata));
    members.set("axis_a", binary_member(section_id + "/axis_a.bin", axis_a));
    members.set("axis_b", binary_member(section_id + "/axis_b.bin", axis_b));
    members.set("energies", binary_member(section_id + "/energies.bin", energies));
    if (geometries)
        members.set("geometries",
                    binary_member(section_id + "/geometries.bin", *geometries));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "scan.surface")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_vibrations(const Json& metadata,
                                      const Tensor& displacements,
                                      const std::string& section_id) {
    if (displacements.shape.size() != 3 || displacements.shape[2] != 3)
        throw std::runtime_error("displacements must be [n_modes, n_atoms, 3]");
    Json members = Json::object();
    members.set("metadata", json_member(section_id + "/metadata.json", metadata));
    members.set("displacements",
                binary_member(section_id + "/displacements.bin", displacements));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "vibrations")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

// -- symmetry & periodic kinds ----------------------------------------------

std::string QvfWriter::add_structure_symmetry(const Json& data,
                                              const std::string& section_id) {
    Json members = Json::object();
    members.set("data", json_member("structure/symmetry.json", data));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "structure.symmetry")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_fermi_surface(const Json& mesh, const Tensor& energies,
                                         const std::string& section_id) {
    if (energies.shape.size() != 4)
        throw std::runtime_error("fermi_surface energies must be 4-D");
    Json members = Json::object();
    members.set("mesh", json_member("fermi/" + section_id + "_mesh.json", mesh));
    members.set("energies", binary_member("fermi/" + section_id + ".bin", energies));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "fermi_surface")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_phonon_bands(const Json& qpath, const Tensor& frequencies,
                                        const Tensor* eigenvectors,
                                        const std::string& section_id) {
    Json members = Json::object();
    members.set("qpath", json_member("phonons/" + section_id + "_qpath.json", qpath));
    members.set("frequencies",
                binary_member("phonons/" + section_id + "_freq.bin", frequencies));
    if (eigenvectors)
        members.set("eigenvectors",
                    binary_member("phonons/" + section_id + "_eig.bin", *eigenvectors));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "phonon_bands")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_phonon_dos(const Json& meta, const Tensor& frequencies,
                                      const Tensor& dos, const Tensor* projected,
                                      const std::string& section_id) {
    Json members = Json::object();
    members.set("meta", json_member("phonons/" + section_id + "_meta.json", meta));
    members.set("frequencies",
                binary_member("phonons/" + section_id + "_freq.bin", frequencies));
    members.set("dos", binary_member("phonons/" + section_id + "_dos.bin", dos));
    if (projected)
        members.set("projected",
                    binary_member("phonons/" + section_id + "_proj.bin", *projected));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "phonon_dos")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_equation_of_state(const Tensor& volumes,
                                             const Tensor& energies, const Json& fit,
                                             const std::string& section_id) {
    Json members = Json::object();
    members.set("volumes", binary_member("eos/" + section_id + "_volumes.bin", volumes));
    members.set("energies",
                binary_member("eos/" + section_id + "_energies.bin", energies));
    members.set("fit", json_member("eos/" + section_id + "_fit.json", fit));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "equation_of_state")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

std::string QvfWriter::add_topology_qtaim(const Json& critical_points,
                                          const std::string& section_id) {
    Json members = Json::object();
    members.set("critical_points",
                json_member("topology/" + section_id + ".json", critical_points));
    Json section = Json::object();
    section.set("id", reserve_id(section_id)).set("kind", "topology.qtaim")
           .set("members", members);
    sections_.push_back(section);
    return section_id;
}

// -- output -----------------------------------------------------------------

Json QvfWriter::build_manifest() const {
    Json m = Json::object();
    m.set("qvf_version", 1);
    m.set("schema_uri", "https://vibe-qc.org/spec/qvf/1/manifest.schema.json");
    Json src = Json::object();
    src.set("program", source_.program).set("version", source_.version)
       .set("calculation", source_.calculation);
    m.set("source", src);
    // Merge optional root blocks in a deterministic order.
    for (const char* key : {"provenance", "thermochemistry", "dipole_moment",
                            "constraints", "extensions", "viewer_defaults"}) {
        for (const auto& kv : root_.items())
            if (kv.first == key) m.set(key, kv.second);
    }
    m.set("sections", sections_);
    return m;
}

std::vector<uint8_t> QvfWriter::to_bytes() {
    std::string manifest = build_manifest().dump(2);
    detail::ZipWriter zip;
    zip.add("manifest.json", manifest, /*compress=*/false);  // STORE: cheap TOC
    for (const auto& f : files_) zip.add(f.first, f.second);  // DEFLATE if smaller
    return zip.finish();
}

std::string QvfWriter::write(const std::string& path) {
    std::string out = path;
    if (out.size() < 4 || out.substr(out.size() - 4) != ".qvf") out += ".qvf";
    std::vector<uint8_t> bytes = to_bytes();
    std::ofstream fh(out, std::ios::binary);
    if (!fh) throw std::runtime_error("cannot open for writing: " + out);
    fh.write(reinterpret_cast<const char*>(bytes.data()),
             static_cast<std::streamsize>(bytes.size()));
    return out;
}

}  // namespace qvf
