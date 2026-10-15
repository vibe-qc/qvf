// read_qvf.cpp — validate a .qvf with the C++ reader and print a summary.
//
// Doubles as a cross-language check: it reads archives written by *any* producer
// (e.g. the Python reference writer, whose zipfile uses dynamic-Huffman DEFLATE),
// proving the C++ ZIP reader + INFLATE + JSON parser + sha256 verify interop.
//
// Every finding is printed as "CODE: message [where]" with the stable codes of
// spec Appendix B. Exits 0 when there is no error (warnings are allowed), 1 on
// any error, 2 on bad usage.
//
// Run:  ./read_qvf file.qvf
#include <iostream>
#include <string>
#include <vector>

#include "qvf/qvf_reader.hpp"

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: read_qvf FILE.qvf\n";
        return 2;
    }
    const std::string path = argv[1];
    std::cout << "QVF validation: " << path << "\n";

    // validate_file() never throws on malformed input: an archive that cannot
    // even be opened (bad ZIP, duplicate entries, broken manifest) is reported
    // as findings too.
    std::vector<qvf::Finding> findings = qvf::QvfReader::validate_file(path);
    const bool ok = !qvf::has_errors(findings);

    if (ok) {
        try {
            qvf::QvfReader reader = qvf::QvfReader::open(path);
            const qvf::Json& m = reader.manifest();
            std::cout << "  QVF v" << m.at("qvf_version").as_int() << " from "
                      << m.at("source").at("program").as_string() << "\n";
            const qvf::Json& secs = reader.sections();
            std::cout << "  sections: " << secs.size() << "\n";
            for (size_t i = 0; i < secs.size(); ++i) {
                const qvf::Json& s = secs.at(i);
                std::cout << "    - " << s.at("id").as_string() << "  ["
                          << s.at("kind").as_string() << "]\n";
            }
        } catch (const std::exception& e) {
            std::cerr << "error: " << e.what() << "\n";
            return 1;
        }
    }

    for (const auto& f : findings)
        std::cout << "  " << f.code << ": " << f.message << "  [" << f.where << "]\n";
    std::cout << (ok ? "  OK (all members sha256-verified)\n" : "  FAILED\n");
    return ok ? 0 : 1;
}
