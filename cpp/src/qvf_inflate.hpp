// qvf_inflate.hpp — an original, dependency-free DEFLATE decompressor (RFC 1951).
//
// Handles all three block types (stored, fixed-Huffman, dynamic-Huffman), so it
// decodes archives written by any conforming deflate (zlib, miniz, Python
// zipfile), not just this toolkit's fixed-Huffman writer. Canonical-Huffman
// decode via the classic count/symbol tables (à la zlib's puff, reimplemented).
//
// Header-only, inline. License: Apache-2.0.
#ifndef QVF_INFLATE_HPP
#define QVF_INFLATE_HPP

#include <cstdint>
#include <stdexcept>
#include <vector>

namespace qvf {
namespace detail {

// Length code (symbol-257) → base + extra bits.
static const int kInfLenBase[29] = {
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
    67, 83, 99, 115, 131, 163, 195, 227, 258};
static const int kInfLenExtra[29] = {
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4,
    5, 5, 5, 5, 0};
static const int kInfDistBase[30] = {
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513,
    769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577};
static const int kInfDistExtra[30] = {
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10,
    11, 11, 12, 12, 13, 13};

class InflateBitReader {
public:
    InflateBitReader(const uint8_t* p, size_t n) : p_(p), n_(n) {}

    int bit() {
        if (bitcnt_ == 0) {
            if (pos_ >= n_) throw std::runtime_error("inflate: out of input");
            cur_ = p_[pos_++];
            bitcnt_ = 8;
        }
        int b = cur_ & 1;
        cur_ >>= 1;
        --bitcnt_;
        return b;
    }
    uint32_t bits(int count) {
        uint32_t v = 0;
        for (int i = 0; i < count; ++i) v |= static_cast<uint32_t>(bit()) << i;
        return v;
    }
    void align() { bitcnt_ = 0; }
    uint8_t byte() {
        if (pos_ >= n_) throw std::runtime_error("inflate: out of input (byte)");
        return p_[pos_++];
    }

private:
    const uint8_t* p_;
    size_t n_;
    size_t pos_ = 0;
    uint8_t cur_ = 0;
    int bitcnt_ = 0;
};

struct HuffTable {
    int counts[16] = {0};       // number of codes of each length
    std::vector<int> symbols;   // symbols sorted by code

    void construct(const std::vector<int>& lengths) {
        for (int i = 0; i < 16; ++i) counts[i] = 0;
        for (int l : lengths) counts[l]++;
        counts[0] = 0;  // length-0 symbols are absent
        int offs[16];
        offs[1] = 0;
        for (int len = 1; len < 15; ++len) offs[len + 1] = offs[len] + counts[len];
        symbols.assign(lengths.size(), 0);
        for (size_t sym = 0; sym < lengths.size(); ++sym)
            if (lengths[sym]) symbols[offs[lengths[sym]]++] = static_cast<int>(sym);
    }

    int decode(InflateBitReader& br) const {
        int code = 0, first = 0, index = 0;
        for (int len = 1; len <= 15; ++len) {
            code |= br.bit();
            int count = counts[len];
            if (code - first < count) return symbols[index + (code - first)];
            index += count;
            first += count;
            first <<= 1;
            code <<= 1;
        }
        throw std::runtime_error("inflate: invalid Huffman code");
    }
};

inline void inflate_block_codes(InflateBitReader& br, std::vector<uint8_t>& out,
                                const HuffTable& lit, const HuffTable& dist) {
    while (true) {
        int sym = lit.decode(br);
        if (sym == 256) return;  // end of block
        if (sym < 256) {
            out.push_back(static_cast<uint8_t>(sym));
            continue;
        }
        sym -= 257;
        if (sym >= 29) throw std::runtime_error("inflate: bad length symbol");
        int length = kInfLenBase[sym] + static_cast<int>(br.bits(kInfLenExtra[sym]));
        int dsym = dist.decode(br);
        if (dsym >= 30) throw std::runtime_error("inflate: bad distance symbol");
        int distance =
            kInfDistBase[dsym] + static_cast<int>(br.bits(kInfDistExtra[dsym]));
        if (static_cast<size_t>(distance) > out.size())
            throw std::runtime_error("inflate: distance too far back");
        size_t start = out.size() - static_cast<size_t>(distance);
        for (int i = 0; i < length; ++i) out.push_back(out[start + i]);
    }
}

inline void build_fixed(HuffTable& lit, HuffTable& dist) {
    std::vector<int> ll(288);
    for (int i = 0; i < 144; ++i) ll[i] = 8;
    for (int i = 144; i < 256; ++i) ll[i] = 9;
    for (int i = 256; i < 280; ++i) ll[i] = 7;
    for (int i = 280; i < 288; ++i) ll[i] = 8;
    lit.construct(ll);
    dist.construct(std::vector<int>(30, 5));
}

inline void build_dynamic(InflateBitReader& br, HuffTable& lit, HuffTable& dist) {
    int hlit = static_cast<int>(br.bits(5)) + 257;
    int hdist = static_cast<int>(br.bits(5)) + 1;
    int hclen = static_cast<int>(br.bits(4)) + 4;
    static const int order[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5,
                                  11, 4, 12, 3, 13, 2, 14, 1, 15};
    std::vector<int> cl(19, 0);
    for (int i = 0; i < hclen; ++i) cl[order[i]] = static_cast<int>(br.bits(3));
    HuffTable clh;
    clh.construct(cl);

    std::vector<int> lengths;
    lengths.reserve(static_cast<size_t>(hlit + hdist));
    while (static_cast<int>(lengths.size()) < hlit + hdist) {
        int sym = clh.decode(br);
        if (sym < 16) {
            lengths.push_back(sym);
        } else if (sym == 16) {
            if (lengths.empty()) throw std::runtime_error("inflate: bad repeat");
            int prev = lengths.back();
            int rep = 3 + static_cast<int>(br.bits(2));
            for (int i = 0; i < rep; ++i) lengths.push_back(prev);
        } else if (sym == 17) {
            int rep = 3 + static_cast<int>(br.bits(3));
            for (int i = 0; i < rep; ++i) lengths.push_back(0);
        } else {  // 18
            int rep = 11 + static_cast<int>(br.bits(7));
            for (int i = 0; i < rep; ++i) lengths.push_back(0);
        }
    }
    lit.construct(std::vector<int>(lengths.begin(), lengths.begin() + hlit));
    dist.construct(std::vector<int>(lengths.begin() + hlit, lengths.end()));
}

// Decompress a raw DEFLATE stream. `size_hint` pre-reserves the output.
inline std::vector<uint8_t> inflate(const uint8_t* data, size_t n,
                                    size_t size_hint = 0) {
    std::vector<uint8_t> out;
    if (size_hint) out.reserve(size_hint);
    InflateBitReader br(data, n);
    while (true) {
        int bfinal = br.bit();
        int btype = static_cast<int>(br.bits(2));
        if (btype == 0) {
            br.align();
            uint16_t len = static_cast<uint16_t>(br.byte() | (br.byte() << 8));
            br.byte();  // NLEN
            br.byte();
            for (int i = 0; i < len; ++i) out.push_back(br.byte());
        } else if (btype == 1) {
            HuffTable lit, dist;
            build_fixed(lit, dist);
            inflate_block_codes(br, out, lit, dist);
        } else if (btype == 2) {
            HuffTable lit, dist;
            build_dynamic(br, lit, dist);
            inflate_block_codes(br, out, lit, dist);
        } else {
            throw std::runtime_error("inflate: reserved block type");
        }
        if (bfinal) break;
    }
    return out;
}

inline std::vector<uint8_t> inflate(const std::vector<uint8_t>& v,
                                    size_t size_hint = 0) {
    return inflate(v.data(), v.size(), size_hint);
}

}  // namespace detail
}  // namespace qvf

#endif  // QVF_INFLATE_HPP
