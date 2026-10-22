// write_single_header.cpp — prove the amalgamated single header works standalone.
//
// This TU is compiled with ONLY qvf_single.hpp on the include path (no cpp/
// sources, no cpp/include, no cpp/src) — see CMakeLists. It defines
// QVF_IMPLEMENTATION so the implementation is emitted here.
//
// Run:  ./write_single_header [out.qvf]   then validate with qvf_reader.py
#define QVF_IMPLEMENTATION
#include "qvf_single.hpp"

#include <iostream>

int main(int argc, char** argv) {
    using namespace qvf;
    std::string out = argc > 1 ? argv[1] : "single.qvf";

    QvfWriter w({"single-header-demo", "1.0", "h2o/rhf"});
    w.add_structure({
        {"O", 8, {{0.0, 0.0, 0.1173}}},
        {"H", 1, {{0.0, 0.7572, -0.4692}}},
        {"H", 1, {{0.0, -0.7572, -0.4692}}},
    });
    Spectrum ir;
    ir.frequencies = {1595.0, 3657.0, 3756.0};
    ir.intensities = {67.0, 5.0, 42.0};
    w.add_spectrum("spectra.ir", ir);
    w.add_atom_properties({-0.68, 0.34, 0.34});
    // An object-shaped spectrum via the Json builder (exercises the impl block).
    Json epr = Json::object();
    epr.set("g_tensor", Json::object().set("isotropic", 2.0044));
    w.add_spectrum("spectra.epr", epr);

    std::string path = w.write(out);
    std::cout << "wrote " << path << " via qvf_single.hpp\n";

    // Read it back through the reader that ships in the same single header.
    Reader reader = Reader::open(path);
    const auto report = reader.validate();
    const bool ok = report.ok;
    const Section* section = reader.section("structure");
    if (!section) return 1;
    Json st = reader.json(*section, "structure");
    std::cout << "read back " << report.n_sections << " sections, "
              << "first atom " << st.at("atoms").at(0).at("symbol").as_string()
              << ", valid=" << (ok ? "yes" : "no") << "\n";
    const auto typed = reader.get<kinds::Structure>("structure");
    if (typed.structure.atoms.size() != 3) return 1;
    Writer copy({"single-header-demo", "1.0", "typed-copy"});
    for (const auto& s : *reader.manifest().sections) kinds::copy_section(reader, s, copy);
    Reader roundtrip = Reader::from_bytes(copy.to_bytes());
    std::cout << "typed copy valid=" << (roundtrip.validate().ok ? "yes" : "no") << "\n";
    return ok && roundtrip.validate().ok ? 0 : 1;
}
