// read_qvf.cpp — open a .qvf with the C++ reader, validate it, print a summary.
//
// Doubles as a cross-language check: it reads archives written by *any* producer
// (e.g. the Python reference writer, whose zipfile uses dynamic-Huffman DEFLATE),
// proving the C++ ZIP reader + INFLATE + JSON parser + sha256 verify interop.
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
    try {
        qvf::QvfReader reader = qvf::QvfReader::open(argv[1]);
        const qvf::Json& m = reader.manifest();
        std::cout << "QVF v" << m.at("qvf_version").as_int() << " from "
                  << m.at("source").at("program").as_string() << "\n";

        std::vector<std::string> errors;
        bool ok = reader.validate(errors);
        const qvf::Json& secs = reader.sections();
        std::cout << "sections: " << secs.size() << "\n";
        for (size_t i = 0; i < secs.size(); ++i) {
            const qvf::Json& s = secs.at(i);
            std::cout << "  - " << s.at("id").as_string() << "  ["
                      << s.at("kind").as_string() << "]\n";
        }
        if (!ok) {
            std::cout << "INVALID:\n";
            for (const auto& e : errors) std::cout << "  ! " << e << "\n";
            return 1;
        }
        std::cout << "OK (all members sha256-verified)\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
