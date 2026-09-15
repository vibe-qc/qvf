// qvf_zip.hpp — a minimal, original ZIP archive writer.
//
// Header-only, inline, dependency-free. Emits a valid PKZIP archive. Each
// member is DEFLATE-compressed (method 8) when that is smaller than the raw
// bytes, else STORE-d (method 0) — both decompressible by any unzip. The
// DEFLATE codec is the original implementation in qvf_deflate.hpp.
//
// Only what QVF needs: no encryption, no zip64 (QVF caps members at 8 GiB and
// archives well under 4 GiB in practice), no directory entries. License:
// Apache-2.0.
#ifndef QVF_ZIP_HPP
#define QVF_ZIP_HPP

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "qvf_deflate.hpp"

namespace qvf {
namespace detail {

inline uint32_t crc32_of(const uint8_t* data, size_t n) {
    static uint32_t table[256];
    static bool init = false;
    if (!init) {
        for (uint32_t i = 0; i < 256; ++i) {
            uint32_t c = i;
            for (int k = 0; k < 8; ++k)
                c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
            table[i] = c;
        }
        init = true;
    }
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; ++i)
        c = table[(c ^ data[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

class ZipWriter {
public:
    // Add a member. DEFLATE-compressed when that is smaller than STORE.
    // `compress = false` forces STORE (used for manifest.json).
    void add(const std::string& name, const uint8_t* data, size_t n,
             bool compress = true) {
        Entry e;
        e.name = name;
        e.crc = crc32_of(data, n);
        e.usize = static_cast<uint32_t>(n);
        e.offset = static_cast<uint32_t>(out_.size());

        std::vector<uint8_t> deflated;
        const uint8_t* body = data;
        uint32_t csize = static_cast<uint32_t>(n);
        e.method = 0;  // STORE
        if (compress && n > 0) {
            deflated = deflate(data, n);
            if (deflated.size() < n) {
                e.method = 8;  // DEFLATE
                body = deflated.data();
                csize = static_cast<uint32_t>(deflated.size());
            }
        }
        e.csize = csize;

        put16(0x04034b50 & 0xFFFF); put16(0x04034b50 >> 16);  // local sig (LE)
        put16(20);              // version needed
        put16(0);               // flags
        put16(e.method);        // compression method
        put16(0); put16(0);     // mod time, mod date (fixed / zeroed)
        put32(e.crc);
        put32(e.csize);         // compressed size
        put32(e.usize);         // uncompressed size
        put16(static_cast<uint16_t>(name.size()));
        put16(0);               // extra len
        out_.insert(out_.end(), name.begin(), name.end());
        out_.insert(out_.end(), body, body + csize);
        entries_.push_back(std::move(e));
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
        uint32_t cd_start = static_cast<uint32_t>(out_.size());
        for (const auto& e : entries_) {
            put16(0x02014b50 & 0xFFFF); put16(0x02014b50 >> 16);  // central sig
            put16(20);          // version made by
            put16(20);          // version needed
            put16(0);           // flags
            put16(e.method);    // compression method
            put16(0); put16(0); // time, date
            put32(e.crc);
            put32(e.csize);     // compressed size
            put32(e.usize);     // uncompressed size
            put16(static_cast<uint16_t>(e.name.size()));
            put16(0);           // extra
            put16(0);           // comment
            put16(0);           // disk number
            put16(0);           // internal attrs
            put32(0);           // external attrs
            put32(e.offset);
            out_.insert(out_.end(), e.name.begin(), e.name.end());
        }
        uint32_t cd_size = static_cast<uint32_t>(out_.size()) - cd_start;
        put16(0x06054b50 & 0xFFFF); put16(0x06054b50 >> 16);  // end sig
        put16(0); put16(0);     // disk numbers
        put16(static_cast<uint16_t>(entries_.size()));
        put16(static_cast<uint16_t>(entries_.size()));
        put32(cd_size);
        put32(cd_start);
        put16(0);               // comment length
        return std::move(out_);
    }

private:
    struct Entry {
        std::string name;
        uint32_t crc = 0;
        uint32_t csize = 0;   // compressed (stored) size
        uint32_t usize = 0;   // uncompressed size
        uint32_t offset = 0;
        uint16_t method = 0;  // 0 = STORE, 8 = DEFLATE
    };

    void put16(uint32_t v) {
        out_.push_back(static_cast<uint8_t>(v & 0xFF));
        out_.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
    }
    void put32(uint32_t v) {
        out_.push_back(static_cast<uint8_t>(v & 0xFF));
        out_.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
        out_.push_back(static_cast<uint8_t>((v >> 16) & 0xFF));
        out_.push_back(static_cast<uint8_t>((v >> 24) & 0xFF));
    }

    std::vector<uint8_t> out_;
    std::vector<Entry> entries_;
};

}  // namespace detail
}  // namespace qvf

#endif  // QVF_ZIP_HPP
