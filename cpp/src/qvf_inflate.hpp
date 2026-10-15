// qvf_inflate.hpp — an original, dependency-free DEFLATE decompressor (RFC 1951).
//
// Handles all three block types (stored, fixed-Huffman, dynamic-Huffman), so it
// decodes archives written by any conforming deflate (zlib, miniz, Python
// zipfile), not just this toolkit's fixed-Huffman writer. Canonical-Huffman
// decode via the classic count/symbol tables (à la zlib's puff, reimplemented).
//
// Two forms share one decoder:
//   * inflate(): the whole compressed stream in memory, the whole output
//     returned as one vector;
//   * InflateBitReader with a refill callback plus InflateWindow with a sink:
//     input is pulled in chunks and output is pushed to the sink in chunks,
//     keeping only the 32 KiB window back-references need (streaming).
// Either way the output never exceeds the caller's bound: a stream that would
// inflate past it is abandoned at once.
//
// Header-only, inline. License: Apache-2.0.
#ifndef QVF_INFLATE_HPP
#define QVF_INFLATE_HPP

#include <cstddef>
#include <cstdint>
#include <functional>
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
    // Supplies the next chunk of compressed input: sets `p` and returns its
    // length, or 0 at the end of the input.
    using Refill = std::function<size_t(const uint8_t*& p)>;

    InflateBitReader(const uint8_t* p, size_t n, Refill refill = Refill())
        : p_(p), n_(n), refill_(std::move(refill)) {}

    int bit() {
        if (bitcnt_ == 0) {
            cur_ = next_byte();
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
    uint8_t byte() { return next_byte(); }

private:
    uint8_t next_byte() {
        while (pos_ >= n_) {
            const uint8_t* q = nullptr;
            const size_t m = refill_ ? refill_(q) : 0;
            if (m == 0 || q == nullptr) throw std::runtime_error("inflate: out of input");
            p_ = q;
            n_ = m;
            pos_ = 0;
        }
        return p_[pos_++];
    }

    const uint8_t* p_;
    size_t n_;
    size_t pos_ = 0;
    Refill refill_;
    uint8_t cur_ = 0;
    int bitcnt_ = 0;
};

// Thrown when a stream inflates past the caller's output bound (a ZIP entry
// whose data expands beyond its declared uncompressed size).
[[noreturn]] inline void inflate_overflow() {
    throw std::runtime_error("inflate: output exceeds the declared size");
}

// The decoder's output: the bytes produced so far, of which at least the last
// 32 KiB (the DEFLATE window) are kept. Without a sink everything is kept and
// take() returns it; with a sink, bytes are handed over in chunks of about
// 1 MiB and dropped once they leave the window.
class InflateWindow {
public:
    using Sink = std::function<void(const uint8_t*, size_t)>;

    InflateWindow(uint64_t max_out, Sink sink = Sink(), size_t reserve = 0)
        : max_out_(max_out), sink_(std::move(sink)) {
        if (sink_) reserve = kFlushAt;
        if (reserve) buf_.reserve(reserve);
    }

    void put(uint8_t b) {
        if (total_ >= max_out_) inflate_overflow();
        buf_.push_back(b);
        ++total_;
    }
    void copy(size_t distance, size_t length) {
        if (distance > buf_.size()) throw std::runtime_error("inflate: distance too far back");
        if (static_cast<uint64_t>(length) > max_out_ - total_) inflate_overflow();
        const size_t start = buf_.size() - distance;
        for (size_t i = 0; i < length; ++i) {
            const uint8_t b = buf_[start + i];
            buf_.push_back(b);
        }
        total_ += length;
    }
    void maybe_flush() {
        if (sink_ && buf_.size() >= kFlushAt) {
            sink_(buf_.data() + delivered_, buf_.size() - delivered_);
            buf_.erase(buf_.begin(),
                       buf_.begin() + static_cast<std::ptrdiff_t>(buf_.size() - kWindow));
            delivered_ = buf_.size();
        }
    }
    void finish() {
        if (sink_ && buf_.size() > delivered_) {
            sink_(buf_.data() + delivered_, buf_.size() - delivered_);
            delivered_ = buf_.size();
        }
    }
    uint64_t total() const { return total_; }
    std::vector<uint8_t> take() { return std::move(buf_); }

private:
    static constexpr size_t kWindow = 32768;
    static constexpr size_t kFlushAt = (size_t(1) << 20) + kWindow;
    std::vector<uint8_t> buf_;
    size_t delivered_ = 0;   // buf_[0, delivered_) already handed to the sink
    uint64_t total_ = 0;
    uint64_t max_out_;
    Sink sink_;
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
            if (lengths[sym])
                symbols[static_cast<size_t>(offs[lengths[sym]]++)] = static_cast<int>(sym);
    }

    int decode(InflateBitReader& br) const {
        int code = 0, first = 0, index = 0;
        for (int len = 1; len <= 15; ++len) {
            code |= br.bit();
            int count = counts[len];
            if (code - first < count)
                return symbols[static_cast<size_t>(index + (code - first))];
            index += count;
            first += count;
            first <<= 1;
            code <<= 1;
        }
        throw std::runtime_error("inflate: invalid Huffman code");
    }
};

inline void inflate_block_codes(InflateBitReader& br, InflateWindow& out,
                                const HuffTable& lit, const HuffTable& dist) {
    while (true) {
        int sym = lit.decode(br);
        if (sym == 256) return;  // end of block
        if (sym < 256) {
            out.put(static_cast<uint8_t>(sym));
            out.maybe_flush();
            continue;
        }
        sym -= 257;
        if (sym >= 29) throw std::runtime_error("inflate: bad length symbol");
        int length = kInfLenBase[sym] + static_cast<int>(br.bits(kInfLenExtra[sym]));
        int dsym = dist.decode(br);
        if (dsym >= 30) throw std::runtime_error("inflate: bad distance symbol");
        int distance =
            kInfDistBase[dsym] + static_cast<int>(br.bits(kInfDistExtra[dsym]));
        out.copy(static_cast<size_t>(distance), static_cast<size_t>(length));
        out.maybe_flush();
    }
}

struct FixedHuffTables {
    HuffTable lit, dist;
    FixedHuffTables() {
        std::vector<int> ll(288);
        for (size_t i = 0; i < 144; ++i) ll[i] = 8;
        for (size_t i = 144; i < 256; ++i) ll[i] = 9;
        for (size_t i = 256; i < 280; ++i) ll[i] = 7;
        for (size_t i = 280; i < 288; ++i) ll[i] = 8;
        lit.construct(ll);
        dist.construct(std::vector<int>(30, 5));
    }
};

inline const FixedHuffTables& fixed_huff_tables() {
    static const FixedHuffTables tables;
    return tables;
}

inline void build_dynamic(InflateBitReader& br, HuffTable& lit, HuffTable& dist) {
    int hlit = static_cast<int>(br.bits(5)) + 257;
    int hdist = static_cast<int>(br.bits(5)) + 1;
    int hclen = static_cast<int>(br.bits(4)) + 4;
    // As zlib: at most 286 literal/length and 30 distance codes.
    if (hlit > 286 || hdist > 30)
        throw std::runtime_error("inflate: too many length or distance codes");
    static const int order[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5,
                                  11, 4, 12, 3, 13, 2, 14, 1, 15};
    std::vector<int> cl(19, 0);
    for (int i = 0; i < hclen; ++i)
        cl[static_cast<size_t>(order[i])] = static_cast<int>(br.bits(3));
    HuffTable clh;
    clh.construct(cl);

    const size_t total = static_cast<size_t>(hlit + hdist);
    std::vector<int> lengths;
    lengths.reserve(total);
    while (lengths.size() < total) {
        int sym = clh.decode(br);
        if (sym < 16) {
            lengths.push_back(sym);
            continue;
        }
        int value = 0, rep = 0;
        if (sym == 16) {
            if (lengths.empty()) throw std::runtime_error("inflate: bad repeat");
            value = lengths.back();
            rep = 3 + static_cast<int>(br.bits(2));
        } else if (sym == 17) {
            rep = 3 + static_cast<int>(br.bits(3));
        } else {  // 18
            rep = 11 + static_cast<int>(br.bits(7));
        }
        if (lengths.size() + static_cast<size_t>(rep) > total)
            throw std::runtime_error("inflate: bad repeat");
        lengths.insert(lengths.end(), static_cast<size_t>(rep), value);
    }
    if (lengths[256] == 0)
        throw std::runtime_error("inflate: missing end-of-block code");
    lit.construct(std::vector<int>(lengths.begin(), lengths.begin() + hlit));
    dist.construct(std::vector<int>(lengths.begin() + hlit, lengths.end()));
}

// Decode a whole raw DEFLATE stream from `br` into `out` (data after the
// final block is ignored), then hand the rest of the output to the sink.
inline void inflate_stream(InflateBitReader& br, InflateWindow& out) {
    while (true) {
        int bfinal = br.bit();
        int btype = static_cast<int>(br.bits(2));
        if (btype == 0) {
            br.align();
            // Read the LEN and NLEN bytes in order: operand evaluation order
            // of `br.byte() | (br.byte() << 8)` is unspecified in C++.
            const unsigned len_lo = br.byte();
            const unsigned len_hi = br.byte();
            const unsigned nlen_lo = br.byte();
            const unsigned nlen_hi = br.byte();
            const unsigned len = len_lo | (len_hi << 8);
            const unsigned nlen = nlen_lo | (nlen_hi << 8);
            if ((len ^ 0xFFFFu) != nlen)
                throw std::runtime_error("inflate: stored block length check failed");
            for (unsigned i = 0; i < len; ++i) {
                out.put(br.byte());
                out.maybe_flush();
            }
        } else if (btype == 1) {
            const FixedHuffTables& fixed = fixed_huff_tables();
            inflate_block_codes(br, out, fixed.lit, fixed.dist);
        } else if (btype == 2) {
            HuffTable lit, dist;
            build_dynamic(br, lit, dist);
            inflate_block_codes(br, out, lit, dist);
        } else {
            throw std::runtime_error("inflate: reserved block type");
        }
        if (bfinal) break;
    }
    out.finish();
}

// Decompress a raw DEFLATE stream. `size_hint` pre-reserves the output (never
// more than DEFLATE's maximum expansion of the input allows, so a lying hint
// cannot force a huge allocation). Throws if the output would exceed `max_out`.
inline std::vector<uint8_t> inflate(const uint8_t* data, size_t n,
                                    size_t size_hint = 0,
                                    size_t max_out = static_cast<size_t>(-1)) {
    // A DEFLATE stream expands at most ~1032:1 (258-byte matches in 1-bit codes).
    const size_t max_expansion = n > static_cast<size_t>(-1) / 1032 - 64
                                     ? static_cast<size_t>(-1)
                                     : n * 1032 + 64;
    size_t reserve = size_hint < max_expansion ? size_hint : max_expansion;
    if (reserve > max_out) reserve = max_out;
    InflateBitReader br(data, n);
    InflateWindow out(static_cast<uint64_t>(max_out), InflateWindow::Sink(), reserve);
    inflate_stream(br, out);
    return out.take();
}

inline std::vector<uint8_t> inflate(const std::vector<uint8_t>& v,
                                    size_t size_hint = 0) {
    return inflate(v.data(), v.size(), size_hint);
}

}  // namespace detail
}  // namespace qvf

#endif  // QVF_INFLATE_HPP
