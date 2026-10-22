// Internal C handle ownership and exception boundary. License: Apache-2.0.
#ifndef QVF_C_INTERNAL_HPP
#define QVF_C_INTERNAL_HPP
#include "qvf/c_api.h"
#include "qvf/writer.hpp"
#include "qvf/reader.hpp"
#include "qvf/editor.hpp"
#include <cstring>
#include <memory>
#include <optional>
#include <stdexcept>
namespace qvf { namespace detail {
struct CAccess {
    static QvfWriter& backend(Writer& w) { w.require_open(); return *w.writer_; }
    static std::unique_ptr<Writer> adopt(QvfWriter w) {
        return std::unique_ptr<Writer>(new Writer(std::move(w)));
    }
};
}}
namespace qvf_c_detail {
// Exception reporting must itself be allocation-free, including bad_alloc.
struct Error {
    char text[1024]{};
    void clear() noexcept { text[0] = 0; }
    const char* c_str() const noexcept { return text; }
    Error& operator=(const char* s) noexcept {
        size_t n = 0; if (s) while (n + 1 < sizeof(text) && s[n]) { text[n] = s[n]; ++n; }
        text[n] = 0; return *this;
    }
};
extern thread_local Error global_error;
struct Cancelled : std::exception { const char* what() const noexcept override { return "callback cancelled"; } };
struct ShortBuffer : std::exception { const char* what() const noexcept override { return "output buffer too small"; } };
template<class F> int protect(Error& error, F&& body) noexcept {
    error.clear();
    try { body(); return QVF_OK; }
    catch (const Cancelled& e) { error = e.what(); return QVF_CANCELLED; }
    catch (const ShortBuffer& e) { error = e.what(); return QVF_BUFFER_TOO_SMALL; }
    catch (const std::exception& e) { error = e.what(); return QVF_ERROR; }
    catch (...) { error = "unknown error"; return QVF_UNKNOWN_ERROR; }
}
template<class H, class F> int guard(H* handle, F&& body) noexcept {
    if (!handle) { global_error = "NULL handle"; return QVF_INVALID_HANDLE; }
    return protect(handle->last_error, std::forward<F>(body));
}
inline void require(bool condition, const char* message) {
    if (!condition) throw std::invalid_argument(message);
}
inline const char* required(const char* p) { require(p != nullptr, "NULL string argument"); return p; }
struct EditorState {
    qvf::Editor editor;
    explicit EditorState(qvf::Editor e) : editor(std::move(e)) {}
};
}
struct qvf_writer {
    qvf_c_detail::Error last_error;
    std::unique_ptr<qvf::QvfWriter> legacy;
    std::unique_ptr<qvf::Writer> owned;
    std::shared_ptr<qvf_c_detail::EditorState> editor;
    bool legacy_mode = false, finished = false, bytes_ready = false;
    std::vector<uint8_t> cached_bytes;
    // Destroy the active member before destroying its owner.
    std::optional<qvf::MemberSink> member;
    explicit qvf_writer(qvf::Source source)
        : legacy(new qvf::QvfWriter(std::move(source))), legacy_mode(true) {}
    explicit qvf_writer(std::unique_ptr<qvf::Writer> writer) : owned(std::move(writer)) {}
    explicit qvf_writer(std::shared_ptr<qvf_c_detail::EditorState> state) : editor(std::move(state)) {}
    qvf::Writer& facade() {
        qvf_c_detail::require(!finished, "writer is finished");
        if (editor) return editor->editor.writer();
        if (legacy) { owned = qvf::detail::CAccess::adopt(std::move(*legacy)); legacy.reset(); }
        return *owned;
    }
    qvf::QvfWriter& backend() {
        qvf_c_detail::require(!finished, "writer is finished");
        if (legacy) return *legacy;
        return qvf::detail::CAccess::backend(facade());
    }
};
struct qvf_reader {
    qvf_c_detail::Error last_error;
    qvf::Reader impl;
    std::string text;
    explicit qvf_reader(qvf::Reader r) : impl(std::move(r)) {}
};
struct qvf_report {
    qvf_c_detail::Error last_error;
    qvf::validate::Report impl;
    explicit qvf_report(qvf::validate::Report r) : impl(std::move(r)) {}
};
struct qvf_editor {
    qvf_c_detail::Error last_error;
    std::shared_ptr<qvf_c_detail::EditorState> state;
    explicit qvf_editor(qvf::Editor e) : state(std::make_shared<qvf_c_detail::EditorState>(std::move(e))) {}
};
using qvf_c_detail::guard;
#endif
