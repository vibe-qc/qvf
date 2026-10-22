// License: Apache-2.0.
#include "qvf/writer.hpp"
#include "qvf_schema_check.hpp"
namespace qvf {
namespace facade_writer_detail {
const char* dtype_name(DType d) {
    switch (d) {
        case DType::Int8: return "int8"; case DType::UInt8: return "uint8";
        case DType::Int16: return "int16"; case DType::UInt16: return "uint16";
        case DType::Int32: return "int32"; case DType::UInt32: return "uint32";
        case DType::Int64: return "int64"; case DType::UInt64: return "uint64";
        case DType::Float32: return "float32"; case DType::Float64: return "float64";
    }
    throw std::invalid_argument("invalid dtype");
}
void check_schema(std::string_view name, const Json& value) {
    const auto errors = detail::schema::check_definition(name, value);
    if (!errors.empty()) throw std::invalid_argument(std::string(name) + ": " +
        errors.front().pointer + ": " + errors.front().message);
}
const gen::RoleInfo* role_info(std::string_view kind, std::string_view role) {
    for (const auto& k : gen::kKindInfos)
        if (k.kind == kind)
            for (size_t i = 0; i < k.n_roles; ++i)
                if (!k.roles[i].pattern && k.roles[i].role == role) return &k.roles[i];
    return nullptr;
}
void add_spec(Section& s, const std::string& role, MemberSpec m) {
    if (s.member(role)) throw std::invalid_argument("duplicate member role: " + role);
    if (!s.members) s.members = std::vector<std::pair<std::string, MemberSpec>>{};
    s.members->emplace_back(role, std::move(m));
}
MemberSpec placeholder(const Section& s, const std::string& role, bool json) {
    MemberSpec m;
    m.path = s.id.value_or("") + "/" + role + (json ? ".json" : ".bin");
    m.format = json ? MemberSpec::Format::Json : MemberSpec::Format::Opaque;
    m.sha256 = std::string(64, '0');
    return m;
}
} // namespace facade_writer_detail
Writer::Writer(Source source) {
    auto memory = std::make_unique<container::MemorySink>();
    memory_ = memory.get();
    writer_ = std::make_unique<QvfWriter>(std::move(source), std::move(memory));
}
Writer::Writer(Source source, std::unique_ptr<container::Sink> sink)
    : writer_(std::make_unique<QvfWriter>(std::move(source), std::move(sink))) {}
Writer::Writer(Source source, const std::string& path)
    : writer_(std::make_unique<QvfWriter>(std::move(source), path)) {}
Writer::Writer(QvfWriter writer) : writer_(std::make_unique<QvfWriter>(std::move(writer))) {}
Writer::Writer(Writer&&) noexcept = default;
Writer& Writer::operator=(Writer&&) noexcept = default;
Writer::~Writer() = default;
void Writer::require_open() const {
    if (!writer_ || finished_) throw std::runtime_error("Writer is finished or moved from");
}
void Writer::set_root(RootBlock b, Json value) {
    require_open();
    switch (b) {
        case RootBlock::Provenance: writer_->set_provenance(std::move(value)); break;
        case RootBlock::Metadata: writer_->set_metadata(std::move(value)); break;
        case RootBlock::ViewerDefaults: writer_->set_viewer_defaults(std::move(value)); break;
        case RootBlock::Thermochemistry: writer_->set_thermochemistry(std::move(value)); break;
        case RootBlock::DipoleMoment: writer_->set_dipole_moment(std::move(value)); break;
        case RootBlock::Constraints: writer_->set_constraints(std::move(value)); break;
        case RootBlock::Energies: writer_->set_energies(std::move(value)); break;
        case RootBlock::Extensions: writer_->set_extensions(std::move(value)); break;
    }
}
void Writer::set_auto_metadata(bool enabled) { require_open(); writer_->auto_metadata = enabled; }
void Writer::set_force_zip64(bool enabled) { require_open(); writer_->force_zip64 = enabled; }
Manifest Writer::manifest() const {
    if (!writer_) throw std::runtime_error("Writer was moved from");
    return Manifest::from_json(writer_->build_manifest());
}
std::string Writer::add_section(Section section) {
    require_open(); return writer_->add_section(std::move(section));
}
MemberSink Writer::begin_binary(std::string id, std::string role, DType dtype,
                                std::vector<int64_t> shape) {
    require_open();
    // The backend accepts legacy roles; this facade rejects path separators.
    if (role.empty() || role.find_first_of("/\\") != std::string::npos || role == "." || role == "..")
        throw std::invalid_argument("invalid member role: " + role);
    return writer_->begin_binary(id, role, dtype, std::move(shape));
}
void Writer::add_json(const std::string& id, const std::string& role, Json value) {
    require_open(); writer_->add_json_member(id, role, std::move(value));
}
void Writer::add_opaque(const std::string& id, const OpaquePayload& value) {
    require_open(); writer_->add_section_opaque(id, value.role, value.bytes, value.media_type.value_or(""));
}
void Writer::add_tensor(const std::string& id, const BinaryPayload& value) {
    require_open();
    const TensorView view = value.value.view();
    view.byte_size();
    const DType dtype = value.value.output_dtype.value_or(view.dtype);
    auto sink = begin_binary(id, value.role, dtype, view.shape);
    view.write_into([&sink](const uint8_t* p, size_t n) { sink.write(p, n); }, dtype);
    sink.close();
}
std::string Writer::add_payload(Section section, const std::vector<JsonPayload>& json,
                                const std::vector<BinaryPayload>& binary,
                                const std::vector<OpaquePayload>& opaque) {
    using namespace facade_writer_detail;
    require_open();
    if (!section.id || !section.kind) throw std::invalid_argument("section id/kind required");
    if (section.members && !section.members->empty())
        throw std::invalid_argument("add_payload requires payloads, not member descriptors");
    // Validate against the same generated schema used by the readers, using
    // placeholder hashes; real member hashes are computed while streaming.
    Section checked = section;
    checked.members = std::vector<std::pair<std::string, MemberSpec>>{};
    for (const auto& p : json) {
        const auto* role = role_info(*section.kind, p.role);
        if (role && !role->payload_def.empty()) check_schema(role->payload_def, p.value);
        add_spec(checked, p.role, placeholder(section, p.role, true));
    }
    for (const auto& p : binary) {
        const auto v = p.value.view(); v.byte_size();
        auto m = placeholder(section, p.role, false);
        m.dtype = facade_writer_detail::dtype_name(p.value.output_dtype.value_or(v.dtype));
        m.format = MemberSpec::Format::Binary; m.shape = v.shape;
        add_spec(checked, p.role, std::move(m));
    }
    for (const auto& p : opaque) {
        auto m = placeholder(section, p.role, false); m.media_type = p.media_type;
        add_spec(checked, p.role, std::move(m));
    }
    check_schema("Section", checked.to_json());
    const std::string id = add_section(std::move(section)); // ID checked before any payload write
    try {
        for (const auto& p : json) add_json(id, p.role, p.value);
        for (const auto& p : binary) add_tensor(id, p);
        for (const auto& p : opaque) add_opaque(id, p);
    } catch (...) {
        writer_->remove_section(id);
        throw;
    }
    return id;
}
void Writer::finish() {
    if (finished_) return;
    require_open(); writer_->write(); finished_ = true;
}
std::vector<uint8_t> Writer::to_bytes() {
    if (!writer_ || !memory_) throw std::runtime_error("to_bytes requires the default memory Writer");
    finish(); return memory_->take();
}
} // namespace qvf
