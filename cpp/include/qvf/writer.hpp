// qvf/writer.hpp — streaming typed writer, sharing the compatibility backend.
// License: Apache-2.0.
#ifndef QVF_WRITER_HPP
#define QVF_WRITER_HPP
#include <string_view>
#include "qvf/tensor_view.hpp"
namespace qvf {
enum class RootBlock { Provenance, Metadata, ViewerDefaults, Thermochemistry,
                       DipoleMoment, Constraints, Energies, Extensions };
struct JsonPayload { std::string role; Json value; };
struct BinaryPayload { std::string role; TensorData value; };
struct OpaquePayload {
    std::string role;
    std::vector<uint8_t> bytes;
    std::optional<std::string> media_type;
};
class Editor;
namespace detail { struct CAccess; }
class Writer {
public:
    // The default is a streaming MemorySink; to_bytes() finishes and takes it.
    explicit Writer(Source source);
    Writer(Source source, std::unique_ptr<container::Sink> sink);
    Writer(Source source, const std::string& path);
    Writer(Writer&&) noexcept;
    Writer& operator=(Writer&&) noexcept;
    ~Writer();
    void set_root(RootBlock, Json);
    void set_auto_metadata(bool enabled);
    void set_force_zip64(bool enabled);
    Manifest manifest() const;
    template <class K> std::string add(const K& value) { return value.to_section(*this); }
    // Declare a section before begin_binary/add_json/add_opaque. Supplied
    // member descriptors are allowed for custom producers; they are not read.
    std::string add_section(Section);
    MemberSink begin_binary(std::string section_id, std::string role, DType,
                            std::vector<int64_t> shape);
    void add_json(const std::string& section_id, const std::string& role, Json);
    void add_opaque(const std::string& section_id, const OpaquePayload&);
    void add_tensor(const std::string& section_id, const BinaryPayload&);
    // Canonical-kind serializers call this transaction. Shape/dtype and JSON
    // schema checks precede writes; a failed member removes the new section.
    std::string add_payload(Section, const std::vector<JsonPayload>&,
                            const std::vector<BinaryPayload>&,
                            const std::vector<OpaquePayload>& = {});
    void finish(); // manifest STOREd last; idempotent
    std::vector<uint8_t> to_bytes(); // only the default memory writer
private:
    friend class Editor;
    friend struct detail::CAccess;
    explicit Writer(QvfWriter writer);
    void require_open() const;
    std::unique_ptr<QvfWriter> writer_;
    container::MemorySink* memory_ = nullptr;
    bool finished_ = false;
};
} // namespace qvf
#endif
