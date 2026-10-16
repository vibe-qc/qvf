// qvf/container.hpp — the QVF container layer: ZIP archives, read and written.
//
// QVF archives are ZIP files (spec § 2.1). This layer reads and writes them
// with no external dependency: CRC-32, SHA-256, DEFLATE and INFLATE are the
// toolkit's own (cpp/src). It knows nothing about manifests or sections.
//
//   ZipWriter  sequential writer over a Sink (file, memory, or callback).
//              Entries are written whole (write) or streamed in chunks
//              (begin -> EntrySink), with CRC-32, sizes and the SHA-256 of
//              the uncompressed bytes computed on the fly. On a seekable sink
//              a streamed entry's local header is patched afterwards; on a
//              non-seekable one a data descriptor (general-purpose bit 3)
//              follows the data. ZIP64 structures (extra field 0x0001, end
//              record and locator) are written when a size, an offset or the
//              entry count passes the 32-bit limits, or when forced. An
//              archive needing none of them is byte-for-byte what this
//              toolkit has always written. append() reopens an existing
//              archive: new entries replace its central directory, which is
//              rewritten after them.
//   ZipReader  random access through the central directory, from memory or
//              a file. ZIP64 end records and extra fields and data-descriptor
//              entries are read; the central directory is authoritative for
//              sizes and CRCs. Duplicate names are recorded, every offset is
//              bounds-checked, an entry is never inflated past its declared
//              size, and its CRC-32 is verified. read_into() streams an entry
//              in chunks under the resource caps of `Limits`.
//
// License: Apache-2.0.
#ifndef QVF_CONTAINER_HPP
#define QVF_CONTAINER_HPP

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace qvf {
namespace detail {
class ZipWriter;   // the in-memory test/compat writer of cpp/src/qvf_zip.hpp
}
namespace container {

// ZIP compression methods QVF uses.
enum class Method : uint16_t { Store = 0, Deflate = 8 };

// Resource caps applied to untrusted archives (spec § 2.1, § 6.1). The
// defaults are the reference values; field names match the Python
// `qvf_reader.Limits` and the negative corpus' `limits` objects. qvf::Limits
// is this type.
struct Limits {
    uint64_t max_member_bytes = 8ull << 30;     // per ZIP entry, uncompressed (§ 2.1)
    uint64_t max_total_bytes = 64ull << 30;     // all ZIP entries, uncompressed
    double max_ratio = 0.0;                     // optional ratio policy; 0 disables it
    uint64_t ratio_exempt_bytes = 1ull << 20;   // smaller entries skip the ratio check
    uint64_t max_json_bytes = 256ull << 20;     // manifest.json and JSON members
    size_t max_json_depth = 64;                 // nesting of JSON arrays/objects
};

// Receives an archive's bytes in order.
class Sink {
public:
    virtual ~Sink() = default;
    virtual void write(const uint8_t* data, size_t n) = 0;
    // Bytes written so far, including any the sink started with.
    virtual uint64_t position() const = 0;
    // Whether write_at() can overwrite earlier bytes (local-header patching).
    virtual bool seekable() const { return false; }
    // Overwrite `n` bytes at `offset` < position() without moving position().
    virtual void write_at(uint64_t offset, const uint8_t* data, size_t n);
    // Called once by ZipWriter::finish(), after the last byte.
    virtual void close() {}
};

// An archive in memory. Seekable.
class MemorySink : public Sink {
public:
    MemorySink() = default;
    // Start from existing bytes; new bytes are appended after them.
    explicit MemorySink(std::vector<uint8_t> prefix) : bytes_(std::move(prefix)) {}
    void write(const uint8_t* data, size_t n) override;
    uint64_t position() const override { return bytes_.size(); }
    bool seekable() const override { return true; }
    void write_at(uint64_t offset, const uint8_t* data, size_t n) override;
    const std::vector<uint8_t>& bytes() const { return bytes_; }
    std::vector<uint8_t> take() { return std::move(bytes_); }

private:
    std::vector<uint8_t> bytes_;
};

// An archive file. Seekable.
class FileSink : public Sink {
public:
    // Create `path` (truncating an existing file).
    explicit FileSink(const std::string& path);
    // Open the existing file `path` for writing at `offset`; close() cuts the
    // file at the final position (ZipWriter::append).
    static std::unique_ptr<FileSink> open_at(const std::string& path, uint64_t offset);
    ~FileSink() override;
    void write(const uint8_t* data, size_t n) override;
    uint64_t position() const override { return pos_; }
    bool seekable() const override { return true; }
    void write_at(uint64_t offset, const uint8_t* data, size_t n) override;
    void close() override;

private:
    FileSink() = default;
    struct Impl;
    std::unique_ptr<Impl> impl_;
    std::string path_;
    uint64_t pos_ = 0;
    bool truncate_on_close_ = false;
};

// Hands every byte to a callback (a pipe, a socket, a hash). Not seekable,
// so streamed entries carry data descriptors.
class CallbackSink : public Sink {
public:
    explicit CallbackSink(std::function<void(const uint8_t*, size_t)> fn)
        : fn_(std::move(fn)) {}
    void write(const uint8_t* data, size_t n) override;
    uint64_t position() const override { return pos_; }

private:
    std::function<void(const uint8_t*, size_t)> fn_;
    uint64_t pos_ = 0;
};

// What the writer recorded for one entry.
struct EntryInfo {
    std::string name;
    Method method = Method::Store;
    uint16_t flags = 0;            // general-purpose bits (3: data descriptor, 11: UTF-8 name)
    uint32_t crc32 = 0;
    uint64_t compressed_size = 0;
    uint64_t size = 0;             // uncompressed
    uint64_t local_offset = 0;
    bool zip64 = false;            // the entry carries ZIP64 extra fields
    std::string sha256;            // of the uncompressed bytes; empty for entries kept by append()
};

class ZipWriter;
class ZipReader;

// One entry being streamed. Push the uncompressed bytes with write() in any
// number of chunks, then close(). Only one EntrySink of a writer is open at a
// time. Destroyed without close(), the entry is abandoned: its bytes stay in
// the output but the central directory does not list it.
class EntrySink {
public:
    EntrySink(EntrySink&&) noexcept;
    EntrySink& operator=(EntrySink&&) noexcept;
    ~EntrySink();

    void write(const uint8_t* data, size_t n);
    void write(const std::vector<uint8_t>& bytes) { write(bytes.data(), bytes.size()); }
    void write(const std::string& bytes);
    // Finish the entry (patch its local header or write its data descriptor)
    // and add it to the central directory. Throws if the entry passed the
    // 32-bit limits without having been begun with force_zip64.
    EntryInfo close();
    uint64_t size() const;         // uncompressed bytes so far
    bool is_open() const;

private:
    friend class ZipWriter;
    struct State;
    explicit EntrySink(std::unique_ptr<State> state);
    void abandon() noexcept;
    std::unique_ptr<State> s_;
};

class ZipWriter {
public:
    // Write a new archive to `out`. `force_zip64` gives every entry ZIP64
    // extra fields and the archive a ZIP64 end record and locator, with the
    // 32-bit fields saturated, whatever the sizes (for testing readers).
    explicit ZipWriter(std::unique_ptr<Sink> out, bool force_zip64 = false);
    // Reopen an existing archive file for appending: its entries are kept
    // (every central-directory record as it is, a repeated name included),
    // new entries are written where its central directory began, and
    // finish() writes the new central directory, old records first, and cuts
    // the file there. Until finish(), the file is not a readable archive.
    static ZipWriter append(const std::string& path);
    // The same over an archive in memory; the result is in sink(), a
    // MemorySink, after finish().
    static ZipWriter append(std::vector<uint8_t> archive);

    ZipWriter(ZipWriter&&) noexcept;
    ZipWriter& operator=(ZipWriter&&) noexcept;
    ~ZipWriter();

    // Stream an entry. With Method::Deflate the data is compressed in
    // blocks of about 32 KiB, each DEFLATEd or STOREd, whichever is smaller.
    // An entry that may reach 4 GiB must be begun with force_zip64 = true.
    EntrySink begin(const std::string& name, Method method = Method::Deflate,
                    bool force_zip64 = false);
    // Write a whole entry. With Method::Deflate the entry is STOREd instead
    // when DEFLATE would not make it smaller. ZIP64 is used when needed.
    EntryInfo write(const std::string& name, const uint8_t* data, size_t n,
                    Method method = Method::Deflate, bool force_zip64 = false);
    EntryInfo write(const std::string& name, const std::vector<uint8_t>& bytes,
                    Method method = Method::Deflate, bool force_zip64 = false);
    EntryInfo write(const std::string& name, const std::string& bytes,
                    Method method = Method::Deflate, bool force_zip64 = false);

    // Entry names are unique: begin()/write() refuse a name already listed,
    // except one allowed here. The archive then lists both records, and
    // readers resolve the name to the last one (QVF's manifest.json after an
    // in-place update, spec § 2.3).
    void allow_repeated_name(const std::string& name);
    bool contains(const std::string& name) const;
    // Remove an entry (the last of that name) from the central directory;
    // its bytes stay in the output as unreferenced space. Returns false if
    // there is none.
    bool drop(const std::string& name);
    std::vector<EntryInfo> entries() const;

    // Writer-level ZIP64 forcing (see the constructor); may be set any time
    // before finish(). Entries written earlier keep their form.
    void set_force_zip64(bool force);

    // Write the central directory and end records, then close the sink.
    void finish();
    bool finished() const;
    Sink& sink();

private:
    friend class EntrySink;
    friend class qvf::detail::ZipWriter;
    struct State;
    // Let begin()/write() repeat a name (only for building malformed test
    // archives; spec § 2.1 forbids duplicates).
    void allow_duplicate_names();
    static void keep_entries(ZipWriter& w, const ZipReader& r);
    std::shared_ptr<State> s_;
};

// One central-directory record.
struct ZipEntry {
    std::string name;
    uint16_t method = 0;           // 0 = STORE, 8 = DEFLATE
    uint16_t flags = 0;            // general-purpose bit flags
    uint32_t crc32 = 0;
    uint64_t csize = 0;            // compressed size
    uint64_t usize = 0;            // declared uncompressed size
    uint64_t local_offset = 0;
    bool zip64 = false;            // the record carried a ZIP64 extra field
};

// What an entry's local header says. The central directory is authoritative;
// these values are informational (with bit 3 set they are zero).
struct LocalHeader {
    uint64_t data_offset = 0;      // first byte of the entry's data
    uint16_t flags = 0;
    uint32_t crc32 = 0;
    uint64_t csize = 0;            // from the ZIP64 extra field when saturated
    uint64_t usize = 0;
    bool zip64 = false;            // the header carries a ZIP64 extra field
};

class ZipReader {
public:
    using Entry = ZipEntry;
    using ChunkFn = std::function<void(const uint8_t*, size_t)>;

    // Open an archive file; entries are read from the file on demand.
    static ZipReader open(const std::string& path);
    // Open an archive held in memory.
    static ZipReader from_bytes(std::vector<uint8_t> archive);
    explicit ZipReader(std::vector<uint8_t> archive);

    ZipReader(ZipReader&&) noexcept;
    ZipReader& operator=(ZipReader&&) noexcept;
    ~ZipReader();

    // Every central-directory record, in archive order, duplicates included.
    const std::vector<Entry>& entries() const;
    // Unique entry names, in central-directory order of first occurrence.
    std::vector<std::string> names() const;
    // Names that occur more than once, in order of their second occurrence.
    const std::vector<std::string>& duplicates() const;
    bool has(const std::string& name) const;
    bool contains(const std::string& name) const { return has(name); }
    // The record a lookup by name resolves to (the last one when duplicated,
    // matching Python's zipfile), or nullptr.
    const Entry* find(const std::string& name) const;

    uint64_t archive_size() const;
    uint64_t central_directory_offset() const;
    uint64_t total_size() const;   // sum of the declared uncompressed sizes

    // The uncompressed bytes of an entry. Throws when the declared size
    // exceeds `max_bytes`, and when the data cannot be read: truncated,
    // encrypted, an unsupported method, a local header naming another entry,
    // data that does not inflate to exactly the declared size, or a CRC-32
    // mismatch.
    std::vector<uint8_t> read(const std::string& name,
                              uint64_t max_bytes = UINT64_MAX) const;
    // The same under every cap of `limits`: the per-member size, the total
    // of all entries' declared sizes, and the compression ratio (checked
    // before inflating and again as bytes are produced).
    std::vector<uint8_t> read(const std::string& name, const Limits& limits) const;
    // Stream an entry's uncompressed bytes to `fn` in chunks (about 1 MiB),
    // under the caps of `limits`. A failure is thrown after some chunks may
    // have been delivered (the CRC-32 is known only at the end): discard what
    // was received when it throws.
    void read_into(const std::string& name, const ChunkFn& fn,
                   const Limits& limits = Limits{}) const;
    // Throws the error read() would throw for exceeding a cap of `limits`.
    void check_limits(const Entry& entry, const Limits& limits) const;

    LocalHeader local_header(const Entry& entry) const;

private:
    friend class ZipWriter;
    struct Impl;
    ZipReader() = default;
    void stream_entry(const Entry& e, const ChunkFn& fn, const Limits* limits,
                      std::vector<uint8_t>* collect) const;
    std::unique_ptr<Impl> impl_;
};

}  // namespace container
}  // namespace qvf

#endif  // QVF_CONTAINER_HPP
