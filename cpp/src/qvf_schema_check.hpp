// qvf_schema_check.hpp — the table-driven JSON Schema checker of the C++
// validator. Internal, header-only; part of the zero-dependency QVF library.
//
// scripts/gen_kinds.py compiles spec/qvf_manifest.schema.json into the
// instruction table of qvf_schema_table.hpp: one node per schema object, one
// op per assertion keyword, with shared pools of strings, numbers, JSON
// literals and compiled patterns. This file interprets that table. It knows
// nothing about QVF: everything schema-specific is in the table, so a schema
// change only needs the table regenerated.
//
// The errors are the ones the Python reference validator gets from
// jsonschema's Draft202012Validator.iter_errors(): keywords that apply to
// children (properties, patternProperties, additionalProperties with a
// schema, prefixItems, items, allOf, $ref, if/then/else, dependentSchemas)
// report their children's errors at the children's locations; every other
// keyword — oneOf, anyOf, not and contains among them — reports one error at
// the instance it applies to. A finding's location is therefore the same JSON
// pointer in both validators; the messages are worded independently.
//
// Patterns are run by a small Pike VM over Unicode code points (linear time,
// no recursion, no <regex>), with ECMA-262 semantics: `$` matches only at the
// end of the string. (Python's re also matches `$` before a final newline,
// the one known divergence from the Python reference.) License: Apache-2.0.
#ifndef QVF_SCHEMA_CHECK_HPP
#define QVF_SCHEMA_CHECK_HPP

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "qvf/json.hpp"
#include "qvf_schema_table.hpp"

namespace qvf {
namespace detail {
namespace schema {

namespace tbl = schema_table;

// One schema error. `pointer` is the RFC 6901 JSON pointer of the failing
// value inside the checked document ("" for the document itself), `location`
// the same path unescaped and '/'-joined, as the Python validator prints it.
struct Error {
    std::string pointer;
    std::string location;
    std::string message;
};

// --- JSON helpers -------------------------------------------------------------

// The value of the last member named `key`: a parsed object may repeat a key,
// and Python's json module keeps the last one.
inline const Json* find_last(const Json& obj, std::string_view key) {
    const auto& items = obj.items();
    for (auto it = items.rbegin(); it != items.rend(); ++it)
        if (it->first == key) return &it->second;
    return nullptr;
}

// The members of an object with each key once (first-occurrence order, last
// value), the view Python has of a parsed object.
inline std::vector<std::pair<const std::string*, const Json*>> unique_members(const Json& obj) {
    std::vector<std::pair<const std::string*, const Json*>> out;
    const auto& items = obj.items();
    out.reserve(items.size());
    if (items.size() <= 8) {
        for (const auto& kv : items) {
            bool seen = false;
            for (auto& o : out)
                if (*o.first == kv.first) { o.second = &kv.second; seen = true; break; }
            if (!seen) out.emplace_back(&kv.first, &kv.second);
        }
        return out;
    }
    std::unordered_map<std::string_view, std::size_t> index;
    index.reserve(items.size());
    for (const auto& kv : items) {
        auto it = index.find(kv.first);
        if (it != index.end()) {
            out[it->second].second = &kv.second;
        } else {
            index.emplace(kv.first, out.size());
            out.emplace_back(&kv.first, &kv.second);
        }
    }
    return out;
}

inline bool is_integral(const Json& v) {
    if (v.type() == Json::Type::Int) return true;
    if (v.type() != Json::Type::Double) return false;
    const double d = v.as_double();
    return std::isfinite(d) && std::floor(d) == d;
}

// JSON equality as jsonschema decides it: booleans are not numbers, 1 == 1.0,
// arrays and objects compare by value.
inline bool json_equal(const Json& a, const Json& b) {
    if (a.is_bool() || b.is_bool()) return a.is_bool() && b.is_bool() && a.as_bool() == b.as_bool();
    if (a.is_number() && b.is_number()) {
        if (a.type() == Json::Type::Int && b.type() == Json::Type::Int)
            return a.as_int() == b.as_int();
        return a.as_double() == b.as_double();
    }
    if (a.type() != b.type()) return false;
    switch (a.type()) {
        case Json::Type::Null: return true;
        case Json::Type::String: return a.as_string() == b.as_string();
        case Json::Type::Array: {
            if (a.size() != b.size()) return false;
            for (std::size_t i = 0; i < a.size(); ++i)
                if (!json_equal(a.at(i), b.at(i))) return false;
            return true;
        }
        case Json::Type::Object: {
            const auto ua = unique_members(a);
            const auto ub = unique_members(b);
            if (ua.size() != ub.size()) return false;
            for (const auto& kv : ua) {
                const Json* other = find_last(b, *kv.first);
                if (!other || !json_equal(*kv.second, *other)) return false;
            }
            return true;
        }
        default: return false;
    }
}

// Number of Unicode code points of a UTF-8 string.
inline std::size_t code_point_count(const std::string& s) {
    std::size_t n = 0;
    for (char c : s)
        if ((static_cast<unsigned char>(c) & 0xC0) != 0x80) ++n;
    return n;
}

// The code points of a UTF-8 string; a malformed byte stands for itself.
inline std::vector<std::uint32_t> code_points(const std::string& s) {
    std::vector<std::uint32_t> out;
    out.reserve(s.size());
    std::size_t i = 0;
    while (i < s.size()) {
        const unsigned char c = static_cast<unsigned char>(s[i]);
        std::size_t len = c < 0x80 ? 1 : (c & 0xE0) == 0xC0 ? 2 : (c & 0xF0) == 0xE0 ? 3
                                       : (c & 0xF8) == 0xF0 ? 4 : 0;
        std::uint32_t cp = len == 1 ? c : len == 2 ? (c & 0x1Fu) : len == 3 ? (c & 0x0Fu)
                                                                             : (c & 0x07u);
        bool ok = len != 0 && i + len <= s.size();
        for (std::size_t k = 1; ok && k < len; ++k) {
            const unsigned char cc = static_cast<unsigned char>(s[i + k]);
            if ((cc & 0xC0) != 0x80) ok = false;
            else cp = (cp << 6) | (cc & 0x3Fu);
        }
        if (!ok) { out.push_back(c); ++i; continue; }
        out.push_back(cp);
        i += len;
    }
    return out;
}

// A compact rendering of a value for messages.
inline std::string show(const Json& v) {
    std::string s;
    try {
        s = v.dump(0);
    } catch (const std::exception&) {
        return "<value>";
    }
    if (s.size() > 80) {
        std::size_t cut = 77;   // never inside a UTF-8 sequence
        while (cut > 0 && (static_cast<unsigned char>(s[cut]) & 0xC0) == 0x80) --cut;
        s = s.substr(0, cut) + "...";
    }
    return s;
}

inline std::string show_number(double x) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%.17g", x);
    return buf;
}

// The JSON literals of the table (const / enum values), parsed once.
inline const std::vector<Json>& table_values() {
    static const std::vector<Json> values = [] {
        std::vector<Json> out;
        for (const char* text : tbl::kValues) {
            try {
                out.push_back(Json::parse(text));
            } catch (const std::exception&) {
                out.push_back(Json());   // the empty-pool placeholder
            }
        }
        return out;
    }();
    return values;
}

// --- patterns -------------------------------------------------------------------

inline bool rx_class_match(const tbl::RxOp& op, std::uint32_t c) {
    bool in = false;
    for (std::int32_t k = 0; k < op.y && !in; ++k) {
        const std::size_t r = 2 * static_cast<std::size_t>(op.x + k);
        in = c >= tbl::kRxRanges[r] && c <= tbl::kRxRanges[r + 1];
    }
    return op.code == tbl::kRxClass ? in : !in;
}

// True when compiled pattern `rx` matches anywhere in `text` (JSON Schema
// patterns are unanchored). A Pike VM: every live thread advances in lock
// step, so the run time is linear in the text and the program.
inline bool rx_search(std::int32_t rx, const std::string& text) {
    const tbl::RxProgram& prog = tbl::kRxPrograms[rx];
    const tbl::RxOp* ops = tbl::kRxOps + prog.first;
    const std::vector<std::uint32_t> cps = code_points(text);
    const std::size_t none = static_cast<std::size_t>(-1);
    std::vector<std::size_t> mark(static_cast<std::size_t>(prog.count), none);
    std::vector<std::int32_t> cur, next, stack;
    std::size_t step = 0;
    bool matched = false;
    // Add the epsilon closure of `pc` at text position `pos` to `list`.
    auto add = [&](std::vector<std::int32_t>& list, std::int32_t start, std::size_t pos) {
        stack.push_back(start);
        while (!stack.empty()) {
            const std::int32_t pc = stack.back();
            stack.pop_back();
            std::size_t& seen = mark[static_cast<std::size_t>(pc)];
            if (seen == step) continue;
            seen = step;
            const tbl::RxOp& op = ops[pc];
            switch (op.code) {
                case tbl::kRxJump: stack.push_back(op.x); break;
                case tbl::kRxSplit:
                    stack.push_back(op.y);
                    stack.push_back(op.x);
                    break;
                case tbl::kRxLineStart:
                    if (pos == 0) stack.push_back(pc + 1);
                    break;
                case tbl::kRxLineEnd:
                    if (pos == cps.size()) stack.push_back(pc + 1);
                    break;
                case tbl::kRxMatch: matched = true; break;
                default: list.push_back(pc); break;   // Class / NotClass
            }
        }
    };
    add(cur, 0, 0);
    for (std::size_t pos = 0; pos < cps.size() && !matched; ++pos) {
        ++step;
        next.clear();
        for (std::int32_t pc : cur)
            if (rx_class_match(ops[pc], cps[pos])) add(next, pc + 1, pos + 1);
        add(next, 0, pos + 1);   // a match may start at any position
        std::swap(cur, next);
    }
    return matched;
}

// --- the interpreter --------------------------------------------------------------

inline std::string type_names(std::int32_t mask) {
    static const struct {
        std::int32_t bit;
        const char* name;
    } kNames[] = {{tbl::kTypeNull, "null"},     {tbl::kTypeBoolean, "boolean"},
                  {tbl::kTypeObject, "object"}, {tbl::kTypeArray, "array"},
                  {tbl::kTypeNumber, "number"}, {tbl::kTypeString, "string"},
                  {tbl::kTypeInteger, "integer"}};
    std::string out;
    for (const auto& n : kNames)
        if (mask & n.bit) out += (out.empty() ? "'" : ", '") + std::string(n.name) + "'";
    return out;
}

inline bool type_matches(std::int32_t mask, const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return (mask & tbl::kTypeNull) != 0;
        case Json::Type::Bool: return (mask & tbl::kTypeBoolean) != 0;
        case Json::Type::Object: return (mask & tbl::kTypeObject) != 0;
        case Json::Type::Array: return (mask & tbl::kTypeArray) != 0;
        case Json::Type::String: return (mask & tbl::kTypeString) != 0;
        case Json::Type::Int: return (mask & (tbl::kTypeNumber | tbl::kTypeInteger)) != 0;
        case Json::Type::Double:
            return (mask & tbl::kTypeNumber) != 0 ||
                   ((mask & tbl::kTypeInteger) != 0 && is_integral(v));
        default: return false;
    }
}

class Evaluator {
public:
    // Collects errors into `out`; with nullptr it only decides validity and
    // stops at the first failure.
    explicit Evaluator(std::vector<Error>* out) : out_(out) {}

    bool eval(std::int32_t node, const Json& v) {
        const tbl::Node& n = tbl::kNodes[node];
        bool ok = true;
        for (std::int32_t i = 0; i < n.count; ++i) {
            if (!apply(tbl::kOps[n.first + i], n, v)) {
                ok = false;
                if (!out_) return false;
            }
        }
        return ok;
    }

private:
    std::vector<Error>* out_;
    std::vector<std::string> path_;

    static bool valid(std::int32_t node, const Json& v) {
        Evaluator e(nullptr);
        return e.eval(node, v);
    }

    bool fail(std::string message) {
        if (out_) {
            Error e;
            for (std::size_t i = 0; i < path_.size(); ++i) {
                e.pointer.push_back('/');
                for (char c : path_[i]) {
                    if (c == '~') e.pointer += "~0";
                    else if (c == '/') e.pointer += "~1";
                    else e.pointer.push_back(c);
                }
                if (i) e.location.push_back('/');
                e.location += path_[i];
            }
            e.message = std::move(message);
            out_->push_back(std::move(e));
        }
        return false;
    }

    // Evaluate a child value under `node`, one path segment deeper.
    bool descend(std::int32_t node, const Json& v, std::string segment) {
        if (!out_) return eval(node, v);
        path_.push_back(std::move(segment));
        const bool ok = eval(node, v);
        path_.pop_back();
        return ok;
    }

    static const char* str(std::int32_t i) { return tbl::kStrings[i]; }
    static std::int32_t list(std::int32_t i) { return tbl::kLists[i]; }

    // The non-additional keys of a node: its Properties names and the
    // patterns of its PatternProperties.
    static bool declared(const tbl::Node& n, const std::string& key) {
        for (std::int32_t i = 0; i < n.count; ++i) {
            const tbl::Op& o = tbl::kOps[n.first + i];
            if (o.code == tbl::kProperties) {
                for (std::int32_t k = 0; k < o.b; ++k)
                    if (key == str(tbl::kPairs[o.a + 2 * k])) return true;
            } else if (o.code == tbl::kPatternProperties) {
                for (std::int32_t k = 0; k < o.b; ++k)
                    if (rx_search(tbl::kPairs[o.a + 2 * k], key)) return true;
            }
        }
        return false;
    }

    bool apply(const tbl::Op& o, const tbl::Node& n, const Json& v) {
        switch (o.code) {
            case tbl::kFalse:
                return fail("False schema does not allow " + show(v));
            case tbl::kType:
                if (type_matches(o.a, v)) return true;
                return fail(show(v) + " is not of type " + type_names(o.a));
            case tbl::kConst:
                if (json_equal(v, table_values()[static_cast<std::size_t>(o.a)])) return true;
                return fail(std::string(tbl::kValues[o.a]) + " was expected");
            case tbl::kEnum: {
                for (std::int32_t k = 0; k < o.b; ++k)
                    if (json_equal(v, table_values()[static_cast<std::size_t>(list(o.a + k))]))
                        return true;
                if (!out_) return false;
                std::string names;
                for (std::int32_t k = 0; k < o.b; ++k)
                    names += (k ? ", " : "") + std::string(tbl::kValues[list(o.a + k)]);
                return fail(show(v) + " is not one of [" + names + "]");
            }
            case tbl::kRef:
                return eval(o.a, v);
            case tbl::kAllOf: {
                bool ok = true;
                for (std::int32_t k = 0; k < o.b; ++k)
                    if (!eval(list(o.a + k), v)) {
                        ok = false;
                        if (!out_) return false;
                    }
                return ok;
            }
            case tbl::kAnyOf:
                for (std::int32_t k = 0; k < o.b; ++k)
                    if (valid(list(o.a + k), v)) return true;
                return fail(show(v) + " is not valid under any of the given schemas");
            case tbl::kOneOf: {
                std::int32_t matches = 0;
                for (std::int32_t k = 0; k < o.b && matches < 2; ++k)
                    if (valid(list(o.a + k), v)) ++matches;
                if (matches == 1) return true;
                return fail(show(v) + (matches == 0
                                           ? " is not valid under any of the given schemas"
                                           : " is valid under more than one of the given schemas"));
            }
            case tbl::kNot:
                if (!valid(o.a, v)) return true;
                return fail(show(v) + " should not be valid under the given schema");
            case tbl::kIf:
                if (valid(o.a, v)) return o.b < 0 || eval(o.b, v);
                return o.c < 0 || eval(o.c, v);
            case tbl::kProperties: {
                if (!v.is_object()) return true;
                bool ok = true;
                for (std::int32_t k = 0; k < o.b; ++k) {
                    const char* name = str(tbl::kPairs[o.a + 2 * k]);
                    if (const Json* m = find_last(v, name))
                        if (!descend(tbl::kPairs[o.a + 2 * k + 1], *m, name)) {
                            ok = false;
                            if (!out_) return false;
                        }
                }
                return ok;
            }
            case tbl::kPatternProperties: {
                if (!v.is_object()) return true;
                bool ok = true;
                const auto members = unique_members(v);
                for (std::int32_t k = 0; k < o.b; ++k)
                    for (const auto& kv : members)
                        if (rx_search(tbl::kPairs[o.a + 2 * k], *kv.first) &&
                            !descend(tbl::kPairs[o.a + 2 * k + 1], *kv.second, *kv.first)) {
                            ok = false;
                            if (!out_) return false;
                        }
                return ok;
            }
            case tbl::kAdditionalProperties: {
                if (!v.is_object()) return true;
                bool ok = true;
                std::string extras;
                for (const auto& kv : unique_members(v)) {
                    if (declared(n, *kv.first)) continue;
                    if (o.a < 0) {
                        extras += (extras.empty() ? "'" : ", '") + *kv.first + "'";
                        if (!out_) return false;
                    } else if (!descend(o.a, *kv.second, *kv.first)) {
                        ok = false;
                        if (!out_) return false;
                    }
                }
                if (!extras.empty())
                    return fail("additional properties are not allowed (" + extras +
                                " unexpected)");
                return ok;
            }
            case tbl::kRequired: {
                if (!v.is_object()) return true;
                bool ok = true;
                for (std::int32_t k = 0; k < o.b; ++k) {
                    const char* name = str(list(o.a + k));
                    if (!find_last(v, name)) {
                        ok = fail("'" + std::string(name) + "' is a required property");
                        if (!out_) return false;
                    }
                }
                return ok;
            }
            case tbl::kDependentRequired: {
                if (!v.is_object()) return true;
                bool ok = true;
                for (std::int32_t k = 0; k < o.b; ++k) {
                    const std::int32_t* t = tbl::kTriples + o.a + 3 * k;
                    if (!find_last(v, str(t[0]))) continue;
                    for (std::int32_t d = 0; d < t[2]; ++d) {
                        const char* dep = str(list(t[1] + d));
                        if (!find_last(v, dep)) {
                            ok = fail("'" + std::string(dep) + "' is a dependency of '" +
                                      str(t[0]) + "'");
                            if (!out_) return false;
                        }
                    }
                }
                return ok;
            }
            case tbl::kDependentSchemas: {
                if (!v.is_object()) return true;
                bool ok = true;
                for (std::int32_t k = 0; k < o.b; ++k)
                    if (find_last(v, str(tbl::kPairs[o.a + 2 * k])) &&
                        !eval(tbl::kPairs[o.a + 2 * k + 1], v)) {
                        ok = false;
                        if (!out_) return false;
                    }
                return ok;
            }
            case tbl::kPropertyNames: {
                if (!v.is_object()) return true;
                bool ok = true;
                for (const auto& kv : unique_members(v))
                    if (!eval(o.a, Json(*kv.first))) {
                        ok = false;
                        if (!out_) return false;
                    }
                return ok;
            }
            case tbl::kMinProperties:
                if (!v.is_object() || unique_members(v).size() >= static_cast<std::size_t>(o.a))
                    return true;
                return fail(show(v) + " does not have enough properties");
            case tbl::kMaxProperties:
                if (!v.is_object() || unique_members(v).size() <= static_cast<std::size_t>(o.a))
                    return true;
                return fail(show(v) + " has too many properties");
            case tbl::kPrefixItems: {
                if (!v.is_array()) return true;
                bool ok = true;
                for (std::int32_t k = 0; k < o.b && static_cast<std::size_t>(k) < v.size(); ++k)
                    if (!descend(list(o.a + k), v.at(static_cast<std::size_t>(k)),
                                 std::to_string(k))) {
                        ok = false;
                        if (!out_) return false;
                    }
                return ok;
            }
            case tbl::kItems: {
                if (!v.is_array() || v.size() <= static_cast<std::size_t>(o.b)) return true;
                if (o.a < 0)
                    return fail("expected at most " + std::to_string(o.b) + " items, found " +
                                std::to_string(v.size()));
                bool ok = true;
                for (std::size_t i = static_cast<std::size_t>(o.b); i < v.size(); ++i)
                    if (!descend(o.a, v.at(i), std::to_string(i))) {
                        ok = false;
                        if (!out_) return false;
                    }
                return ok;
            }
            case tbl::kContains: {
                if (!v.is_array()) return true;
                std::int32_t matches = 0;
                for (const Json& item : v.elements()) {
                    if (!valid(o.a, item)) continue;
                    if (++matches > o.c && o.c >= 0)
                        return fail("too many items match the given schema (expected at most " +
                                    std::to_string(o.c) + ")");
                }
                if (matches >= o.b) return true;
                return fail(matches == 0
                                ? show(v) + " does not contain items matching the given schema"
                                : "too few items match the given schema (expected at least " +
                                      std::to_string(o.b) + ", " + std::to_string(matches) +
                                      " matched)");
            }
            case tbl::kMinItems:
                if (!v.is_array() || v.size() >= static_cast<std::size_t>(o.a)) return true;
                return fail(show(v) + " is too short (at least " + std::to_string(o.a) +
                            " items)");
            case tbl::kMaxItems:
                if (!v.is_array() || v.size() <= static_cast<std::size_t>(o.a)) return true;
                return fail(show(v) + " is too long (at most " + std::to_string(o.a) + " items)");
            case tbl::kUniqueItems: {
                if (!v.is_array()) return true;
                for (std::size_t i = 0; i < v.size(); ++i)
                    for (std::size_t j = i + 1; j < v.size(); ++j)
                        if (json_equal(v.at(i), v.at(j)))
                            return fail(show(v) + " has non-unique elements");
                return true;
            }
            case tbl::kMinimum:
            case tbl::kMaximum:
            case tbl::kExclusiveMinimum:
            case tbl::kExclusiveMaximum: {
                if (!v.is_number()) return true;
                const double x = v.as_double(), lim = tbl::kNumbers[o.a];
                const bool bad = o.code == tbl::kMinimum            ? x < lim
                                 : o.code == tbl::kMaximum          ? x > lim
                                 : o.code == tbl::kExclusiveMinimum ? x <= lim
                                                                    : x >= lim;
                if (!bad) return true;
                const char* what = o.code == tbl::kMinimum            ? " is less than the minimum of "
                                   : o.code == tbl::kMaximum          ? " is greater than the maximum of "
                                   : o.code == tbl::kExclusiveMinimum ? " is less than or equal to the minimum of "
                                                                      : " is greater than or equal to the maximum of ";
                return fail(show(v) + what + show_number(lim));
            }
            case tbl::kMultipleOf: {
                if (!v.is_number()) return true;
                const double x = v.as_double(), d = tbl::kNumbers[o.a];
                bool bad;
                if (v.type() == Json::Type::Int && std::floor(d) == d) {
                    bad = std::fmod(x, d) != 0.0;
                } else {
                    const double q = x / d;
                    bad = !std::isfinite(q) || std::trunc(q) != q;
                }
                if (!bad) return true;
                return fail(show(v) + " is not a multiple of " + show_number(d));
            }
            case tbl::kMinLength:
                if (!v.is_string() || code_point_count(v.as_string()) >= static_cast<std::size_t>(o.a))
                    return true;
                return fail(show(v) + (o.a == 1 ? " should be non-empty"
                                                : " is too short (at least " +
                                                      std::to_string(o.a) + " characters)"));
            case tbl::kMaxLength:
                if (!v.is_string() || code_point_count(v.as_string()) <= static_cast<std::size_t>(o.a))
                    return true;
                return fail(show(v) + " is too long (at most " + std::to_string(o.a) +
                            " characters)");
            case tbl::kPattern:
                if (!v.is_string() || rx_search(o.a, v.as_string())) return true;
                return fail(show(v) + " does not match '" + tbl::kRxPrograms[o.a].source + "'");
            default:
                return fail("unknown schema opcode " + std::to_string(o.code));
        }
    }
};

// The node of a $defs entry, or -1.
inline std::int32_t definition_node(std::string_view name) {
    for (const tbl::Def& d : tbl::kDefs)
        if (name == d.name) return d.node;
    return -1;
}

// Every schema error of `doc` against the node.
inline std::vector<Error> check_node(std::int32_t node, const Json& doc) {
    std::vector<Error> out;
    Evaluator(&out).eval(node, doc);
    return out;
}

// Every schema error of a manifest.json document against the root schema.
inline std::vector<Error> check_manifest(const Json& manifest) {
    return check_node(tbl::kRoot, manifest);
}

// Every schema error of a payload against the $defs entry `def` (nothing for
// an unknown entry).
inline std::vector<Error> check_definition(std::string_view def, const Json& doc) {
    const std::int32_t node = definition_node(def);
    if (node < 0) return {};
    return check_node(node, doc);
}

}  // namespace schema
}  // namespace detail
}  // namespace qvf

#endif  // QVF_SCHEMA_CHECK_HPP
