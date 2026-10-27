// read_qvf.cpp — qvf-inspect, using the typed Reader/validation facade.
//
// Doubles as a cross-language check: it reads archives written by *any* producer
// (e.g. the Python reference writer, whose zipfile uses dynamic-Huffman DEFLATE),
// proving the C++ ZIP reader + INFLATE + JSON parser + sha256 verify interop.
//
// Every finding is printed as "CODE: message [where]" with the stable codes of
// spec Appendix B. Exits 0 when there is no error (warnings are allowed), 1 on
// any error, 2 on bad usage.
//
// Run:  ./qvf-inspect file.qvf (read_qvf is kept as an executable alias)
#include <iostream>
#include <string>
#include <vector>

#include "qvf/reader.hpp"

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: qvf-inspect FILE.qvf\n";
        return 2;
    }
    const std::string path = argv[1];
    std::cout << "QVF validation: " << path << "\n";

    // The input adapter reports malformed ZIP/manifest input as findings too.
    const qvf::validate::Report report = qvf::validate::run_file(path);
    const bool ok = report.ok;

    if (ok) {
        try {
            qvf::Reader reader = qvf::Reader::open(path);
            const qvf::Manifest& manifest = reader.manifest();
            std::cout << "  QVF v" << manifest.qvf_version.value_or(0) << " from "
                      << (manifest.source ? manifest.source->program : "") << "\n";
            std::cout << "  sections: " << report.n_sections << "\n";
            if (manifest.sections)
                for (const auto& section : *manifest.sections)
                    std::cout << "    - " << section.id.value_or("") << "  ["
                              << section.kind.value_or("") << "]\n";
        } catch (const std::exception& e) {
            std::cerr << "error: " << e.what() << "\n";
            return 1;
        }
    }

    for (const auto& f : report.findings)
        std::cout << "  " << f.code << ": " << f.message << "  [" << f.where << "]\n";
    std::cout << (ok ? "  OK (all members sha256-verified)\n" : "  FAILED\n");
    return ok ? 0 : 1;
}
