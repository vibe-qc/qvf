// run_conformance.cpp — the QVF conformance runner for the C++ reference reader.
//
// The C++ counterpart of conformance/run_conformance.py: it implements the
// expected.json check format of conformance/README.md over the positive corpus,
// and the negative format over the negative corpus and the legacy corpus.
//
//   run_conformance CORPUS_DIR [--negative DIR] [--legacy DIR] [--no-schema-check]
//
// Positive corpus (CORPUS_DIR): every archive must validate with no error and
// reproduce its expected.json: the set of section kinds, source.program, and
// each check, which is one of
//   {"manifest_pointer": [...], "equals": V}
//   {"section": S, "member": M, "json_pointer": [...], "equals": V}
//   {"section": S, "member": M, "binary_index": [...], "equals": V}
//   {"section": S, "member": M, "decode": "utf8", "equals": TEXT | "contains": TEXT}
// compared exactly, or as numbers within "tol" when it is present. A binary
// index is decoded from the member's declared little-endian dtype.
//
// Negative corpus (--negative) and legacy corpus (--legacy, archives stamped
// qvf_version 2, which validators check as version 1 with the warning
// W_VERSION_WITHDRAWN): every archive must produce every finding its
// expected.json names, under the "limits" it names, and exactly its codes
// apart from the JSON Schema codes E_SCHEMA and E_PAYLOAD_SCHEMA (a schema
// check also reports E_SCHEMA for several of these archives, as the Python
// validator does); it must be invalid when an expected finding is an error,
// and valid (with its warnings) when every one is a warning. The validator
// runs the JSON Schema check generated from the schema; --no-schema-check
// disables it (the validator then reports W_SCHEMA_SKIPPED), and as in
// run_conformance.py the schema-only expectations are dropped and the verdict
// is judged on the other codes, so an archive that expects only schema codes
// must validate without another error. The same rules as tests/test_reader.cpp.
//
// Prints one PASS or FAIL line per archive and the summary lines of the Python
// runner. Exits 0 when every archive passes, 1 on any failure, 2 on bad usage
// or an empty directory, and 77 (a skipped CTest) when CORPUS_DIR is absent.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "qvf/reader.hpp"

namespace fs = std::filesystem;
using qvf::Tensor;
using qvf::Finding;
using qvf::Json;
using qvf::Limits;
using qvf::Reader;

namespace {

std::string show(const Json& j) {
    try {
        return j.dump(0);
    } catch (const std::exception&) {
        return "<unprintable>";
    }
}

std::string read_text(const fs::path& path) {
    std::ifstream fh(path, std::ios::binary);
    if (!fh) throw std::runtime_error("cannot open " + path.string());
    std::stringstream text;
    text << fh.rdbuf();
    return text.str();
}

// The *.expected.json files of a directory, sorted.
std::vector<fs::path> expected_files(const std::string& dir) {
    const std::string suffix = ".expected.json";
    std::vector<fs::path> out;
    for (const auto& e : fs::directory_iterator(dir)) {
        const std::string name = e.path().filename().string();
        if (name.size() > suffix.size() &&
            name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0)
            out.push_back(e.path());
    }
    std::sort(out.begin(), out.end());
    return out;
}

const qvf::Section& require_section(const Reader& reader, const std::string& id) {
    const qvf::Section* section = reader.section(id);
    if (!section) throw std::runtime_error("section not found: " + id);
    return *section;
}

// --- the positive check format ---------------------------------------------

// Walk a value by a list of object keys (strings) and array indices (numbers;
// a negative index counts from the end, as in the Python runner).
const Json& navigate(const Json& root, const Json& pointer) {
    const Json* cur = &root;
    for (const Json& step : pointer.elements()) {
        if (step.is_string()) {
            if (!cur->is_object() || !cur->has(step.as_string()))
                throw std::runtime_error("pointer step " + show(step) +
                                         " does not exist");
            cur = &cur->at(step.as_string());
        } else if (step.is_number()) {
            if (!cur->is_array())
                throw std::runtime_error("pointer step " + show(step) +
                                         " indexes a non-array");
            int64_t i = step.as_int();
            const int64_t n = static_cast<int64_t>(cur->size());
            if (i < 0) i += n;
            if (i < 0 || i >= n)
                throw std::runtime_error("pointer step " + show(step) +
                                         " is out of range");
            cur = &cur->at(static_cast<size_t>(i));
        } else {
            throw std::runtime_error("pointer step " + show(step) +
                                     " is neither a key nor an index");
        }
    }
    return *cur;
}

size_t dtype_size(qvf::DType dtype) {
    if (dtype == qvf::DType::Int8 || dtype == qvf::DType::UInt8) return 1;
    if (dtype == qvf::DType::Int16 || dtype == qvf::DType::UInt16) return 2;
    if (dtype == qvf::DType::Int32 || dtype == qvf::DType::UInt32 || dtype == qvf::DType::Float32) return 4;
    if (dtype == qvf::DType::Int64 || dtype == qvf::DType::UInt64 || dtype == qvf::DType::Float64) return 8;
    return 0;
}

uint64_t load_le(const uint8_t* p, size_t n) {
    uint64_t v = 0;
    for (size_t i = 0; i < n; ++i) v |= static_cast<uint64_t>(p[i]) << (8 * i);
    return v;
}

// The element of a binary member at a (possibly negative) multi-index, decoded
// from its declared little-endian dtype: an integer for the integer dtypes, a
// double for the float dtypes. uint64 values above 2^63 would wrap; no
// archive holds one.
Json element(const Tensor& bm, const Json& index) {
    const size_t rank = bm.shape.size();
    if (index.size() != rank)
        throw std::runtime_error("index rank " + std::to_string(index.size()) +
                                 " does not match array rank " +
                                 std::to_string(rank));
    size_t flat = 0;
    for (size_t axis = 0; axis < rank; ++axis) {
        const int64_t extent = bm.shape[axis];
        int64_t i = index.at(axis).as_int();
        if (i < 0) i += extent;
        if (i < 0 || i >= extent)
            throw std::runtime_error("index " + show(index.at(axis)) +
                                     " is out of range for axis " +
                                     std::to_string(axis) + " of extent " +
                                     std::to_string(extent));
        flat = flat * static_cast<size_t>(extent) + static_cast<size_t>(i);
    }
    const size_t size = dtype_size(bm.dtype);
    if (size == 0) throw std::runtime_error("unknown tensor dtype");
    if ((flat + 1) * size > bm.bytes.size())
        throw std::runtime_error("binary member is shorter than its shape");
    const uint64_t raw = load_le(bm.bytes.data() + flat * size, size);
    if (bm.dtype == qvf::DType::Int8) return Json(static_cast<long long>(static_cast<int8_t>(raw)));
    if (bm.dtype == qvf::DType::Int16) return Json(static_cast<long long>(static_cast<int16_t>(raw)));
    if (bm.dtype == qvf::DType::Int32) return Json(static_cast<long long>(static_cast<int32_t>(raw)));
    if (bm.dtype == qvf::DType::Int64) return Json(static_cast<long long>(static_cast<int64_t>(raw)));
    if (bm.dtype == qvf::DType::Float32) {
        const uint32_t bits = static_cast<uint32_t>(raw);
        float f = 0.0f;
        std::memcpy(&f, &bits, sizeof f);
        return Json(static_cast<double>(f));
    }
    if (bm.dtype == qvf::DType::Float64) {
        double d = 0.0;
        std::memcpy(&d, &raw, sizeof d);
        return Json(d);
    }
    return Json(static_cast<long long>(raw));   // uint8 .. uint64
}

bool json_equal(const Json& a, const Json& b) {
    if (a.is_number() && b.is_number()) {
        if (a.type() == Json::Type::Int && b.type() == Json::Type::Int)
            return a.as_int() == b.as_int();
        return a.as_double() == b.as_double();
    }
    if (a.type() != b.type()) return false;
    switch (a.type()) {
        case Json::Type::Null: return true;
        case Json::Type::Bool: return a.as_bool() == b.as_bool();
        case Json::Type::String: return a.as_string() == b.as_string();
        case Json::Type::Array:
            if (a.size() != b.size()) return false;
            for (size_t i = 0; i < a.size(); ++i)
                if (!json_equal(a.at(i), b.at(i))) return false;
            return true;
        case Json::Type::Object:
            if (a.size() != b.size()) return false;
            for (const auto& kv : a.items())
                if (!b.has(kv.first) || !json_equal(kv.second, b.at(kv.first)))
                    return false;
            return true;
        default: return false;
    }
}

// Strict UTF-8: no overlong forms, no surrogates, nothing above U+10FFFF.
bool valid_utf8(const std::string& s) {
    size_t i = 0;
    while (i < s.size()) {
        const unsigned char c = static_cast<unsigned char>(s[i]);
        if (c < 0x80) { ++i; continue; }
        size_t len = 0;
        uint32_t cp = 0, least = 0;
        if ((c & 0xE0) == 0xC0) { len = 2; cp = c & 0x1Fu; least = 0x80; }
        else if ((c & 0xF0) == 0xE0) { len = 3; cp = c & 0x0Fu; least = 0x800; }
        else if ((c & 0xF8) == 0xF0) { len = 4; cp = c & 0x07u; least = 0x10000; }
        else return false;
        if (i + len > s.size()) return false;
        for (size_t k = 1; k < len; ++k) {
            const unsigned char cc = static_cast<unsigned char>(s[i + k]);
            if ((cc & 0xC0) != 0x80) return false;
            cp = (cp << 6) | (cc & 0x3Fu);
        }
        if (cp < least || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF))
            return false;
        i += len;
    }
    return true;
}

// Options of every validation: the JSON Schema check unless --no-schema-check.
qvf::ValidationOptions g_options;

// Failure strings for one positive archive (empty = pass).
std::vector<std::string> run_one(const std::string& path, const Json& expected) {
    std::vector<std::string> fails;

    const std::vector<Finding> findings = qvf::validate::run_file(path, qvf::validate::Level::All, Limits{}, g_options).findings;
    if (qvf::has_errors(findings)) {
        for (const Finding& f : findings)
            if (f.severity == Finding::Severity::Error)
                fails.push_back("validation failed: " + f.code + ": " + f.message);
        return fails;
    }

    Reader reader = Reader::open(path);

    // The set of section kinds.
    std::set<std::string> got_kinds;
    const Json& sections = reader.manifest_json().at("sections");
    for (size_t i = 0; i < sections.size(); ++i)
        got_kinds.insert(sections.at(i).at("kind").as_string());
    if (expected.has("kinds")) {
        std::set<std::string> want_kinds;
        for (const Json& k : expected.at("kinds").elements())
            want_kinds.insert(k.as_string());
        if (got_kinds != want_kinds) {
            std::string got, want;
            for (const auto& k : got_kinds) got += (got.empty() ? "" : ", ") + k;
            for (const auto& k : want_kinds) want += (want.empty() ? "" : ", ") + k;
            fails.push_back("kinds mismatch: got [" + got + "], want [" + want + "]");
        }
    }
    if (expected.has("source_program")) {
        const std::string got = reader.manifest_json().at("source").at("program").as_string();
        const std::string want = expected.at("source_program").as_string();
        if (got != want)
            fails.push_back("source.program: got " + show(Json(got)) + ", want " +
                            show(Json(want)));
    }

    if (!expected.has("checks")) return fails;
    for (const Json& chk : expected.at("checks").elements()) {
        const std::string section = chk.has("section") ? chk.at("section").as_string() : "manifest";
        const std::string member = chk.has("member") ? chk.at("member").as_string() : "";
        const std::string label = section + "/" + member;
        try {
            Json got;
            if (chk.has("manifest_pointer")) {
                got = navigate(reader.manifest_json(), chk.at("manifest_pointer"));
            } else if (chk.has("json_pointer")) {
                const Json doc = reader.json(require_section(reader, section), member);
                got = navigate(doc, chk.at("json_pointer"));
            } else if (chk.has("binary_index")) {
                const Tensor bm = reader.tensor(require_section(reader, section), member);
                got = element(bm, chk.at("binary_index"));
            } else if (chk.has("decode") && chk.at("decode").as_string() == "utf8") {
                // An opaque member (citations.references, run.record input/log):
                // the raw bytes as UTF-8 text.
                const std::vector<uint8_t> raw = reader.bytes(require_section(reader, section), member);
                const std::string text(raw.begin(), raw.end());
                if (!valid_utf8(text)) throw std::runtime_error("member is not valid UTF-8");
                if (chk.has("contains")) {
                    if (text.find(chk.at("contains").as_string()) == std::string::npos)
                        fails.push_back("check failed (" + label + "): text does not contain " +
                                        show(chk.at("contains")));
                    continue;
                }
                got = Json(text);
            } else {
                fails.push_back("malformed check (no pointer): " + show(chk));
                continue;
            }
            if (!chk.has("equals")) {
                fails.push_back("malformed check (no equals): " + show(chk));
                continue;
            }
            const Json& want = chk.at("equals");
            bool same = false;
            if (chk.has("tol")) {
                if (!got.is_number() || !want.is_number())
                    throw std::runtime_error("a check with tol needs numbers");
                same = std::fabs(got.as_double() - want.as_double()) <=
                       chk.at("tol").as_double();
            } else {
                same = json_equal(got, want);
            }
            if (!same)
                fails.push_back("check failed (" + label + "): got " + show(got) +
                                ", want " + show(want) +
                                (chk.has("tol") ? " (tol " + show(chk.at("tol")) + ")" : ""));
        } catch (const std::exception& ex) {
            fails.push_back("check errored " + show(chk) + ": " + ex.what());
        }
    }
    return fails;
}

int run_positive(const std::string& dir) {
    const std::vector<fs::path> files = expected_files(dir);
    if (files.empty()) {
        std::cerr << "no *.expected.json found in " << dir << "\n";
        return 2;
    }
    size_t failed = 0;
    for (const fs::path& ef : files) {
        std::string archive = ef.filename().string();
        std::vector<std::string> fails;
        size_t n_checks = 0;
        try {
            const Json expected = Json::parse(read_text(ef));
            archive = expected.at("archive").as_string();
            n_checks = expected.has("checks") ? expected.at("checks").size() : 0;
            const fs::path path = fs::path(dir) / archive;
            if (!fs::exists(path)) fails.push_back("archive missing");
            else fails = run_one(path.string(), expected);
        } catch (const std::exception& ex) {
            fails.push_back(std::string("runner error: ") + ex.what());
        }

        if (!fails.empty()) {
            ++failed;
            std::cout << "FAIL " << archive << "\n";
            for (const std::string& f : fails) std::cout << "     - " << f << "\n";
        } else {
            std::cout << "PASS " << archive << "  (" << n_checks << " checks)\n";
        }
    }
    std::cout << "\nconformance: " << files.size() - failed << "/" << files.size()
              << " archives passed\n";
    return failed != 0 ? 1 : 0;
}

// --- the negative format -----------------------------------------------------

bool set_limit(Limits& lim, const std::string& key, const Json& v) {
    if (!v.is_number()) return false;
    if (key == "max_member_bytes") lim.max_member_bytes = static_cast<uint64_t>(v.as_int());
    else if (key == "max_total_bytes") lim.max_total_bytes = static_cast<uint64_t>(v.as_int());
    else if (key == "max_ratio") lim.max_ratio = v.as_double();
    else if (key == "ratio_exempt_bytes") lim.ratio_exempt_bytes = static_cast<uint64_t>(v.as_int());
    else if (key == "max_json_bytes") lim.max_json_bytes = static_cast<uint64_t>(v.as_int());
    else if (key == "max_json_depth") lim.max_json_depth = static_cast<size_t>(v.as_int());
    else return false;
    return true;
}

std::string describe(const std::vector<Finding>& fs) {
    std::string s;
    for (const Finding& f : fs) s += "\n    " + f.code + " [" + f.where + "] " + f.message;
    return s;
}

bool has_code(const std::vector<Finding>& fs, const std::string& code,
              Finding::Severity sev) {
    for (const Finding& f : fs)
        if (f.code == code && f.severity == sev) return true;
    return false;
}

bool is_schema_code(const std::string& code) {
    return code == "E_SCHEMA" || code == "E_PAYLOAD_SCHEMA" || code == "W_SCHEMA_SKIPPED";
}

// Run one archive in the negative format. `schema_only` is set when the
// schema check was skipped and every expectation was a schema-only code, so
// the archive is accepted without errors.
std::vector<std::string> run_negative_one(const std::string& path, const Json& expected,
                                          bool& schema_only) {
    std::vector<std::string> problems;
    schema_only = false;
    Limits lim;
    if (expected.has("limits"))
        for (const auto& kv : expected.at("limits").items())
            if (!set_limit(lim, kv.first, kv.second))
                problems.push_back("unknown limit '" + kv.first + "'");
    const std::vector<Finding> findings = qvf::validate::run_file(path, qvf::validate::Level::All, lim, g_options).findings;
    const bool skipped = has_code(findings, "W_SCHEMA_SKIPPED", Finding::Severity::Warning);
    std::set<std::string> got, want;
    bool other_errors = false;
    for (const Finding& f : findings) {
        if (!is_schema_code(f.code)) got.insert(f.code);
        // Without the schema check, a semantic payload rule may still report
        // E_PAYLOAD_SCHEMA (a spectrum's array lengths); judge the verdict on
        // the codes this validator is held to.
        if (f.severity == Finding::Severity::Error && !(skipped && is_schema_code(f.code)))
            other_errors = true;
    }
    bool expects_error = false;
    for (const Json& w : expected.at("expect").elements()) {
        const std::string code = w.at("code").as_string();
        if (skipped && is_schema_code(code)) continue;
        const bool is_error = w.at("severity").as_string() == "error";
        expects_error = expects_error || is_error;
        if (!is_schema_code(code)) want.insert(code);
        if (!has_code(findings, code,
                      is_error ? Finding::Severity::Error : Finding::Severity::Warning))
            problems.push_back("missing " + code);
    }
    schema_only = skipped && want.empty() && !expects_error && expected.at("expect").size() != 0;
    if (other_errors != expects_error)
        problems.push_back(expects_error ? "validator reported no error"
                                         : "validator reported an unexpected error");
    if (got != want)
        problems.push_back("codes differ from the expected set:" + describe(findings));
    return problems;
}

int run_negative(const std::string& dir, const std::string& label) {
    const std::vector<fs::path> files = expected_files(dir);
    if (files.empty()) {
        std::cerr << "no *.expected.json found in " << dir << "\n";
        return 2;
    }
    size_t failed = 0;
    for (const fs::path& ef : files) {
        std::string archive = ef.filename().string();
        std::vector<std::string> problems;
        bool schema_only = false;
        std::string codes;
        try {
            const Json expected = Json::parse(read_text(ef));
            archive = expected.at("archive").as_string();
            for (const Json& w : expected.at("expect").elements())
                codes += (codes.empty() ? "" : ", ") + w.at("code").as_string();
            const fs::path path = fs::path(dir) / archive;
            if (!fs::exists(path)) problems.push_back("archive missing");
            else problems = run_negative_one(path.string(), expected, schema_only);
        } catch (const std::exception& ex) {
            problems.push_back(std::string("runner error: ") + ex.what());
        }
        if (!problems.empty()) {
            ++failed;
            std::cout << "FAIL " << archive << "\n";
            for (const std::string& p : problems) std::cout << "     - " << p << "\n";
        } else {
            std::cout << "PASS " << archive << "  (" << codes << ")"
                      << (schema_only ? "  [schema-only: accepted without errors]" : "")
                      << "\n";
        }
    }
    // The legacy archives are valid with a warning today, so they are
    // "judged", as the Python runner says.
    const char* verdict = label == "negative" ? "rejected" : "judged";
    std::cout << "\n" << label << " conformance: " << files.size() - failed << "/"
              << files.size() << " archives " << verdict << " as expected\n";
    return failed != 0 ? 1 : 0;
}

int usage() {
    std::cerr << "usage: run_conformance CORPUS_DIR [--negative DIR] [--legacy DIR] "
                 "[--no-schema-check]\n";
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    std::string corpus, negative, legacy;
    bool have_negative = false, have_legacy = false;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--negative" && i + 1 < argc) { negative = argv[++i]; have_negative = true; }
        else if (a == "--legacy" && i + 1 < argc) { legacy = argv[++i]; have_legacy = true; }
        else if (a == "--no-schema-check") g_options.schema_check = false;
        else if (!a.empty() && a[0] == '-') return usage();
        else if (corpus.empty()) corpus = a;
        else return usage();
    }
    if (corpus.empty()) return usage();
    if (!fs::is_directory(corpus)) {
        std::cout << "conformance corpus not found at " << corpus << "; skipped\n";
        return 77;
    }
    for (const std::string& dir : {negative, legacy})
        if (!dir.empty() && !fs::is_directory(dir)) {
            std::cerr << "not a directory: " << dir << "\n";
            return 2;
        }

    if (!g_options.schema_check)
        std::cout << "JSON Schema check disabled (--no-schema-check)\n\n";
    int rc = run_positive(corpus);
    if (have_negative) {
        std::cout << "\n";
        const int rc_neg = run_negative(negative, "negative");
        rc = rc != 0 ? rc : rc_neg;
    }
    if (have_legacy) {
        std::cout << "\n";
        const int rc_leg = run_negative(legacy, "legacy");
        rc = rc != 0 ? rc : rc_leg;
    }
    return rc;
}
