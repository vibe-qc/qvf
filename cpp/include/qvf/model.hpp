// qvf/model.hpp — the typed manifest model (library layer L1): Manifest,
// Section and MemberSpec, built from and written back to manifest.json.
// Header-only; part of the zero-dependency QVF library. License: Apache-2.0.
//
// The model is lossless. from_json() types every field it knows when the field
// has the JSON type the schema gives it, and keeps everything else verbatim in
// the `extra` object of the enclosing record: keys the model does not know
// (kind-specific section fields such as `operand_a` or `ao_metadata`, vendor
// keys) and known keys whose value has another type. to_json() writes the
// typed fields, then `extra`, so to_json(from_json(m)) equals m as a JSON
// value for any manifest object m (object key order aside; a key a parsed
// object repeats keeps its last value, as in Python). Absent and present are
// told apart everywhere: every optional field is a std::optional.
//
// The model checks nothing; the validator (QvfReader::validate_findings) does.
// QvfReader::typed_manifest() exposes the model of an opened archive beside
// the raw QvfReader::manifest().
#ifndef QVF_MODEL_HPP
#define QVF_MODEL_HPP

#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "qvf/json.hpp"

namespace qvf {

// The root `source` block (spec § 3.1): the program that wrote the archive.
struct Source {
    std::string program;
    std::string version;
    std::string calculation;
};

namespace model_detail {

// The value of the last member named `key` (a parsed object may repeat a key;
// the last one wins, as in Python's json module).
inline const Json* find(const Json& obj, std::string_view key) {
    const auto& items = obj.items();
    for (auto it = items.rbegin(); it != items.rend(); ++it)
        if (it->first == key) return &it->second;
    return nullptr;
}

// Each key of an object once, first-occurrence order, last value.
inline std::vector<std::pair<std::string, const Json*>> members_of(const Json& obj) {
    std::vector<std::pair<std::string, const Json*>> out;
    for (const auto& kv : obj.items()) {
        bool seen = false;
        for (auto& o : out)
            if (o.first == kv.first) { o.second = &kv.second; seen = true; break; }
        if (!seen) out.emplace_back(kv.first, &kv.second);
    }
    return out;
}

inline bool is_key(std::string_view key, std::initializer_list<std::string_view> known) {
    for (std::string_view k : known)
        if (k == key) return true;
    return false;
}

inline void put_string(Json& out, const char* key, const std::optional<std::string>& v) {
    if (v) out.set(key, *v);
}

// Every key of `extra`, after the typed fields.
inline void put_extra(Json& out, const Json& extra) {
    if (!extra.is_object()) return;
    for (const auto& kv : extra.items()) out.set(kv.first, kv.second);
}

}  // namespace model_detail

// One entry of a section's `members` object (spec § 4.2).
struct MemberSpec {
    // How the member's bytes are stored: format "json"; format "binary" with
    // a dtype (a typed array); format "binary" without one (opaque bytes).
    enum class Format { Json, Binary, Opaque };

    std::optional<std::string> path;
    std::optional<Format> format;
    std::optional<std::string> dtype;                // Binary
    std::optional<std::vector<int64_t>> shape;       // Binary
    std::optional<std::string> sha256;
    std::optional<uint64_t> size;                    // spec § 4.2, optional
    std::optional<std::string> media_type;           // spec § 4.2, optional
    Json extra = Json::object();

    static MemberSpec from_json(const Json& j) {
        using namespace model_detail;
        if (!j.is_object()) throw std::invalid_argument("qvf::MemberSpec: not a JSON object");
        MemberSpec m;
        const auto members = members_of(j);
        for (const auto& kv : members) {
            const std::string& key = kv.first;
            const Json& v = *kv.second;
            bool typed = false;
            if (key == "path" && v.is_string()) {
                m.path = v.as_string();
                typed = true;
            } else if (key == "dtype" && v.is_string()) {
                m.dtype = v.as_string();
                typed = true;
            } else if (key == "sha256" && v.is_string()) {
                m.sha256 = v.as_string();
                typed = true;
            } else if (key == "media_type" && v.is_string()) {
                m.media_type = v.as_string();
                typed = true;
            } else if (key == "size" && v.type() == Json::Type::Int && v.as_int() >= 0) {
                m.size = static_cast<uint64_t>(v.as_int());
                typed = true;
            } else if (key == "shape" && v.is_array()) {
                std::vector<int64_t> shape;
                typed = true;
                for (const Json& d : v.elements()) {
                    if (d.type() != Json::Type::Int) { typed = false; break; }
                    shape.push_back(d.as_int());
                }
                if (typed) m.shape = std::move(shape);
            } else if (key == "format" && v.is_string() &&
                       (v.as_string() == "json" || v.as_string() == "binary")) {
                typed = true;   // resolved below, once dtype is known
            }
            if (!typed) m.extra.set(key, v);
        }
        if (const Json* f = find(j, "format"))
            if (f->is_string() && (f->as_string() == "json" || f->as_string() == "binary"))
                m.format = f->as_string() == "json" ? Format::Json
                           : m.dtype                ? Format::Binary
                                                    : Format::Opaque;
        return m;
    }

    Json to_json() const {
        using namespace model_detail;
        Json out = Json::object();
        put_string(out, "path", path);
        if (format) out.set("format", *format == Format::Json ? "json" : "binary");
        put_string(out, "dtype", dtype);
        if (shape) {
            Json s = Json::array();
            for (int64_t d : *shape) s.push_back(Json(static_cast<long long>(d)));
            out.set("shape", std::move(s));
        }
        put_string(out, "sha256", sha256);
        if (size) out.set("size", Json(static_cast<unsigned long long>(*size)));
        put_string(out, "media_type", media_type);
        put_extra(out, extra);
        return out;
    }
};

// One entry of the manifest's `sections` array (spec § 4.1).
struct Section {
    std::optional<std::string> id, kind, label, component, structure_ref, run_ref, group;
    std::optional<bool> critical;
    // role -> member spec, in manifest order; absent when the section has no
    // `members` object of member-spec objects (then `extra` holds it as is).
    std::optional<std::vector<std::pair<std::string, MemberSpec>>> members;
    // Kind-specific peer fields (operand_a, ao_metadata, program, chains, ...)
    // and anything else the model does not type.
    Json extra = Json::object();

    // The spec of member `role`, or nullptr.
    const MemberSpec* member(std::string_view role) const {
        if (!members) return nullptr;
        for (const auto& kv : *members)
            if (kv.first == role) return &kv.second;
        return nullptr;
    }

    static Section from_json(const Json& j) {
        using namespace model_detail;
        if (!j.is_object()) throw std::invalid_argument("qvf::Section: not a JSON object");
        Section s;
        std::optional<std::string>* const strings[] = {&s.id, &s.kind, &s.label, &s.component,
                                                       &s.structure_ref, &s.run_ref, &s.group};
        const char* const names[] = {"id", "kind", "label", "component",
                                     "structure_ref", "run_ref", "group"};
        for (const auto& kv : members_of(j)) {
            const std::string& key = kv.first;
            const Json& v = *kv.second;
            bool typed = false;
            for (std::size_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i)
                if (key == names[i] && v.is_string()) {
                    *strings[i] = v.as_string();
                    typed = true;
                }
            if (key == "critical" && v.is_bool()) {
                s.critical = v.as_bool();
                typed = true;
            } else if (key == "members" && v.is_object()) {
                bool all_objects = true;
                for (const auto& m : v.items()) all_objects = all_objects && m.second.is_object();
                if (all_objects) {
                    std::vector<std::pair<std::string, MemberSpec>> list;
                    for (const auto& m : members_of(v))
                        list.emplace_back(m.first, MemberSpec::from_json(*m.second));
                    s.members = std::move(list);
                    typed = true;
                }
            }
            if (!typed) s.extra.set(key, v);
        }
        return s;
    }

    Json to_json() const {
        using namespace model_detail;
        Json out = Json::object();
        put_string(out, "id", id);
        put_string(out, "kind", kind);
        put_string(out, "label", label);
        put_string(out, "component", component);
        if (critical) out.set("critical", *critical);
        put_string(out, "structure_ref", structure_ref);
        put_string(out, "run_ref", run_ref);
        put_string(out, "group", group);
        if (members) {
            Json m = Json::object();
            for (const auto& kv : *members) m.set(kv.first, kv.second.to_json());
            out.set("members", std::move(m));
        }
        put_extra(out, extra);
        return out;
    }
};

// The whole manifest.json (spec § 3).
struct Manifest {
    std::optional<int64_t> qvf_version;
    std::optional<std::string> schema_uri;
    std::optional<std::string> byte_order;
    // Typed when `source` is an object of exactly the three strings.
    std::optional<Source> source;
    // The root blocks, each kept as JSON when it is an object (spec § 3.2 -
    // § 3.6, § 7.4).
    std::optional<Json> provenance, metadata, viewer_defaults, thermochemistry,
        dipole_moment, constraints, energies, extensions;
    // Absent when `sections` is not an array of objects (then `extra` holds it).
    std::optional<std::vector<Section>> sections;
    Json extra = Json::object();

    // The section with this id (the first one, should ids repeat), or nullptr.
    const Section* section(std::string_view id) const {
        if (!sections) return nullptr;
        for (const Section& s : *sections)
            if (s.id && *s.id == id) return &s;
        return nullptr;
    }

    static Manifest from_json(const Json& j) {
        using namespace model_detail;
        if (!j.is_object()) throw std::invalid_argument("qvf::Manifest: not a JSON object");
        Manifest m;
        struct Block {
            const char* name;
            std::optional<Json>* field;
        } const blocks[] = {{"provenance", &m.provenance},
                            {"metadata", &m.metadata},
                            {"viewer_defaults", &m.viewer_defaults},
                            {"thermochemistry", &m.thermochemistry},
                            {"dipole_moment", &m.dipole_moment},
                            {"constraints", &m.constraints},
                            {"energies", &m.energies},
                            {"extensions", &m.extensions}};
        for (const auto& kv : members_of(j)) {
            const std::string& key = kv.first;
            const Json& v = *kv.second;
            bool typed = false;
            if (key == "qvf_version" && v.type() == Json::Type::Int) {
                m.qvf_version = v.as_int();
                typed = true;
            } else if (key == "schema_uri" && v.is_string()) {
                m.schema_uri = v.as_string();
                typed = true;
            } else if (key == "byte_order" && v.is_string()) {
                m.byte_order = v.as_string();
                typed = true;
            } else if (key == "source" && v.is_object()) {
                const auto fields = members_of(v);
                bool exact = fields.size() == 3;
                for (const auto& f : fields)
                    exact = exact && f.second->is_string() &&
                            is_key(f.first, {"program", "version", "calculation"});
                if (exact) {
                    m.source = Source{find(v, "program")->as_string(),
                                      find(v, "version")->as_string(),
                                      find(v, "calculation")->as_string()};
                    typed = true;
                }
            } else if (key == "sections" && v.is_array()) {
                bool all_objects = true;
                for (const Json& s : v.elements()) all_objects = all_objects && s.is_object();
                if (all_objects) {
                    std::vector<Section> list;
                    for (const Json& s : v.elements()) list.push_back(Section::from_json(s));
                    m.sections = std::move(list);
                    typed = true;
                }
            } else if (v.is_object()) {
                for (const Block& b : blocks)
                    if (key == b.name) {
                        *b.field = v;
                        typed = true;
                    }
            }
            if (!typed) m.extra.set(key, v);
        }
        return m;
    }

    Json to_json() const {
        using namespace model_detail;
        Json out = Json::object();
        if (qvf_version) out.set("qvf_version", Json(static_cast<long long>(*qvf_version)));
        put_string(out, "schema_uri", schema_uri);
        put_string(out, "byte_order", byte_order);
        if (source) {
            Json s = Json::object();
            s.set("program", source->program);
            s.set("version", source->version);
            s.set("calculation", source->calculation);
            out.set("source", std::move(s));
        }
        const std::pair<const char*, const std::optional<Json>*> blocks[] = {
            {"provenance", &provenance},       {"metadata", &metadata},
            {"viewer_defaults", &viewer_defaults}, {"thermochemistry", &thermochemistry},
            {"dipole_moment", &dipole_moment}, {"constraints", &constraints},
            {"energies", &energies},           {"extensions", &extensions}};
        for (const auto& b : blocks)
            if (*b.second) out.set(b.first, **b.second);
        if (sections) {
            Json list = Json::array();
            for (const Section& s : *sections) list.push_back(s.to_json());
            out.set("sections", std::move(list));
        }
        put_extra(out, extra);
        return out;
    }
};

}  // namespace qvf

#endif  // QVF_MODEL_HPP
