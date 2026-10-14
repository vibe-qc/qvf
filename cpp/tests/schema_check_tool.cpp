// schema_check_tool.cpp — drive the generated C++ schema checker from a test.
//
// Used by python/tests/test_schema_checker_parity.py to compare the checker
// and the validator with the Python reference (jsonschema), document by
// document and archive by archive. Not an example and not installed; the
// JavaScript twin is js/scripts/schema-check.mjs.
//
// Reads one JSON object per line from stdin and prints one JSON line per input:
//   {"def": NAME, "doc": VALUE}
//       NAME null checks VALUE against the root schema (as manifest.json),
//       otherwise against $defs/NAME. Prints an array of [pointer, message]
//       pairs, one per schema error, in the order the checker reports them.
//   {"archive": PATH, "limits": {...} | null, "schema_check": true | false}
//       Validates the archive (limits as in the negative corpus) and prints
//       its findings as an array of {"severity", "code", "where", "message"}.
// A request that cannot be served prints {"error": MESSAGE}.
//
// License: Apache-2.0.
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

#include "qvf/json.hpp"
#include "qvf/qvf_reader.hpp"
#include "qvf_schema_check.hpp"

namespace {

qvf::Json check_document(const qvf::Json& req) {
    const qvf::Json& def = req.at("def");
    const qvf::Json& doc = req.at("doc");
    const std::vector<qvf::detail::schema::Error> errors =
        def.is_null() ? qvf::detail::schema::check_manifest(doc)
                      : qvf::detail::schema::check_definition(def.as_string(), doc);
    qvf::Json out = qvf::Json::array();
    for (const auto& e : errors) {
        qvf::Json pair = qvf::Json::array();
        pair.push_back(e.pointer);
        pair.push_back(e.message);
        out.push_back(std::move(pair));
    }
    return out;
}

qvf::Json validate_archive(const qvf::Json& req) {
    qvf::Limits lim;
    if (req.has("limits") && req.at("limits").is_object()) {
        for (const auto& kv : req.at("limits").items()) {
            const qvf::Json& v = kv.second;
            if (kv.first == "max_member_bytes") lim.max_member_bytes = static_cast<uint64_t>(v.as_int());
            else if (kv.first == "max_total_bytes") lim.max_total_bytes = static_cast<uint64_t>(v.as_int());
            else if (kv.first == "max_ratio") lim.max_ratio = v.as_double();
            else if (kv.first == "ratio_exempt_bytes") lim.ratio_exempt_bytes = static_cast<uint64_t>(v.as_int());
            else if (kv.first == "max_json_bytes") lim.max_json_bytes = static_cast<uint64_t>(v.as_int());
            else if (kv.first == "max_json_depth") lim.max_json_depth = static_cast<size_t>(v.as_int());
            else throw std::runtime_error("unknown limit " + kv.first);
        }
    }
    qvf::ValidationOptions opts;
    opts.schema_check = !req.has("schema_check") || req.at("schema_check").as_bool();
    qvf::Json out = qvf::Json::array();
    for (const qvf::Finding& f :
         qvf::QvfReader::validate_file(req.at("archive").as_string(), lim, opts)) {
        qvf::Json o = qvf::Json::object();
        o.set("severity", f.severity == qvf::Finding::Severity::Error ? "error" : "warning");
        o.set("code", f.code);
        o.set("where", f.where);
        o.set("message", f.message);
        out.push_back(std::move(o));
    }
    return out;
}

}  // namespace

int main(int argc, char**) {
    if (argc != 1) {
        std::cerr << "usage: qvf_schema_check < requests (one JSON object per line)\n";
        return 2;
    }
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        try {
            const qvf::Json req = qvf::Json::parse(line, 1024);
            const qvf::Json out = req.has("archive") ? validate_archive(req) : check_document(req);
            std::cout << out.dump(0) << "\n";
        } catch (const std::exception& ex) {
            qvf::Json err = qvf::Json::object();
            err.set("error", std::string(ex.what()));
            std::cout << err.dump(0) << "\n";
        }
    }
    return 0;
}
