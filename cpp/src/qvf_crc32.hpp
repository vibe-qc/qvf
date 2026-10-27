// qvf_crc32.hpp — CRC-32 (ISO-HDLC, the ZIP checksum), incremental.
//
// Header-only, inline, dependency-free. `Crc32` accumulates a checksum over
// any number of update() calls; crc32_of() is the one-shot form. The lookup
// table is built once, on first use, by a function-local static (thread-safe
// initialisation). License: Apache-2.0.
#ifndef QVF_CRC32_HPP
#define QVF_CRC32_HPP

#include <cstddef>
#include <cstdint>

namespace qvf {
namespace detail {

struct Crc32Table {
    uint32_t entry[256];
    Crc32Table() {
        for (uint32_t i = 0; i < 256; ++i) {
            uint32_t c = i;
            for (int k = 0; k < 8; ++k)
                c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
            entry[i] = c;
        }
    }
};

inline const uint32_t* crc32_table() {
    static const Crc32Table table;
    return table.entry;
}

class Crc32 {
public:
    void update(const uint8_t* data, size_t n) {
        const uint32_t* t = crc32_table();
        uint32_t c = state_;
        for (size_t i = 0; i < n; ++i) c = t[(c ^ data[i]) & 0xFF] ^ (c >> 8);
        state_ = c;
    }
    uint32_t value() const { return state_ ^ 0xFFFFFFFFu; }

private:
    uint32_t state_ = 0xFFFFFFFFu;
};

inline uint32_t crc32_of(const uint8_t* data, size_t n) {
    Crc32 c;
    c.update(data, n);
    return c.value();
}

}  // namespace detail
}  // namespace qvf

#endif  // QVF_CRC32_HPP
