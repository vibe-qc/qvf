// qvf_reader.cpp — implementation of the QVF C++ reader. License: Apache-2.0.
#include "qvf/qvf_reader.hpp"

#include <cstring>
#include <fstream>
#include <stdexcept>

#include "qvf_sha256.hpp"
#include "qvf_unzip.hpp"

namespace qvf {

static size_t dtype_itemsize(const std::string& d) {
    if (d == "int8" || d == "uint8") return 1;
    if (d == "int16" || d == "uint16") return 2;
    if (d == "int32" || d == "uint32" || d == "float32") return 4;
    if (d == "int64" || d == "uint64" || d == "float64") return 8;
    return 0;
}

struct QvfReader::Impl {
    detail::ZipReader zip;
    Json manifest;
    explicit Impl(std::vector<uint8_t> bytes) : zip(std::move(bytes)) {
        std::vector<uint8_t> mf = zip.read("manifest.json");
        manifest = Json::parse(std::string(mf.begin(), mf.end()));
    }

    const Json& member_spec(const std::string& sid, const std::string& role) const {
        const Json& secs = manifest.at("sections");
        for (size_t i = 0; i < secs.size(); ++i) {
            const Json& s = secs.at(i);
            if (s.contains("id") && s.at("id").as_string() == sid) {
                const Json& members = s.at("members");
                if (!members.contains(role))
                    throw std::runtime_error("section '" + sid +
                                             "' has no member '" + role + "'");
                return members.at(role);
            }
        }
        throw std::runtime_error("section id not found: " + sid);
    }

    std::vector<uint8_t> read_spec(const Json& spec, bool verify) const {
        std::vector<uint8_t> bytes = zip.read(spec.at("path").as_string());
        if (verify && spec.contains("sha256")) {
            std::string got = detail::Sha256::hex_of(bytes);
            if (got != spec.at("sha256").as_string())
                throw std::runtime_error("sha256 mismatch for " +
                                         spec.at("path").as_string());
        }
        return bytes;
    }
};

std::vector<double> BinaryMember::as_doubles() const {
    if (dtype != "float64")
        throw std::runtime_error("BinaryMember::as_doubles: dtype is " + dtype);
    std::vector<double> out(element_count());
    if (bytes.size() != out.size() * 8)
        throw std::runtime_error("BinaryMember::as_doubles: size mismatch");
    for (size_t i = 0; i < out.size(); ++i) {
        uint64_t bits = 0;
        for (int b = 0; b < 8; ++b)
            bits |= static_cast<uint64_t>(bytes[i * 8 + b]) << (8 * b);
        std::memcpy(&out[i], &bits, 8);  // little-endian host assumed (spec § 2.2)
    }
    return out;
}

QvfReader::QvfReader(std::unique_ptr<Impl> impl) : impl_(std::move(impl)) {}
QvfReader::QvfReader(QvfReader&&) noexcept = default;
QvfReader& QvfReader::operator=(QvfReader&&) noexcept = default;
QvfReader::~QvfReader() = default;

QvfReader QvfReader::from_bytes(std::vector<uint8_t> archive) {
    return QvfReader(std::unique_ptr<Impl>(new Impl(std::move(archive))));
}

QvfReader QvfReader::open(const std::string& path) {
    std::ifstream fh(path, std::ios::binary);
    if (!fh) throw std::runtime_error("cannot open: " + path);
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(fh)),
                               std::istreambuf_iterator<char>());
    return from_bytes(std::move(bytes));
}

const Json& QvfReader::manifest() const { return impl_->manifest; }
const Json& QvfReader::sections() const { return impl_->manifest.at("sections"); }

bool QvfReader::has_section(const std::string& id) const {
    const Json& secs = sections();
    for (size_t i = 0; i < secs.size(); ++i)
        if (secs.at(i).contains("id") && secs.at(i).at("id").as_string() == id)
            return true;
    return false;
}

const Json& QvfReader::section(const std::string& id) const {
    const Json& secs = sections();
    for (size_t i = 0; i < secs.size(); ++i)
        if (secs.at(i).contains("id") && secs.at(i).at("id").as_string() == id)
            return secs.at(i);
    throw std::runtime_error("section id not found: " + id);
}

std::vector<uint8_t> QvfReader::read_member_bytes(const std::string& sid,
                                                  const std::string& role,
                                                  bool verify) const {
    return impl_->read_spec(impl_->member_spec(sid, role), verify);
}

Json QvfReader::read_json_member(const std::string& sid, const std::string& role,
                                 bool verify) const {
    std::vector<uint8_t> b = read_member_bytes(sid, role, verify);
    return Json::parse(std::string(b.begin(), b.end()));
}

BinaryMember QvfReader::read_binary_member(const std::string& sid,
                                           const std::string& role,
                                           bool verify) const {
    const Json& spec = impl_->member_spec(sid, role);
    BinaryMember bm;
    if (spec.contains("dtype")) bm.dtype = spec.at("dtype").as_string();
    if (spec.contains("shape")) {
        const Json& sh = spec.at("shape");
        for (size_t i = 0; i < sh.size(); ++i)
            bm.shape.push_back(sh.at(i).as_int());
    }
    bm.bytes = impl_->read_spec(spec, verify);
    return bm;
}

bool QvfReader::validate(std::vector<std::string>& errors) const {
    const Json& m = impl_->manifest;
    if (!m.contains("qvf_version") || m.at("qvf_version").as_int() != 1)
        errors.push_back("qvf_version must be 1");
    if (!m.contains("source"))
        errors.push_back("missing source");
    if (!m.contains("sections")) {
        errors.push_back("missing sections");
        return errors.empty();
    }
    const Json& secs = m.at("sections");
    for (size_t i = 0; i < secs.size(); ++i) {
        const Json& s = secs.at(i);
        std::string sid = s.contains("id") ? s.at("id").as_string() : "<no-id>";
        if (!s.contains("members")) continue;
        const Json& members = s.at("members");
        for (const auto& kv : members.items()) {
            const Json& spec = kv.second;
            std::string path = spec.contains("path") ? spec.at("path").as_string()
                                                     : "";
            std::vector<uint8_t> bytes;
            try {
                bytes = impl_->read_spec(spec, /*verify=*/true);
            } catch (const std::exception& e) {
                errors.push_back("section '" + sid + "' member '" + kv.first +
                                 "': " + e.what());
                continue;
            }
            if (spec.contains("format") &&
                spec.at("format").as_string() == "binary" && spec.contains("dtype")) {
                size_t itemsize = dtype_itemsize(spec.at("dtype").as_string());
                size_t n = 1;
                if (spec.contains("shape")) {
                    const Json& sh = spec.at("shape");
                    for (size_t k = 0; k < sh.size(); ++k)
                        n *= static_cast<size_t>(sh.at(k).as_int());
                }
                if (itemsize && bytes.size() != itemsize * n)
                    errors.push_back("section '" + sid + "' member '" + kv.first +
                                     "': byte length != itemsize*prod(shape)");
            }
        }
    }
    return errors.empty();
}

}  // namespace qvf
