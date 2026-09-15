// qvf/json.hpp — a tiny, dependency-free JSON value type + emitter.
//
// Just enough JSON to build QVF manifests and member payloads: null, bool,
// integer, double, string, ordered object, and array. Objects preserve
// insertion order. Numbers emit as round-trippable JSON (integers without a
// decimal point; doubles via %.17g). This is deliberately minimal — it is a
// *writer*, not a parser.
//
// License: Apache-2.0.
#ifndef QVF_JSON_HPP
#define QVF_JSON_HPP

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace qvf {

class Json {
public:
    enum class Type { Null, Bool, Int, Double, String, Array, Object, Raw };

    Json() : type_(Type::Null) {}
    Json(std::nullptr_t) : type_(Type::Null) {}
    Json(bool b) : type_(Type::Bool), bool_(b) {}
    Json(int v) : type_(Type::Int), int_(v) {}
    Json(long v) : type_(Type::Int), int_(v) {}
    Json(long long v) : type_(Type::Int), int_(v) {}
    Json(unsigned v) : type_(Type::Int), int_(static_cast<int64_t>(v)) {}
    Json(unsigned long v) : type_(Type::Int), int_(static_cast<int64_t>(v)) {}
    Json(double v) : type_(Type::Double), dbl_(v) {}
    Json(const char* s) : type_(Type::String), str_(s) {}
    Json(std::string s) : type_(Type::String), str_(std::move(s)) {}

    // Homogeneous convenience constructors.
    static Json array() { Json j; j.type_ = Type::Array; return j; }
    static Json object() { Json j; j.type_ = Type::Object; return j; }

    // A pre-serialized JSON fragment emitted verbatim. Used by the C ABI to
    // accept JSON payloads as strings without shipping a parser. The caller is
    // responsible for the string being valid JSON.
    static Json raw(std::string s) {
        Json j;
        j.type_ = Type::Raw;
        j.str_ = std::move(s);
        return j;
    }

    static Json from_doubles(const std::vector<double>& v) {
        Json j = array();
        for (double x : v) j.arr_.push_back(Json(x));
        return j;
    }
    static Json from_ints(const std::vector<int>& v) {
        Json j = array();
        for (int x : v) j.arr_.push_back(Json(x));
        return j;
    }
    static Json from_strings(const std::vector<std::string>& v) {
        Json j = array();
        for (const auto& s : v) j.arr_.push_back(Json(s));
        return j;
    }

    // Array building.
    Json& push_back(Json value) {
        ensure(Type::Array);
        arr_.push_back(std::move(value));
        return *this;
    }

    // Object building (ordered). set() overwrites an existing key in place.
    Json& set(const std::string& key, Json value) {
        ensure(Type::Object);
        for (auto& kv : obj_) {
            if (kv.first == key) { kv.second = std::move(value); return *this; }
        }
        obj_.emplace_back(key, std::move(value));
        return *this;
    }
    bool has(const std::string& key) const {
        if (type_ != Type::Object) return false;
        for (const auto& kv : obj_) if (kv.first == key) return true;
        return false;
    }

    Type type() const { return type_; }
    bool is_null() const { return type_ == Type::Null; }

    // Read-back accessors (used by the writer to merge root blocks / iterate
    // vendor members). Throw on a type mismatch.
    const std::vector<std::pair<std::string, Json>>& items() const {
        if (type_ != Type::Object)
            throw std::runtime_error("qvf::Json::items() on non-object");
        return obj_;
    }
    const std::vector<Json>& elements() const {
        if (type_ != Type::Array)
            throw std::runtime_error("qvf::Json::elements() on non-array");
        return arr_;
    }
    size_t size() const {
        if (type_ == Type::Object) return obj_.size();
        if (type_ == Type::Array) return arr_.size();
        return 0;
    }

    std::string dump(int indent = 2) const {
        std::string out;
        dump_to(out, indent, 0);
        return out;
    }

    // --- read accessors (for the reader / parsed JSON) -------------------
    bool is_bool() const { return type_ == Type::Bool; }
    bool is_number() const { return type_ == Type::Int || type_ == Type::Double; }
    bool is_string() const { return type_ == Type::String; }
    bool is_array() const { return type_ == Type::Array; }
    bool is_object() const { return type_ == Type::Object; }

    bool as_bool() const {
        if (type_ != Type::Bool) throw std::runtime_error("qvf::Json not a bool");
        return bool_;
    }
    double as_double() const {
        if (type_ == Type::Double) return dbl_;
        if (type_ == Type::Int) return static_cast<double>(int_);
        throw std::runtime_error("qvf::Json not a number");
    }
    int64_t as_int() const {
        if (type_ == Type::Int) return int_;
        if (type_ == Type::Double) return static_cast<int64_t>(dbl_);
        throw std::runtime_error("qvf::Json not a number");
    }
    const std::string& as_string() const {
        if (type_ != Type::String && type_ != Type::Raw)
            throw std::runtime_error("qvf::Json not a string");
        return str_;
    }

    bool contains(const std::string& key) const { return has(key); }
    // Object member access (throws if absent / not an object).
    const Json& at(const std::string& key) const {
        if (type_ != Type::Object)
            throw std::runtime_error("qvf::Json::at(key) on non-object");
        for (const auto& kv : obj_) if (kv.first == key) return kv.second;
        throw std::runtime_error("qvf::Json: missing key '" + key + "'");
    }
    // Array element access (throws on out-of-range / not an array).
    const Json& at(size_t i) const {
        if (type_ != Type::Array)
            throw std::runtime_error("qvf::Json::at(index) on non-array");
        if (i >= arr_.size()) throw std::runtime_error("qvf::Json index out of range");
        return arr_[i];
    }
    const Json& operator[](const std::string& key) const { return at(key); }
    const Json& operator[](size_t i) const { return at(i); }

    // Parse a UTF-8 JSON document. Throws std::runtime_error on malformed input.
    static Json parse(const std::string& text) {
        size_t pos = 0;
        Json v = parse_value(text, pos);
        skip_ws(text, pos);
        if (pos != text.size())
            throw std::runtime_error("qvf::Json::parse: trailing content");
        return v;
    }

private:
    // --- parser ----------------------------------------------------------
    static void skip_ws(const std::string& s, size_t& p) {
        while (p < s.size() &&
               (s[p] == ' ' || s[p] == '\t' || s[p] == '\n' || s[p] == '\r'))
            ++p;
    }
    static Json parse_value(const std::string& s, size_t& p) {
        skip_ws(s, p);
        if (p >= s.size()) throw std::runtime_error("qvf::Json::parse: unexpected end");
        char c = s[p];
        if (c == '{') return parse_object(s, p);
        if (c == '[') return parse_array(s, p);
        if (c == '"') return Json(parse_string(s, p));
        if (c == 't' || c == 'f') return parse_bool(s, p);
        if (c == 'n') { expect(s, p, "null"); return Json(nullptr); }
        return parse_number(s, p);
    }
    static void expect(const std::string& s, size_t& p, const char* lit) {
        for (const char* q = lit; *q; ++q, ++p)
            if (p >= s.size() || s[p] != *q)
                throw std::runtime_error("qvf::Json::parse: bad literal");
    }
    static Json parse_bool(const std::string& s, size_t& p) {
        if (s[p] == 't') { expect(s, p, "true"); return Json(true); }
        expect(s, p, "false");
        return Json(false);
    }
    static std::string parse_string(const std::string& s, size_t& p) {
        ++p;  // opening quote
        std::string out;
        while (p < s.size()) {
            char c = s[p++];
            if (c == '"') return out;
            if (c == '\\') {
                if (p >= s.size()) break;
                char e = s[p++];
                switch (e) {
                    case '"': out.push_back('"'); break;
                    case '\\': out.push_back('\\'); break;
                    case '/': out.push_back('/'); break;
                    case 'b': out.push_back('\b'); break;
                    case 'f': out.push_back('\f'); break;
                    case 'n': out.push_back('\n'); break;
                    case 'r': out.push_back('\r'); break;
                    case 't': out.push_back('\t'); break;
                    case 'u': {
                        if (p + 4 > s.size())
                            throw std::runtime_error("qvf::Json::parse: bad \\u");
                        unsigned cp = 0;
                        for (int i = 0; i < 4; ++i) {
                            char h = s[p++];
                            cp <<= 4;
                            if (h >= '0' && h <= '9') cp |= unsigned(h - '0');
                            else if (h >= 'a' && h <= 'f') cp |= unsigned(h - 'a' + 10);
                            else if (h >= 'A' && h <= 'F') cp |= unsigned(h - 'A' + 10);
                            else throw std::runtime_error("qvf::Json::parse: bad hex");
                        }
                        encode_utf8(out, cp);  // surrogate pairs left as-is (rare in QVF)
                        break;
                    }
                    default: throw std::runtime_error("qvf::Json::parse: bad escape");
                }
            } else {
                out.push_back(c);
            }
        }
        throw std::runtime_error("qvf::Json::parse: unterminated string");
    }
    static void encode_utf8(std::string& out, unsigned cp) {
        if (cp < 0x80) out.push_back(static_cast<char>(cp));
        else if (cp < 0x800) {
            out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else {
            out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        }
    }
    static Json parse_number(const std::string& s, size_t& p) {
        size_t start = p;
        bool is_double = false;
        if (p < s.size() && (s[p] == '-' || s[p] == '+')) ++p;
        while (p < s.size()) {
            char c = s[p];
            if (c >= '0' && c <= '9') { ++p; }
            else if (c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-') {
                is_double = true; ++p;
            } else break;
        }
        std::string num = s.substr(start, p - start);
        if (num.empty()) throw std::runtime_error("qvf::Json::parse: bad number");
        if (is_double) return Json(std::stod(num));
        try {
            return Json(static_cast<long long>(std::stoll(num)));
        } catch (...) {
            return Json(std::stod(num));
        }
    }
    static Json parse_array(const std::string& s, size_t& p) {
        ++p;  // '['
        Json a = array();
        skip_ws(s, p);
        if (p < s.size() && s[p] == ']') { ++p; return a; }
        while (true) {
            a.arr_.push_back(parse_value(s, p));
            skip_ws(s, p);
            if (p >= s.size()) throw std::runtime_error("qvf::Json::parse: bad array");
            if (s[p] == ',') { ++p; continue; }
            if (s[p] == ']') { ++p; break; }
            throw std::runtime_error("qvf::Json::parse: expected , or ]");
        }
        return a;
    }
    static Json parse_object(const std::string& s, size_t& p) {
        ++p;  // '{'
        Json o = object();
        skip_ws(s, p);
        if (p < s.size() && s[p] == '}') { ++p; return o; }
        while (true) {
            skip_ws(s, p);
            if (p >= s.size() || s[p] != '"')
                throw std::runtime_error("qvf::Json::parse: expected key");
            std::string key = parse_string(s, p);
            skip_ws(s, p);
            if (p >= s.size() || s[p] != ':')
                throw std::runtime_error("qvf::Json::parse: expected :");
            ++p;
            o.obj_.emplace_back(key, parse_value(s, p));
            skip_ws(s, p);
            if (p >= s.size()) throw std::runtime_error("qvf::Json::parse: bad object");
            if (s[p] == ',') { ++p; continue; }
            if (s[p] == '}') { ++p; break; }
            throw std::runtime_error("qvf::Json::parse: expected , or }");
        }
        return o;
    }


    void ensure(Type t) {
        if (type_ == Type::Null) type_ = t;
        if (type_ != t) throw std::runtime_error("qvf::Json type mismatch");
    }

    static void emit_string(std::string& out, const std::string& s) {
        out.push_back('"');
        for (unsigned char c : s) {
            switch (c) {
                case '"': out += "\\\""; break;
                case '\\': out += "\\\\"; break;
                case '\b': out += "\\b"; break;
                case '\f': out += "\\f"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (c < 0x20) {
                        char buf[8];
                        std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                        out += buf;
                    } else {
                        out.push_back(static_cast<char>(c));  // UTF-8 passthrough
                    }
            }
        }
        out.push_back('"');
    }

    static void emit_double(std::string& out, double v) {
        if (std::isnan(v) || std::isinf(v))
            throw std::runtime_error("qvf::Json cannot emit NaN/Inf");
        char buf[32];
        std::snprintf(buf, sizeof(buf), "%.17g", v);
        // Ensure it reads back as a float (has '.', 'e', 'n', or 'i').
        std::string s(buf);
        if (s.find_first_of(".eEnN") == std::string::npos) s += ".0";
        out += s;
    }

    void newline(std::string& out, int indent, int depth) const {
        if (indent <= 0) return;
        out.push_back('\n');
        out.append(static_cast<size_t>(indent) * depth, ' ');
    }

    void dump_to(std::string& out, int indent, int depth) const {
        switch (type_) {
            case Type::Null: out += "null"; break;
            case Type::Bool: out += bool_ ? "true" : "false"; break;
            case Type::Int: out += std::to_string(int_); break;
            case Type::Double: emit_double(out, dbl_); break;
            case Type::String: emit_string(out, str_); break;
            case Type::Raw: out += str_; break;  // pre-serialized, verbatim
            case Type::Array: {
                if (arr_.empty()) { out += "[]"; break; }
                out.push_back('[');
                for (size_t i = 0; i < arr_.size(); ++i) {
                    newline(out, indent, depth + 1);
                    arr_[i].dump_to(out, indent, depth + 1);
                    if (i + 1 < arr_.size()) out.push_back(',');
                }
                newline(out, indent, depth);
                out.push_back(']');
                break;
            }
            case Type::Object: {
                if (obj_.empty()) { out += "{}"; break; }
                out.push_back('{');
                for (size_t i = 0; i < obj_.size(); ++i) {
                    newline(out, indent, depth + 1);
                    emit_string(out, obj_[i].first);
                    out += indent > 0 ? ": " : ":";
                    obj_[i].second.dump_to(out, indent, depth + 1);
                    if (i + 1 < obj_.size()) out.push_back(',');
                }
                newline(out, indent, depth);
                out.push_back('}');
                break;
            }
        }
    }

    Type type_;
    bool bool_ = false;
    int64_t int_ = 0;
    double dbl_ = 0.0;
    std::string str_;
    std::vector<Json> arr_;
    std::vector<std::pair<std::string, Json>> obj_;
};

}  // namespace qvf

#endif  // QVF_JSON_HPP
