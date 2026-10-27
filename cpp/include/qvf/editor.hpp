// qvf/editor.hpp — archive updates and optional atomic replacement.
// License: Apache-2.0.
#ifndef QVF_EDITOR_HPP
#define QVF_EDITOR_HPP
#include "qvf/writer.hpp"
namespace qvf {
enum class RunStatus { Running, Converged, Failed };
class Editor {
public:
    // atomic=true copies to an exclusively reserved sibling directory and
    // commits by rename. Before commit, the original remains byte-identical.
    // Atomic replacement is guaranteed by POSIX rename on the same filesystem;
    // platforms unable to replace an existing file fail without deleting it.
    // In-place mode can leave an incomplete ZIP after a failed/abandoned stream.
    static Editor open(const std::string& path, bool atomic = false);
    Editor(Editor&&) noexcept;
    Editor& operator=(Editor&&) noexcept;
    ~Editor();
    Writer& writer();
    template <class K> std::string append(const K& value) { return writer().add(value); }
    Section remove_section(std::string_view id);
    // An omitted id is accepted only when exactly one run.record exists.
    void set_run_status(RunStatus, std::string_view id = {});
    void commit();
    // Drops orphans and previous manifests; streams members, optionally
    // recompressing them, and replaces out only after a complete archive exists.
    static void repack(const std::string& in, const std::string& out,
                       container::Method = container::Method::Deflate);
private:
    struct Impl;
    explicit Editor(std::unique_ptr<Impl>);
    std::unique_ptr<Impl> impl_;
};
} // namespace qvf
#endif
