// qvf/qvf_reader.hpp — reference C++ reader for QVF archives.
//
// Completes the round-trip: open a .qvf, parse manifest.json, verify member
// sha256s, and decode JSON / binary members. Zero external dependencies — the
// ZIP reader, INFLATE decompressor, JSON parser, and SHA-256 are all in the
// toolkit. License: Apache-2.0.
#ifndef QVF_QVF_READER_HPP
#define QVF_QVF_READER_HPP

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "qvf/json.hpp"

namespace qvf {

// A decoded binary member: little-endian raw bytes + declared dtype/shape.
struct BinaryMember {
    std::string dtype;            // e.g. "float64", "float32", "int32"
    std::vector<int64_t> shape;
    std::vector<uint8_t> bytes;   // C-contiguous, little-endian

    size_t element_count() const {
        size_t n = 1;
        for (int64_t d : shape) n *= static_cast<size_t>(d);
        return n;
    }
    // Convenience: reinterpret the bytes as a vector<double>. Only valid for
    // float64 members (throws otherwise).
    std::vector<double> as_doubles() const;
};

class QvfReader {
public:
    // Open a .qvf file from disk, or from an in-memory archive.
    static QvfReader open(const std::string& path);
    static QvfReader from_bytes(std::vector<uint8_t> archive);

    QvfReader(QvfReader&&) noexcept;
    QvfReader& operator=(QvfReader&&) noexcept;
    ~QvfReader();

    // The parsed manifest, and its `sections` array.
    const Json& manifest() const;
    const Json& sections() const;

    bool has_section(const std::string& id) const;
    const Json& section(const std::string& id) const;   // throws if missing

    // Read a member (resolved through the manifest by section id + role),
    // verifying its sha256 by default.
    std::vector<uint8_t> read_member_bytes(const std::string& section_id,
                                           const std::string& role,
                                           bool verify = true) const;
    Json read_json_member(const std::string& section_id, const std::string& role,
                          bool verify = true) const;
    BinaryMember read_binary_member(const std::string& section_id,
                                    const std::string& role,
                                    bool verify = true) const;

    // Semantic validation: qvf_version/source, member existence, sha256
    // integrity, binary byte-size == itemsize*prod(shape). Returns true if
    // clean; otherwise appends messages to `errors`.
    bool validate(std::vector<std::string>& errors) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    explicit QvfReader(std::unique_ptr<Impl> impl);
};

}  // namespace qvf

#endif  // QVF_QVF_READER_HPP
