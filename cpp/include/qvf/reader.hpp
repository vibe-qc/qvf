// qvf/reader.hpp — lazy reader with the lossless typed manifest model.
// License: Apache-2.0.
#ifndef QVF_READER_HPP
#define QVF_READER_HPP

#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "qvf/qvf.hpp"
#include "qvf/validation.hpp"

namespace qvf {

// A borrowed chunk (at most 1 MiB) of little-endian, C-contiguous bytes. A chunk
// need not end at an element boundary. The pointer is valid during the call
// only. CRC-32/SHA-256 failures can follow delivery: discard received data
// when tensor_into throws. Callback exceptions propagate unchanged.
using TensorSink = std::function<void(const uint8_t*, size_t)>;

class Reader {
public:
    // Reads the central directory and current manifest only. Payload members
    // stay unread until requested; open() retains the file handle, and
    // from_bytes() takes ownership without copying the archive.
    static Reader open(const std::string& path, Limits limits = {});
    static Reader from_bytes(std::vector<uint8_t> archive, Limits limits = {});
    Reader(Reader&&) noexcept;
    Reader& operator=(Reader&&) noexcept;
    ~Reader();

    const Manifest& manifest() const;
    // Exact parsed JSON, including fields kept in the typed model's extra.
    const Json& manifest_json() const;
    std::vector<const Section*> sections_of(std::string_view kind) const;
    const Section* section(std::string_view id) const;

    Json json(const Section&, std::string_view role, bool verify = true) const;
    Tensor tensor(const Section&, std::string_view role, bool verify = true) const;
    void tensor_into(const Section&, std::string_view role, const TensorSink&,
                     bool verify = true) const;
    // Entry size checked against declared size and configured limits; no read.
    uint64_t member_size(const Section&, std::string_view role) const;
    // Raw member streaming, including opaque bytes; same integrity contract.
    void bytes_into(const Section&, std::string_view role, const TensorSink&,
                    bool verify = true) const;
    // Escape hatch for opaque members (logs, inputs, images, vendor bytes).
    std::vector<uint8_t> bytes(const Section&, std::string_view role,
                               bool verify = true) const;

    // The kind's own from_section implementation performs typed decoding and
    // rejects the wrong kind. This protocol does not erase a canonical kind
    // to a generic JSON wrapper; custom kinds can implement the same API.
    template <class K> K get(std::string_view id) const {
        const Section* s = section(id);
        if (!s) throw std::runtime_error("E_REF_UNRESOLVED: section not found: " +
                                         std::string(id));
        return K::from_section(*this, *s);
    }

    validate::Report validate(validate::Level level = validate::Level::All,
                              const ValidationOptions& options = {}) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    explicit Reader(std::unique_ptr<Impl>);
};

}  // namespace qvf
#endif  // QVF_READER_HPP
