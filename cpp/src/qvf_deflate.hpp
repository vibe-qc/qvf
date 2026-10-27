// qvf_deflate.hpp — an original, dependency-free DEFLATE compressor (RFC 1951).
//
// LZ77 (hash-chain match finder, greedy) with the fixed Huffman code. Output
// is a raw DEFLATE stream (no zlib/gzip wrapper), suitable for ZIP method 8.
// Not the tightest possible ratio, but standards-clean and decompressible by
// any inflate (zlib, unzip, Python zipfile).
//
// `Deflater` compresses incrementally: write() any number of chunks, then
// finish(). Memory is bounded by the 32 KiB window plus the chunk being
// encoded, whatever the total size. It has two framings:
//
//   * SingleBlock (the default, and what deflate() produces): the whole
//     stream is one fixed-Huffman block. The output for a given input does
//     not depend on how the input was split into write() calls, and is the
//     encoding this codec has always produced.
//   * Blocks: the stream is cut into blocks of about 32 KiB of input, and
//     each is emitted with the fixed code or STORED, whichever is smaller, so
//     incompressible data grows by at most 5 bytes per block (the fixed code
//     alone can grow it by up to 12.5 %). The streaming ZIP writer uses this
//     framing, because it cannot fall back to STORE for a whole entry once
//     the entry's bytes are written.
//
// Header-only, inline. License: Apache-2.0.
#ifndef QVF_DEFLATE_HPP
#define QVF_DEFLATE_HPP

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <stdexcept>
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

// Fixed literal/length Huffman code (RFC 1951 §3.2.6): returns (code, len).
inline void fixed_litlen_code(int sym, uint32_t& code, int& len) {
    if (sym <= 143) { code = static_cast<uint32_t>(0x30 + sym); len = 8; }
    else if (sym <= 255) { code = static_cast<uint32_t>(0x190 + (sym - 144)); len = 9; }
    else if (sym <= 279) { code = static_cast<uint32_t>(0x00 + (sym - 256)); len = 7; }
    else { code = static_cast<uint32_t>(0xC0 + (sym - 280)); len = 8; }
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

class Deflater {
public:
    enum class Framing { SingleBlock, Blocks };

    explicit Deflater(Framing framing = Framing::SingleBlock) : framing_(framing) {}

    // Compress `n` more input bytes; compressed bytes are appended to `out`.
    void write(const uint8_t* data, size_t n, std::vector<uint8_t>& out) {
        if (finished_) throw std::logic_error("deflate: write after finish");
        start(out);
        while (n > 0) {
            const size_t take = n < kSlice ? n : kSlice;
            buf_.insert(buf_.end(), data, data + take);
            data += take;
            n -= take;
            encode(false, out);
            compact();
        }
    }

    // Encode the rest of the input and end the stream (byte-aligned).
    void finish(std::vector<uint8_t>& out) {
        if (finished_) return;
        start(out);
        encode(true, out);
        if (framing_ == Framing::SingleBlock)
            emit_end_of_block(out);
        else
            flush_block(true, out);
        if (bitcount_ > 0) {
            out.push_back(static_cast<uint8_t>(bitbuf_ & 0xFF));
            bitbuf_ = 0;
            bitcount_ = 0;
        }
        finished_ = true;
    }

    uint64_t total_in() const { return base_ + buf_.size(); }

private:
    static constexpr int kMinMatch = 3, kMaxMatch = 258;
    static constexpr uint64_t kWindow = 32768, kWindowMask = kWindow - 1;
    static constexpr int kHashBits = 15, kHashSize = 1 << kHashBits;
    static constexpr int kMaxChain = 128;  // effort cap per position
    // A position is encoded only when this much input follows it (or at the
    // end of the stream): every decision then sees the same bytes it would
    // see with the whole input in memory, so the output does not depend on
    // how the input was chunked.
    static constexpr uint64_t kLookahead = kMaxMatch + kMinMatch + 1;
    static constexpr size_t kSlice = size_t(1) << 18;        // input per encode pass
    static constexpr uint64_t kCompactAt = uint64_t(1) << 20; // drop consumed input
    static constexpr uint64_t kBlockInput = 32768;           // Blocks framing

    // -- bit output (LSB first) --
    void bits(uint32_t value, int n, std::vector<uint8_t>& out) {
        bitbuf_ |= static_cast<uint64_t>(value) << bitcount_;
        bitcount_ += n;
        while (bitcount_ >= 8) {
            out.push_back(static_cast<uint8_t>(bitbuf_ & 0xFF));
            bitbuf_ >>= 8;
            bitcount_ -= 8;
        }
    }
    // A Huffman code given MSB-first, reversed into the LSB-first stream.
    void huff(uint32_t code, int len, std::vector<uint8_t>& out) {
        uint32_t rev = 0;
        for (int i = 0; i < len; ++i) {
            rev = (rev << 1) | (code & 1u);
            code >>= 1;
        }
        bits(rev, len, out);
    }

    void start(std::vector<uint8_t>& out) {
        if (started_) return;
        started_ = true;
        // SingleBlock: BFINAL=1, BTYPE=01 (fixed Huffman), once.
        if (framing_ == Framing::SingleBlock) {
            bits(1, 1, out);
            bits(1, 2, out);
        }
    }

    const uint8_t* at(uint64_t p) const { return buf_.data() + (p - base_); }

    uint32_t hash3(uint64_t p) const {
        const uint8_t* d = at(p);
        uint32_t h = (uint32_t(d[0]) << 16) ^ (uint32_t(d[1]) << 8) ^ uint32_t(d[2]);
        return (h * 2654435761u) >> (32 - kHashBits);
    }

    // Hash chains hold position + 1 modulo 2^32 (0 = empty); a candidate's
    // distance is recovered relative to the current position.
    void insert(uint64_t p) {
        if (head_.empty()) head_.assign(kHashSize, 0);
        const size_t slot = static_cast<size_t>(p & kWindowMask);
        if (prev_.size() <= slot)
            prev_.resize(slot + 1 < kWindow ? slot + 1 : static_cast<size_t>(kWindow), 0);
        const uint32_t h = hash3(p);
        prev_[slot] = head_[h];
        head_[h] = static_cast<uint32_t>(p + 1);
    }
    // Distance from pos_ to the position stored as `link`, or 0 for none.
    uint64_t distance_of(uint32_t link) const {
        if (link == 0) return 0;
        const uint32_t d = static_cast<uint32_t>(pos_ + 1) - link;
        if (d == 0 || d > pos_) return 0;
        return d;
    }

    void encode(bool final, std::vector<uint8_t>& out) {
        const uint64_t n = base_ + buf_.size();  // input available
        while (pos_ < n) {
            if (!final && n - pos_ < kLookahead) break;
            int best_len = 0, best_dist = 0;
            if (pos_ + kMinMatch <= n && !head_.empty()) {
                const size_t max_len =
                    static_cast<size_t>(std::min<uint64_t>(kMaxMatch, n - pos_));
                const uint8_t* cur = at(pos_);
                uint64_t d = distance_of(head_[hash3(pos_)]);
                int chain = kMaxChain;
                while (d != 0 && chain-- > 0) {
                    if (d > kWindow) break;
                    const uint64_t cand = pos_ - d;
                    const uint8_t* c = at(cand);
                    // Quick reject on the byte past the current best match.
                    if (best_len == 0 || c[best_len] == cur[best_len]) {
                        size_t l = 0;
                        while (l < max_len && c[l] == cur[l]) ++l;
                        if (static_cast<int>(l) > best_len) {
                            best_len = static_cast<int>(l);
                            best_dist = static_cast<int>(d);
                            if (l >= max_len) break;
                        }
                    }
                    const size_t slot = static_cast<size_t>(cand & kWindowMask);
                    d = slot < prev_.size() ? distance_of(prev_[slot]) : 0;
                }
            }
            if (best_len >= kMinMatch) {
                emit_match(best_len, best_dist, out);
                // Insert hash entries for all covered positions.
                const uint64_t stop = pos_ + static_cast<uint64_t>(best_len);
                for (; pos_ + kMinMatch <= n && pos_ < stop; ++pos_) insert(pos_);
                pos_ = stop;
            } else {
                emit_literal(*at(pos_), out);
                if (pos_ + kMinMatch <= n) insert(pos_);
                ++pos_;
            }
            if (framing_ == Framing::Blocks && pos_ - block_start_ >= kBlockInput)
                flush_block(false, out);
        }
    }

    // Drop input that no future match (and no pending STORED block) can use.
    void compact() {
        uint64_t keep = pos_ > kWindow ? pos_ - kWindow : 0;
        if (framing_ == Framing::Blocks && block_start_ < keep) keep = block_start_;
        if (keep > base_ && keep - base_ >= kCompactAt) {
            buf_.erase(buf_.begin(), buf_.begin() + static_cast<std::ptrdiff_t>(keep - base_));
            base_ = keep;
        }
    }

    static int literal_bits(int byte) { return byte <= 143 ? 8 : 9; }
    static int match_bits(int length, int dist) {
        const int li = len_code_index(length);
        const int di = dist_code_index(dist);
        return (257 + li <= 279 ? 7 : 8) + kLenExtra[li] + 5 + kDistExtra[di];
    }

    void put_literal(int byte, std::vector<uint8_t>& out) {
        uint32_t code;
        int len;
        fixed_litlen_code(byte, code, len);
        huff(code, len, out);
    }
    void put_match(int length, int dist, std::vector<uint8_t>& out) {
        const int li = len_code_index(length);
        uint32_t code;
        int clen;
        fixed_litlen_code(257 + li, code, clen);
        huff(code, clen, out);
        if (kLenExtra[li])
            bits(static_cast<uint32_t>(length - kLenBase[li]), kLenExtra[li], out);
        const int di = dist_code_index(dist);
        huff(static_cast<uint32_t>(di), 5, out);  // fixed 5-bit distance code
        if (kDistExtra[di])
            bits(static_cast<uint32_t>(dist - kDistBase[di]), kDistExtra[di], out);
    }
    void emit_end_of_block(std::vector<uint8_t>& out) {
        uint32_t eob;
        int eob_len;
        fixed_litlen_code(256, eob, eob_len);
        huff(eob, eob_len, out);
    }

    void emit_literal(uint8_t byte, std::vector<uint8_t>& out) {
        if (framing_ == Framing::SingleBlock) {
            put_literal(byte, out);
        } else {
            tokens_.push_back(byte);
            block_bits_ += static_cast<uint64_t>(literal_bits(byte));
        }
    }
    void emit_match(int length, int dist, std::vector<uint8_t>& out) {
        if (framing_ == Framing::SingleBlock) {
            put_match(length, dist, out);
        } else {
            tokens_.push_back(0x80000000u | (static_cast<uint32_t>(length) << 16) |
                              static_cast<uint32_t>(dist));
            block_bits_ += static_cast<uint64_t>(match_bits(length, dist));
        }
    }

    // Blocks framing: emit the input since block_start_ as one block, fixed
    // Huffman or STORED, whichever takes fewer bits.
    void flush_block(bool final, std::vector<uint8_t>& out) {
        const uint64_t len = pos_ - block_start_;   // < 65536 by construction
        const uint64_t fixed_bits = 3 + block_bits_ + 7;
        const uint64_t pad = (8 - (static_cast<uint64_t>(bitcount_) + 3) % 8) % 8;
        const uint64_t stored_bits = 3 + pad + 32 + 8 * len;
        bits(final ? 1u : 0u, 1, out);
        if (stored_bits < fixed_bits) {
            bits(0, 2, out);                         // BTYPE=00 (stored)
            if (bitcount_ > 0) bits(0, 8 - bitcount_, out);
            const uint32_t l16 = static_cast<uint32_t>(len);
            bits(l16 & 0xFFFF, 16, out);
            bits(~l16 & 0xFFFF, 16, out);
            const uint8_t* src = at(block_start_);
            out.insert(out.end(), src, src + static_cast<size_t>(len));
        } else {
            bits(1, 2, out);                         // BTYPE=01 (fixed)
            for (uint32_t t : tokens_) {
                if (t & 0x80000000u)
                    put_match(static_cast<int>((t >> 16) & 0x1FF),
                              static_cast<int>(t & 0xFFFF), out);
                else
                    put_literal(static_cast<int>(t), out);
            }
            emit_end_of_block(out);
        }
        tokens_.clear();
        block_bits_ = 0;
        block_start_ = pos_;
    }

    Framing framing_;
    std::vector<uint8_t> buf_;     // input [base_, base_ + buf_.size())
    uint64_t base_ = 0;
    uint64_t pos_ = 0;             // next input position to encode
    std::vector<uint32_t> head_;   // hash -> position + 1 (lazily allocated)
    std::vector<uint32_t> prev_;   // ring over the window: position -> previous
    uint64_t bitbuf_ = 0;
    int bitcount_ = 0;
    bool started_ = false;
    bool finished_ = false;
    // Blocks framing: the pending block.
    std::vector<uint32_t> tokens_;
    uint64_t block_bits_ = 0;
    uint64_t block_start_ = 0;
};

// Compress `data` into a raw DEFLATE stream (one fixed-Huffman block).
inline std::vector<uint8_t> deflate(const uint8_t* data, size_t n) {
    std::vector<uint8_t> out;
    out.reserve(n / 2 + 16);
    Deflater d;
    d.write(data, n, out);
    d.finish(out);
    return out;
}

inline std::vector<uint8_t> deflate(const std::vector<uint8_t>& v) {
    return deflate(v.data(), v.size());
}

}  // namespace detail
}  // namespace qvf

#endif  // QVF_DEFLATE_HPP
