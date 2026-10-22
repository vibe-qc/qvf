// qvf_zip.hpp — the in-memory ZIP writer interface of the original toolkit.
//
// `detail::ZipWriter` keeps the interface the tests and early code use (add
// members, finish() returns the archive bytes) on top of
// qvf::container::ZipWriter (qvf/container.hpp), which does the encoding:
// each member is DEFLATE-compressed (method 8) when that is smaller than the
// raw bytes, else STORE-d (method 0). An archive that needs no ZIP64
// structure is byte-for-byte what this writer has always produced. Unlike
// container::ZipWriter it accepts a repeated name, so tests can build the
// malformed archives validators must reject.
//
// Also re-exports crc32_of() (qvf_crc32.hpp). License: Apache-2.0.
#ifndef QVF_ZIP_HPP
#define QVF_ZIP_HPP

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "qvf/container.hpp"
#include "qvf_crc32.hpp"

namespace qvf {
namespace detail {

class ZipWriter {
public:
    ZipWriter() : sink_(new container::MemorySink), zip_(std::unique_ptr<container::Sink>(sink_)) {
        zip_.allow_duplicate_names();
    }

    // Add a member. DEFLATE-compressed when that is smaller than STORE.
    // `compress = false` forces STORE (used for manifest.json).
    void add(const std::string& name, const uint8_t* data, size_t n,
             bool compress = true) {
        zip_.write(name, data, n,
                   compress ? container::Method::Deflate : container::Method::Store);
    }
    void add(const std::string& name, const std::vector<uint8_t>& v,
             bool compress = true) {
        add(name, v.data(), v.size(), compress);
    }
    void add(const std::string& name, const std::string& s,
             bool compress = true) {
        add(name, reinterpret_cast<const uint8_t*>(s.data()), s.size(), compress);
    }

    // Finalize: append the central directory + end record; return archive bytes.
    std::vector<uint8_t> finish() {
        zip_.finish();
        return sink_->take();
    }

private:
    container::MemorySink* sink_;   // owned by zip_
    container::ZipWriter zip_;
};

}  // namespace detail
}  // namespace qvf

#endif  // QVF_ZIP_HPP
