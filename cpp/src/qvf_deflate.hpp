// qvf_deflate.hpp — an original, dependency-free DEFLATE compressor (RFC 1951).
//
// LZ77 (hash-chain match finder) + a single fixed-Huffman block. Output is a
// raw DEFLATE stream (no zlib/gzip wrapper), suitable for ZIP method 8. Not the
// tightest possible ratio (fixed Huffman, greedy matching), but standards-clean
// and decompressible by any inflate (zlib, unzip, Python zipfile).
//
// Header-only, inline. License: Apache-2.0.
#ifndef QVF_DEFLATE_HPP
#define QVF_DEFLATE_HPP

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <vector>

namespace qvf {
namespace detail {

// -- fixed length / distance code tables (RFC 1951 §3.2.5) ------------------

// Length code i (0..28) → base length and extra bits; code number is 257+i.
static const int kLenBase[29] = {
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
    67, 83, 99, 115, 131, 163, 195, 227, 258};
static const int kLenExtra[29] = {
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4,
    5, 5, 5, 5, 0};

// Distance code i (0..29) → base distance and extra bits.
static const int kDistBase[30] = {
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513,
    769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577};
static const int kDistExtra[30] = {
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10,
    11, 11, 12, 12, 13, 13};

// LSB-first bit sink. Huffman codes are supplied MSB-first and bit-reversed here.
class BitWriter {
public:
    explicit BitWriter(std::vector<uint8_t>& out) : out_(out) {}

    void bits(uint32_t value, int n) {
        buf_ |= (static_cast<uint64_t>(value) << count_);
        count_ += n;
        while (count_ >= 8) {
            out_.push_back(static_cast<uint8_t>(buf_ & 0xFF));
            buf_ >>= 8;
            count_ -= 8;
        }
    }
    // Emit a Huffman code given MSB-first; reversed into the LSB-first stream.
    void huff(uint32_t code, int len) {
        uint32_t rev = 0;
        for (int i = 0; i < len; ++i) {
            rev = (rev << 1) | (code & 1u);
            code >>= 1;
        }
        bits(rev, len);
    }
    void flush() {
        if (count_ > 0) {
            out_.push_back(static_cast<uint8_t>(buf_ & 0xFF));
            buf_ = 0;
            count_ = 0;
        }
    }

private:
    std::vector<uint8_t>& out_;
    uint64_t buf_ = 0;
    int count_ = 0;
};

// Fixed literal/length Huffman code (RFC 1951 §3.2.6): returns (code, len).
inline void fixed_litlen_code(int sym, uint32_t& code, int& len) {
    if (sym <= 143) { code = 0x30 + sym; len = 8; }
    else if (sym <= 255) { code = 0x190 + (sym - 144); len = 9; }
    else if (sym <= 279) { code = 0x00 + (sym - 256); len = 7; }
    else { code = 0xC0 + (sym - 280); len = 8; }
}

inline int len_code_index(int length) {
    // length in [3,258]; find i with kLenBase[i] <= length < next.
    for (int i = 28; i >= 0; --i)
        if (length >= kLenBase[i]) return i;
    return 0;
}

inline int dist_code_index(int dist) {
    for (int i = 29; i >= 0; --i)
        if (dist >= kDistBase[i]) return i;
    return 0;
}

// Compress `data` into a raw DEFLATE stream.
inline std::vector<uint8_t> deflate(const uint8_t* data, size_t n) {
    std::vector<uint8_t> out;
    out.reserve(n / 2 + 16);
    BitWriter bw(out);

    // Block header: BFINAL=1, BTYPE=01 (fixed Huffman).
    bw.bits(1, 1);
    bw.bits(1, 2);

    auto emit_literal = [&](uint8_t byte) {
        uint32_t code;
        int len;
        fixed_litlen_code(byte, code, len);
        bw.huff(code, len);
    };
    auto emit_match = [&](int length, int dist) {
        int li = len_code_index(length);
        uint32_t code;
        int clen;
        fixed_litlen_code(257 + li, code, clen);
        bw.huff(code, clen);
        if (kLenExtra[li]) bw.bits(length - kLenBase[li], kLenExtra[li]);
        int di = dist_code_index(dist);
        bw.huff(static_cast<uint32_t>(di), 5);  // fixed 5-bit distance code
        if (kDistExtra[di]) bw.bits(dist - kDistBase[di], kDistExtra[di]);
    };

    // LZ77 with a hash-chain match finder.
    constexpr int kMinMatch = 3, kMaxMatch = 258, kWindow = 32768;
    constexpr int kHashBits = 15, kHashSize = 1 << kHashBits;
    constexpr int kMaxChain = 128;  // effort cap per position

    std::vector<int32_t> head(kHashSize, -1);
    std::vector<int32_t> prev(n, -1);

    auto hash3 = [&](size_t p) -> uint32_t {
        uint32_t h = (uint32_t(data[p]) << 16) ^ (uint32_t(data[p + 1]) << 8)
                     ^ uint32_t(data[p + 2]);
        return (h * 2654435761u) >> (32 - kHashBits);
    };

    size_t pos = 0;
    while (pos < n) {
        int best_len = 0, best_dist = 0;
        if (pos + kMinMatch <= n) {
            uint32_t h = hash3(pos);
            int32_t cand = head[h];
            int chain = kMaxChain;
            size_t max_len = std::min<size_t>(kMaxMatch, n - pos);
            while (cand >= 0 && chain-- > 0) {
                size_t d = pos - static_cast<size_t>(cand);
                if (d > kWindow) break;
                // Quick reject on the byte past the current best match.
                if (best_len == 0 ||
                    data[cand + best_len] == data[pos + best_len]) {
                    size_t l = 0;
                    while (l < max_len && data[cand + l] == data[pos + l]) ++l;
                    if (static_cast<int>(l) > best_len) {
                        best_len = static_cast<int>(l);
                        best_dist = static_cast<int>(d);
                        if (l >= max_len) break;
                    }
                }
                cand = prev[cand];
            }
        }

        if (best_len >= kMinMatch) {
            emit_match(best_len, best_dist);
            // Insert hash entries for all covered positions.
            size_t end = pos + static_cast<size_t>(best_len);
            for (; pos + kMinMatch <= n && pos < end; ++pos) {
                uint32_t h = hash3(pos);
                prev[pos] = head[h];
                head[h] = static_cast<int32_t>(pos);
            }
            pos = end;
        } else {
            emit_literal(data[pos]);
            if (pos + kMinMatch <= n) {
                uint32_t h = hash3(pos);
                prev[pos] = head[h];
                head[h] = static_cast<int32_t>(pos);
            }
            ++pos;
        }
    }

    // End of block (symbol 256), then flush partial byte.
    uint32_t eob;
    int eob_len;
    fixed_litlen_code(256, eob, eob_len);
    bw.huff(eob, eob_len);
    bw.flush();
    return out;
}

inline std::vector<uint8_t> deflate(const std::vector<uint8_t>& v) {
    return deflate(v.data(), v.size());
}

}  // namespace detail
}  // namespace qvf

#endif  // QVF_DEFLATE_HPP
