// qvf_unzip.hpp — a minimal, original ZIP archive reader.
//
// Parses the central directory and extracts members by name, decompressing
// STORE (method 0) and DEFLATE (method 8, via qvf_inflate.hpp). No zip64, no
// encryption — matching what the QVF writer produces and what real .qvf files
// use. Header-only, inline. License: Apache-2.0.
#ifndef QVF_UNZIP_HPP
#define QVF_UNZIP_HPP

#include <cstdint>
#include <cstring>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

#include "qvf_inflate.hpp"

namespace qvf {
namespace detail {

class ZipReader {
public:
    explicit ZipReader(std::vector<uint8_t> bytes) : buf_(std::move(bytes)) {
        parse_central_directory();
    }

    bool has(const std::string& name) const {
        return entries_.find(name) != entries_.end();
    }

    std::vector<std::string> names() const {
        std::vector<std::string> out;
        out.reserve(entries_.size());
        for (const auto& kv : entries_) out.push_back(kv.first);
        return out;
    }

    // Return the uncompressed bytes of a member.
    std::vector<uint8_t> read(const std::string& name) const {
        auto it = entries_.find(name);
        if (it == entries_.end())
            throw std::runtime_error("zip: member not found: " + name);
        const Entry& e = it->second;
        // Local header: sig(4) ver(2) flags(2) method(2) time(2) date(2)
        // crc(4) csize(4) usize(4) namelen(2) extralen(2) -> 30 bytes fixed.
        if (e.local_offset + 30 > buf_.size())
            throw std::runtime_error("zip: truncated local header");
        if (rd32(e.local_offset) != 0x04034b50u)
            throw std::runtime_error("zip: bad local header signature");
        uint16_t namelen = rd16(e.local_offset + 26);
        uint16_t extralen = rd16(e.local_offset + 28);
        size_t data_off = e.local_offset + 30 + namelen + extralen;
        if (data_off + e.csize > buf_.size())
            throw std::runtime_error("zip: truncated member data");
        const uint8_t* data = buf_.data() + data_off;
        if (e.method == 0) {
            return std::vector<uint8_t>(data, data + e.csize);
        }
        if (e.method == 8) {
            return inflate(data, e.csize, e.usize);
        }
        throw std::runtime_error("zip: unsupported compression method");
    }

private:
    struct Entry {
        uint16_t method = 0;
        uint32_t csize = 0;
        uint32_t usize = 0;
        uint32_t local_offset = 0;
    };

    uint16_t rd16(size_t o) const {
        return static_cast<uint16_t>(buf_[o] | (buf_[o + 1] << 8));
    }
    uint32_t rd32(size_t o) const {
        return static_cast<uint32_t>(buf_[o]) |
               (static_cast<uint32_t>(buf_[o + 1]) << 8) |
               (static_cast<uint32_t>(buf_[o + 2]) << 16) |
               (static_cast<uint32_t>(buf_[o + 3]) << 24);
    }

    void parse_central_directory() {
        if (buf_.size() < 22) throw std::runtime_error("zip: too small");
        // Find the End Of Central Directory record by scanning backwards.
        size_t eocd = 0;
        bool found = false;
        size_t max_back = buf_.size() < 65557 ? buf_.size() : 65557;
        for (size_t i = 0; i <= max_back - 22; ++i) {
            size_t p = buf_.size() - 22 - i;
            if (rd32(p) == 0x06054b50u) { eocd = p; found = true; break; }
        }
        if (!found) throw std::runtime_error("zip: no end-of-central-directory");
        uint16_t total = rd16(eocd + 10);
        uint32_t cd_size = rd32(eocd + 12);
        uint32_t cd_off = rd32(eocd + 16);
        if (static_cast<size_t>(cd_off) + cd_size > buf_.size())
            throw std::runtime_error("zip: central directory out of range");

        size_t p = cd_off;
        for (uint16_t i = 0; i < total; ++i) {
            if (p + 46 > buf_.size() || rd32(p) != 0x02014b50u)
                throw std::runtime_error("zip: bad central directory entry");
            Entry e;
            e.method = rd16(p + 10);
            e.csize = rd32(p + 20);
            e.usize = rd32(p + 24);
            uint16_t namelen = rd16(p + 28);
            uint16_t extralen = rd16(p + 30);
            uint16_t commentlen = rd16(p + 32);
            e.local_offset = rd32(p + 42);
            std::string name(reinterpret_cast<const char*>(buf_.data() + p + 46),
                             namelen);
            entries_[name] = e;
            p += 46u + namelen + extralen + commentlen;
        }
    }

    std::vector<uint8_t> buf_;
    std::map<std::string, Entry> entries_;
};

}  // namespace detail
}  // namespace qvf

#endif  // QVF_UNZIP_HPP
