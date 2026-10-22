// qvf_reader_facade.cpp — lazy typed member reads. License: Apache-2.0.
#include "qvf/reader.hpp"

#include <limits>
#include <stdexcept>
#include <utility>

#include "qvf_sha256.hpp"

namespace qvf {
namespace facade_reader_detail {

[[noreturn]] void fail(const char* code, const std::string& message) {
    throw std::runtime_error(std::string(code) + ": " + message);
}

bool safe_path(const std::string& path) {
    if ((!path.empty() && path.front() == '/') || path.find('\\') != std::string::npos ||
        path.find('\0') != std::string::npos)
        return false;
    if (path.size() >= 2 && path[1] == ':' &&
        ((path[0] >= 'A' && path[0] <= 'Z') || (path[0] >= 'a' && path[0] <= 'z')))
        return false;
    size_t start = 0;
    while (start <= path.size()) {
        const size_t slash = path.find('/', start);
        const std::string part = path.substr(start, slash == std::string::npos
                                                      ? std::string::npos : slash - start);
        if (part == "..") return false;
        if (slash == std::string::npos) break;
        start = slash + 1;
    }
    return true;
}

bool utf8(const std::vector<uint8_t>& bytes) {
    for (size_t i = 0; i < bytes.size();) {
        const uint8_t lead = bytes[i++];
        if (lead < 0x80) continue;
        size_t tail;
        uint32_t cp, minimum;
        if ((lead & 0xe0) == 0xc0) { tail = 1; cp = lead & 0x1f; minimum = 0x80; }
        else if ((lead & 0xf0) == 0xe0) { tail = 2; cp = lead & 0x0f; minimum = 0x800; }
        else if ((lead & 0xf8) == 0xf0) { tail = 3; cp = lead & 0x07; minimum = 0x10000; }
        else return false;
        if (tail > bytes.size() - i) return false;
        while (tail--) {
            const uint8_t next = bytes[i++];
            if ((next & 0xc0) != 0x80) return false;
            cp = (cp << 6) | (next & 0x3f);
        }
        if (cp < minimum || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff))
            return false;
    }
    return true;
}

DType dtype(const std::string& name, uint64_t& size) {
    static const struct { const char* name; DType type; uint64_t size; } types[] = {
        {"int8", DType::Int8, 1}, {"uint8", DType::UInt8, 1},
        {"int16", DType::Int16, 2}, {"uint16", DType::UInt16, 2},
        {"int32", DType::Int32, 4}, {"uint32", DType::UInt32, 4},
        {"int64", DType::Int64, 8}, {"uint64", DType::UInt64, 8},
        {"float32", DType::Float32, 4}, {"float64", DType::Float64, 8}};
    for (const auto& type : types)
        if (name == type.name) { size = type.size; return type.type; }
    fail("E_DTYPE", "unknown binary dtype: " + name);
}

Json parse(const std::vector<uint8_t>& bytes, const Limits& limits, bool manifest) {
    const char* code = manifest ? "E_MANIFEST_JSON" : "E_JSON_INVALID";
    if (!utf8(bytes)) fail(code, "JSON is not valid UTF-8");
    try {
        return Json::parse(std::string(bytes.begin(), bytes.end()), limits.max_json_depth);
    } catch (const JsonDepthError&) {
        fail("E_JSON_TOO_DEEP", "JSON exceeds the configured nesting depth");
    } catch (const std::exception& e) {
        fail(code, e.what());
    }
}
}  // namespace facade_reader_detail

struct Reader::Impl {
    container::ZipReader zip;
    Limits limits;
    Json raw;
    Manifest typed;

    Impl(container::ZipReader archive, Limits lim)
        : zip(std::move(archive)), limits(lim) {
        using namespace facade_reader_detail;
        for (const auto& name : zip.duplicates())
            if (name != "manifest.json")
                fail("E_ZIP_DUPLICATE_ENTRY", "duplicate ZIP entry: " + name);
        const auto* entry = zip.find("manifest.json");
        if (!entry) fail("E_MANIFEST_MISSING", "missing manifest.json");
        check_limits(*entry);
        if (entry->usize > limits.max_json_bytes)
            fail("E_JSON_TOO_LARGE", "manifest.json exceeds the JSON byte cap");
        raw = parse(zip.read("manifest.json", limits), limits, true);
        if (!raw.is_object()) fail("E_MANIFEST_JSON", "manifest.json must be an object");
        if (raw.has("byte_order") &&
            (!raw.at("byte_order").is_string() || raw.at("byte_order").as_string() != "little"))
            fail("E_SCHEMA", "byte_order must be little");
        typed = Manifest::from_json(raw);
    }

    void check_limits(const container::ZipEntry& entry) const {
        using namespace facade_reader_detail;
        if (entry.usize > limits.max_member_bytes)
            fail("E_MEMBER_TOO_LARGE", entry.name + " exceeds the member byte cap");
        if (zip.total_size() > limits.max_total_bytes)
            fail("E_TOTAL_TOO_LARGE", "archive exceeds the total byte cap");
        if (limits.max_ratio > 0 && entry.method != 0 &&
            entry.usize >= limits.ratio_exempt_bytes &&
            (entry.csize == 0 || static_cast<double>(entry.usize) >
                                    limits.max_ratio * static_cast<double>(entry.csize)))
            fail("E_COMPRESSION_RATIO", entry.name + " exceeds the compression ratio cap");
    }

    const MemberSpec& member(const Section& section, std::string_view role) const {
        using namespace facade_reader_detail;
        const MemberSpec* spec = section.member(role);
        if (!spec || !spec->path)
            fail("E_MEMBER_MALFORMED", "missing member/path for role " + std::string(role));
        if (!safe_path(*spec->path)) fail("E_MEMBER_PATH", "illegal member path");
        const auto* entry = zip.find(*spec->path);
        if (!entry) fail("E_MEMBER_MISSING", "member is absent: " + *spec->path);
        if (spec->extra.has("size"))
            fail("E_MEMBER_MALFORMED", "member size must be a non-negative integer");
        if (spec->size && *spec->size != entry->usize)
            fail("E_BINARY_SIZE", "declared size differs from ZIP entry size");
        check_limits(*entry);
        return *spec;
    }

    void stream(const MemberSpec& spec, const TensorSink& sink, bool verify) const {
        using namespace facade_reader_detail;
        if (!sink) throw std::invalid_argument("qvf::Reader: a member sink is required");
        if (verify && spec.extra.has("sha256"))
            fail("E_SHA256_MISMATCH", "member sha256 must be a string");
        detail::Sha256 hash;
        zip.read_into(*spec.path, [&](const uint8_t* data, size_t n) {
            // Container chunks can include the initial DEFLATE history window.
            // Bound delivery without allocating or copying those bytes.
            constexpr size_t max_chunk = 1u << 20;
            while (n) {
                const size_t chunk = n < max_chunk ? n : max_chunk;
                if (verify && spec.sha256) hash.update(data, chunk);
                sink(data, chunk);
                data += chunk;
                n -= chunk;
            }
        }, limits);
        if (verify && spec.sha256 && hash.hex() != *spec.sha256)
            fail("E_SHA256_MISMATCH", "member sha256 mismatch: " + *spec.path);
    }

    Tensor tensor_metadata(const MemberSpec& spec) const {
        using namespace facade_reader_detail;
        if (!spec.format || *spec.format != MemberSpec::Format::Binary || !spec.dtype)
            fail("E_DTYPE", "tensor requires format=binary and a dtype");
        if (!spec.shape) fail("E_MEMBER_MALFORMED", "tensor requires an integer shape");
        uint64_t itemsize = 0;
        Tensor tensor;
        tensor.dtype = dtype(*spec.dtype, itemsize);
        tensor.shape = *spec.shape;
        uint64_t count = 1;
        for (int64_t dimension : tensor.shape) {
            if (dimension < 0) fail("E_MEMBER_MALFORMED", "tensor shape has a negative extent");
            const uint64_t extent = static_cast<uint64_t>(dimension);
            if (extent && count > UINT64_MAX / extent)
                fail("E_BINARY_SIZE", "tensor element count overflows");
            count *= extent;
        }
        if (count > UINT64_MAX / itemsize || count * itemsize != zip.find(*spec.path)->usize)
            fail("E_BINARY_SIZE", "tensor byte count differs from dtype and shape");
        return tensor;
    }
};

Reader::Reader(std::unique_ptr<Impl> impl) : impl_(std::move(impl)) {}
Reader::Reader(Reader&&) noexcept = default;
Reader& Reader::operator=(Reader&&) noexcept = default;
Reader::~Reader() = default;
Reader Reader::open(const std::string& path, Limits limits) {
    return Reader(std::unique_ptr<Impl>(new Impl(container::ZipReader::open(path), limits)));
}
Reader Reader::from_bytes(std::vector<uint8_t> archive, Limits limits) {
    return Reader(std::unique_ptr<Impl>(
        new Impl(container::ZipReader::from_bytes(std::move(archive)), limits)));
}
const Manifest& Reader::manifest() const { return impl_->typed; }
const Json& Reader::manifest_json() const { return impl_->raw; }
const Section* Reader::section(std::string_view id) const { return manifest().section(id); }
std::vector<const Section*> Reader::sections_of(std::string_view kind) const {
    std::vector<const Section*> result;
    if (manifest().sections)
        for (const auto& section : *manifest().sections)
            if (section.kind && *section.kind == kind) result.push_back(&section);
    return result;
}
uint64_t Reader::member_size(const Section& section, std::string_view role) const {
    const MemberSpec& spec = impl_->member(section, role);
    if (spec.dtype) impl_->tensor_metadata(spec);
    return impl_->zip.find(*spec.path)->usize;
}
void Reader::bytes_into(const Section& section, std::string_view role,
                        const TensorSink& sink, bool verify) const {
    impl_->stream(impl_->member(section, role), sink, verify);
}
std::vector<uint8_t> Reader::bytes(const Section& section, std::string_view role,
                                  bool verify) const {
    const MemberSpec& spec = impl_->member(section, role);
    const uint64_t size = impl_->zip.find(*spec.path)->usize;
    std::vector<uint8_t> result;
    if (size > result.max_size())
        facade_reader_detail::fail("E_MEMBER_TOO_LARGE", "member cannot fit in an owning buffer");
    result.reserve(static_cast<size_t>(size));
    impl_->stream(spec, [&](const uint8_t* data, size_t n) {
        result.insert(result.end(), data, data + n);
    }, verify);
    return result;
}
Json Reader::json(const Section& section, std::string_view role, bool verify) const {
    const MemberSpec& spec = impl_->member(section, role);
    if (!spec.format || *spec.format != MemberSpec::Format::Json)
        facade_reader_detail::fail("E_MEMBER_MALFORMED", "json() requires a JSON member");
    if (impl_->zip.find(*spec.path)->usize > impl_->limits.max_json_bytes)
        facade_reader_detail::fail("E_JSON_TOO_LARGE", "member exceeds the JSON byte cap");
    return facade_reader_detail::parse(bytes(section, role, verify), impl_->limits, false);
}
Tensor Reader::tensor(const Section& section, std::string_view role, bool verify) const {
    const MemberSpec& spec = impl_->member(section, role);
    Tensor result = impl_->tensor_metadata(spec);
    result.bytes = bytes(section, role, verify);
    return result;
}
void Reader::tensor_into(const Section& section, std::string_view role,
                          const TensorSink& sink, bool verify) const {
    const MemberSpec& spec = impl_->member(section, role);
    impl_->tensor_metadata(spec);  // reject size/shape before delivering any data
    impl_->stream(spec, sink, verify);
}
qvf::validate::Report Reader::validate(qvf::validate::Level level,
                                  const ValidationOptions& options) const {
    return qvf::validate::run(impl_->zip, level, impl_->limits, options);
}

}  // namespace qvf
