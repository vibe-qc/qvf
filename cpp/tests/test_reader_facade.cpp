// test_reader_facade.cpp — lazy access, bounded streaming and validation stages.
// License: Apache-2.0.
#include <algorithm>
#include <cstdint>
#include <chrono>
#include <fstream>
#include <filesystem>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "qvf/reader.hpp"
#include "qvf_sha256.hpp"

namespace {
int failures = 0;
#define CHECK(test, message) do { if (!(test)) { \
    std::cerr << "FAIL: " << message << "\n"; ++failures; } } while (false)
using qvf::Json;
using qvf::validate::Level;
using qvf::validate::Report;
using Bytes = std::vector<uint8_t>;

bool throws(const std::function<void()>& call, const std::string& text) {
    try { call(); }
    catch (const std::exception& e) { return std::string(e.what()).find(text) != std::string::npos; }
    return false;
}
bool has(const Report& report, const std::string& code) {
    return std::any_of(report.findings.begin(), report.findings.end(),
                       [&](const qvf::Finding& finding) { return finding.code == code; });
}
Bytes text_bytes(const std::string& text) { return Bytes(text.begin(), text.end()); }
Json object(std::initializer_list<std::pair<std::string, Json>> entries) {
    Json result = Json::object();
    for (const auto& entry : entries) result.set(entry.first, entry.second);
    return result;
}
Json array(std::initializer_list<Json> entries) {
    Json result = Json::array();
    for (const auto& entry : entries) result.push_back(entry);
    return result;
}
bool equal_json(const Json& a, const Json& b) {
    if (a.type() != b.type() || a.size() != b.size()) return false;
    if (a.is_object()) {
        for (const auto& entry : a.items())
            if (!b.has(entry.first) || !equal_json(entry.second, b.at(entry.first))) return false;
        return true;
    }
    if (a.is_array()) {
        for (size_t i = 0; i < a.size(); ++i) if (!equal_json(a.at(i), b.at(i))) return false;
        return true;
    }
    return a.dump() == b.dump();
}
Json member(const std::string& path, const Bytes& bytes, const std::string& format) {
    return object({{"path", path}, {"format", format},
                         {"sha256", qvf::detail::Sha256::hex_of(bytes)},
                         {"size", Json(static_cast<unsigned long long>(bytes.size()))}});
}
Json manifest(const Bytes& data, const Bytes& meta) {
    Json tensor = member("sample/data.bin", data, "binary");
    tensor.set("dtype", "uint8");
    tensor.set("shape", array({Json(static_cast<unsigned long long>(data.size()))}));
    Json section = object({{"id", "sample"}, {"kind", "x_reader_test.tensor"},
                                  {"x_annotation", "retained"},
                                  {"members", object({{"data", tensor},
                                      {"meta", member("sample/meta.json", meta, "json")}})}});
    return object({{"qvf_version", 1}, {"byte_order", "little"},
                          {"source", object({{"program", "reader-test"},
                              {"version", "1"}, {"calculation", "synthetic"}})},
                          {"sections", array({section})}});
}
Bytes archive(const Json& manifest, const Bytes& data, const Bytes& meta,
              qvf::container::Method method = qvf::container::Method::Store) {
    auto sink = std::unique_ptr<qvf::container::MemorySink>(new qvf::container::MemorySink);
    auto* memory = sink.get();
    qvf::container::ZipWriter writer(std::move(sink));
    writer.write("sample/data.bin", data, method);
    writer.write("sample/meta.json", meta);
    writer.write("manifest.json", manifest.dump(), qvf::container::Method::Store);
    writer.finish();
    return memory->take();
}
Json with_data_spec(Json source, const std::function<void(Json&)>& edit) {
    Json sections = source.at("sections");
    Json section = sections.at(0);
    Json members = section.at("members");
    Json data = members.at("data");
    edit(data);
    members.set("data", data);
    section.set("members", members);
    sections = array({section});
    source.set("sections", sections);
    return source;
}

// A test-only typed decoder proving the customization protocol. Canonical
// kinds implement this same API in kinds/, with their own typed fields.
struct TestValue {
    int64_t value;
    static TestValue from_section(const qvf::Reader& reader, const qvf::Section& section) {
        if (!section.kind || *section.kind != "x_reader_test.tensor")
            throw std::invalid_argument("wrong kind");
        return {reader.json(section, "meta").at("value").as_int()};
    }
};

void access_and_streaming() {
    Bytes data(3 * 1024 * 1024 + 17);
    for (size_t i = 0; i < data.size(); ++i) data[i] = static_cast<uint8_t>(i % 251);
    const Bytes meta = text_bytes("{\"value\":7}");
    const Json root = manifest(data, meta);
    for (const auto method : {qvf::container::Method::Store, qvf::container::Method::Deflate}) {
        auto reader = qvf::Reader::from_bytes(archive(root, data, meta, method));
        const qvf::Section* section = reader.section("sample");
        CHECK(section != nullptr, "section lookup");
        CHECK(reader.sections_of("x_reader_test.tensor").size() == 1, "kind lookup");
        CHECK(reader.sections_of("missing").empty(), "missing kind lookup");
        CHECK(reader.section("missing") == nullptr, "missing section lookup");
        CHECK(section->extra.at("x_annotation").as_string() == "retained", "lossless typed extras");
        CHECK(equal_json(reader.manifest().to_json(), reader.manifest_json()), "typed manifest round trip");
        CHECK(reader.json(*section, "meta").at("value").as_int() == 7, "JSON member");
        CHECK(reader.get<TestValue>("sample").value == 7, "get<K> decoder protocol");
        CHECK(reader.validate(Level::Manifest).n_sections == 1, "parsed section count");
        CHECK(reader.validate(Level::Container).n_sections == 0, "container stage does not count unread sections");
        CHECK(throws([&] { reader.get<TestValue>("missing"); }, "E_REF_UNRESOLVED"), "get missing id");
        const qvf::Tensor tensor = reader.tensor(*section, "data");
        CHECK(tensor.dtype == qvf::DType::UInt8 && tensor.shape == std::vector<int64_t>{static_cast<int64_t>(data.size())}, "typed tensor metadata");
        CHECK(tensor.bytes == data, "owning tensor bytes");
        size_t count = 0, calls = 0, max_chunk = 0;
        bool equal = true;
        reader.tensor_into(*section, "data", [&](const uint8_t* chunk, size_t n) {
            equal = equal && count + n <= data.size() && std::equal(chunk, chunk + n, data.data() + count);
            count += n; ++calls; max_chunk = std::max(max_chunk, n);
        });
        CHECK(equal && count == data.size() && calls > 1 && max_chunk <= (1u << 20), "bounded streamed tensor bytes");
        CHECK(throws([&] { reader.tensor_into(*section, "data", [](const uint8_t*, size_t) {
            throw std::runtime_error("consumer-stop");
        }); }, "consumer-stop"), "callback exceptions propagate");
        auto moved = std::move(reader);
        CHECK(moved.json(*section, "meta").at("value").as_int() == 7, "section remains valid across Reader move");
    }
}

void lazy_integrity_and_limits() {
    const Bytes data(4096, 42), meta = text_bytes("{\"value\":7}");
    const Json root = manifest(data, meta);
    const Json bad_sha = with_data_spec(root, [](Json& spec) { spec.set("sha256", std::string(64, '0')); });
    const Bytes wrong_hash = archive(bad_sha, data, meta);
    auto reader = qvf::Reader::from_bytes(wrong_hash);  // opening must not read/check payload
    const auto* section = reader.section("sample");
    size_t delivered = 0;
    CHECK(throws([&] { reader.tensor_into(*section, "data", [&](const uint8_t*, size_t n) { delivered += n; }); }, "E_SHA256_MISMATCH"), "stream final sha mismatch");
    CHECK(delivered == data.size(), "final SHA can fail after chunks were delivered");
    CHECK(reader.tensor(*section, "data", false).bytes == data, "optional SHA verification only");
    CHECK(!has(reader.validate(Level::Manifest), "E_SHA256_MISMATCH"), "manifest stage does not hash payload");
    CHECK(has(reader.validate(Level::Payloads), "E_SHA256_MISMATCH"), "payload stage hashes payload");

    Bytes bad_crc = archive(root, data, meta);
    const auto directory = qvf::container::ZipReader::from_bytes(bad_crc);
    const auto entry = directory.find("sample/data.bin");
    bad_crc.at(static_cast<size_t>(directory.local_header(*entry).data_offset)) ^= 1;
    auto corrupt = qvf::Reader::from_bytes(bad_crc);  // CRC-corrupt data remains lazy
    CHECK(corrupt.json(*corrupt.section("sample"), "meta").at("value").as_int() == 7, "unrequested corrupt member is not read");
    CHECK(qvf::validate::run_bytes(bad_crc, Level::Manifest).ok, "manifest stage never decodes corrupt member");
    CHECK(has(qvf::validate::run_bytes(bad_crc, Level::Payloads), "E_ZIP_UNREADABLE"), "payload stage checks CRC");
    CHECK(throws([&] { corrupt.tensor(*corrupt.section("sample"), "data", false); }, "CRC"), "CRC enforced even with SHA verification disabled");

    // Exercise the same lazy path through a held file, with no product-tree
    // scratch. The owning test object removes its temporary file on exit.
    struct TemporaryArchive {
        std::filesystem::path path = std::filesystem::temp_directory_path() /
            ("qvf-reader-facade-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + ".qvf");
        ~TemporaryArchive() { std::error_code error; std::filesystem::remove(path, error); }
    } temporary;
    {
        std::ofstream output(temporary.path, std::ios::binary);
        output.write(reinterpret_cast<const char*>(bad_crc.data()), static_cast<std::streamsize>(bad_crc.size()));
        if (!output) throw std::runtime_error("cannot write test archive");
    }
    auto on_disk = qvf::Reader::open(temporary.path.string());
    CHECK(on_disk.json(*on_disk.section("sample"), "meta").at("value").as_int() == 7, "file-backed member access is lazy");
    CHECK(throws([&] { on_disk.tensor(*on_disk.section("sample"), "data"); }, "CRC"), "file-backed member CRC on demand");

    qvf::Limits limits;
    limits.max_member_bytes = 1024;
    auto limited = qvf::Reader::from_bytes(archive(root, data, meta), limits);
    CHECK(throws([&] { limited.tensor(*limited.section("sample"), "data"); }, "E_MEMBER_TOO_LARGE"), "member limit before allocation");
    limits = {};
    limits.max_ratio = 2;
    limits.ratio_exempt_bytes = 1024;
    auto ratio_limited = qvf::Reader::from_bytes(archive(root, data, meta, qvf::container::Method::Deflate), limits);
    CHECK(throws([&] { ratio_limited.tensor(*ratio_limited.section("sample"), "data"); }, "E_COMPRESSION_RATIO"), "compression ratio cap before decoding");
    const Bytes large_meta = text_bytes("{\"value\":\"" + std::string(4096, 'x') + "\"}");
    limits = {};
    limits.max_json_bytes = 1024;
    auto json_limited = qvf::Reader::from_bytes(archive(manifest(data, large_meta), data, large_meta), limits);
    CHECK(throws([&] { json_limited.json(*json_limited.section("sample"), "meta"); }, "E_JSON_TOO_LARGE"), "JSON-specific cap before allocation");
    const Bytes invalid_meta = {'{', '\"', 'v', '\"', ':', '\"', 0xff, '\"', '}'};
    auto invalid_utf8 = qvf::Reader::from_bytes(archive(manifest(data, invalid_meta), data, invalid_meta));
    CHECK(throws([&] { invalid_utf8.json(*invalid_utf8.section("sample"), "meta"); }, "E_JSON_INVALID"), "JSON UTF-8 is validated");
    limits = {};
    limits.max_total_bytes = 1;
    CHECK(throws([&] { qvf::Reader::from_bytes(archive(root, data, meta), limits); }, "E_TOTAL_TOO_LARGE"), "total archive limit");

    const Json wrong_size = with_data_spec(root, [](Json& spec) { spec.set("size", 4095); });
    auto size_reader = qvf::Reader::from_bytes(archive(wrong_size, data, meta));
    delivered = 0;
    CHECK(throws([&] { size_reader.tensor_into(*size_reader.section("sample"), "data", [&](const uint8_t*, size_t n) { delivered += n; }); }, "E_BINARY_SIZE") && delivered == 0, "declared size rejected before callback");
    const Json overflow = with_data_spec(root, [](Json& spec) {
        spec.set("shape", array({Json(std::numeric_limits<long long>::max()), Json(8)}));
    });
    auto huge = qvf::Reader::from_bytes(archive(overflow, data, meta));
    CHECK(throws([&] { huge.tensor(*huge.section("sample"), "data"); }, "E_BINARY_SIZE"), "shape overflow rejected before allocation");
    CHECK(throws([&] { reader.json(*section, "data"); }, "E_MEMBER_MALFORMED"), "JSON access refuses binary");
    CHECK(throws([&] { reader.tensor(*section, "meta"); }, "E_DTYPE"), "tensor access refuses JSON");
}

void stage_boundaries(const std::filesystem::path& negative) {
    if (!std::filesystem::exists(negative)) return;
    qvf::ValidationOptions options;
    options.schema_check = false;  // isolate semantic/reference stages
    const auto periodic = (negative / "structure_periodicity.qvf").string();
    CHECK(!has(qvf::validate::run_file(periodic, Level::Payloads, {}, options), "E_STRUCTURE_PERIODICITY"), "payload stage excludes semantic checks");
    CHECK(has(qvf::validate::run_file(periodic, Level::Semantics, {}, options), "E_STRUCTURE_PERIODICITY"), "semantic stage includes structure consistency");
    const auto reference = (negative / "ref_unresolved.qvf").string();
    CHECK(!has(qvf::validate::run_file(reference, Level::Semantics, {}, options), "E_REF_UNRESOLVED"), "semantic stage excludes reference findings");
    CHECK(has(qvf::validate::run_file(reference, Level::References, {}, options), "E_REF_UNRESOLVED"), "reference stage resolves section ids");
    const auto bad_manifest = (negative / "manifest_json_invalid.qvf").string();
    CHECK(!has(qvf::validate::run_file(bad_manifest, Level::Container), "E_MANIFEST_JSON"), "container stage leaves manifest bytes unread");
    CHECK(has(qvf::validate::run_file(bad_manifest, Level::Manifest), "E_MANIFEST_JSON"), "manifest stage decodes manifest");
    for (const char* name : {"sha256_mismatch.qvf", "structure_periodicity.qvf", "ref_unresolved.qvf", "manifest_json_invalid.qvf", "not_a_zip.qvf", "binary_size.qvf", "crc_mismatch_stored.qvf", "byte_order_big.qvf"}) {
        const auto path = (negative / name).string();
        const auto old = qvf::QvfReader::validate_file(path);
        const auto current = qvf::validate::run_file(path);
        bool same = old.size() == current.findings.size();
        for (size_t i = 0; same && i < old.size(); ++i)
            same = old[i].code == current.findings[i].code && old[i].where == current.findings[i].where && old[i].severity == current.findings[i].severity;
        CHECK(same, std::string("full-validation finding parity: ") + name);
    }
}
}  // namespace

int main(int argc, char** argv) {
    try {
        access_and_streaming();
        lazy_integrity_and_limits();
        if (argc > 1) stage_boundaries(argv[1]);
        CHECK(has(qvf::validate::run_bytes({1, 2, 3}), "E_ZIP_UNREADABLE"), "unreadable container report");
    } catch (const std::exception& e) {
        std::cerr << "unexpected exception: " << e.what() << "\n";
        return 1;
    }
    std::cout << (failures ? "FAIL" : "PASS") << ": Reader facade and validation stages\n";
    return failures ? 1 : 0;
}
