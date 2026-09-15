// write_h2o.cpp — write a QVF archive for a (fictional) H2O / RHF / STO-3G run.
//
// Build:  cmake -S .. -B build && cmake --build build
// Run:    ./build/write_h2o [out.qvf]
// Check:  python ../python/qvf_reader.py out.qvf
//
// Mirrors the Python example: the ORCA-relevant sections (structure,
// wavefunction.gto = the GBW-equivalent, spectra, atom properties, SCF trace,
// provenance, citations). Numbers are illustrative.
#include <iostream>
#include <string>

#include "qvf/qvf.hpp"

int main(int argc, char** argv) {
    using namespace qvf;
    std::string out = argc > 1 ? argv[1] : "h2o.qvf";

    QvfWriter w({"my-code", "1.0.0", "h2o/rhf/sto-3g"});

    w.add_structure({
        {"O", 8, {{0.0, 0.0, 0.1173}}},
        {"H", 1, {{0.0, 0.7572, -0.4692}}},
        {"H", 1, {{0.0, -0.7572, -0.4692}}},
    });
    w.add_bonds({{0, 1, 1.0}, {0, 2, 1.0}});

    // STO-3G shells (illustrative). These are the raw published .g94 values,
    // which already apply to N_i-normalized primitives as spec Appendix A.1
    // requires -- no divide needed, flag stays false. Set it true only for
    // engine-native coefficients stored pre-multiplied by N_i
    // (libint / libcint / GBW-style storage).
    WavefunctionGTO wf;
    wf.coeffs_are_libint_normalized = false;
    wf.shells = {
        {0, 0, {130.70932, 23.808861, 6.4436083}, {0.15432897, 0.53532814, 0.44463454}, true},
        {0, 0, {5.0331513, 1.1695961, 0.3803890}, {-0.09996723, 0.39951283, 0.70011547}, true},
        {0, 1, {5.0331513, 1.1695961, 0.3803890}, {0.15591627, 0.60768372, 0.39195739}, true},
        {1, 0, {3.4252509, 0.6239137, 0.1688554}, {0.15432897, 0.53532814, 0.44463454}, true},
        {2, 0, {3.4252509, 0.6239137, 0.1688554}, {0.15432897, 0.53532814, 0.44463454}, true},
    };
    const int n_ao = 7;  // 1 + 1 + 3 + 1 + 1
    wf.mo_coefficients.rows = n_ao;
    wf.mo_coefficients.cols = n_ao;
    wf.mo_coefficients.data.assign(n_ao * n_ao, 0.0);
    for (int i = 0; i < n_ao; ++i) wf.mo_coefficients.data[i * n_ao + i] = 1.0;
    wf.energies = {-20.24, -1.27, -0.62, -0.45, -0.39, 0.60, 0.74};
    wf.occupations = {2, 2, 2, 2, 2, 0, 0};
    w.add_wavefunction_gto(wf);

    Spectrum ir;
    ir.frequencies = {1595.0, 3657.0, 3756.0};
    ir.intensities = {67.0, 5.0, 42.0};
    w.add_spectrum("spectra.ir", ir, "IR (harmonic)");

    w.add_atom_properties({-0.68, 0.34, 0.34}, {-0.41, 0.205, 0.205});

    Json iters = Json::array();
    for (auto rec : {std::array<double, 3>{{1, -74.90, 1e-1}},
                     std::array<double, 3>{{2, -74.962, 1e-3}},
                     std::array<double, 3>{{3, -74.9630, 1e-6}}}) {
        Json it = Json::object();
        it.set("iter", static_cast<int>(rec[0])).set("energy_eh", rec[1])
          .set("diis_error", rec[2]);
        iters.push_back(it);
    }
    w.add_scf_history(iters);

    Json prov = Json::object();
    prov.set("method", "RHF").set("basis", "STO-3G").set("charge", 0)
        .set("multiplicity", 1).set("n_electrons", 10).set("scf_converged", true)
        .set("n_scf_iterations", 3);
    Json e = Json::object();
    e.set("value", -74.9630).set("units", "Eh");
    prov.set("scf_energy", e);
    w.set_provenance(prov);

    w.add_citations("@article{example2026,\n  title = {A calculation},\n"
                    "  author = {Anon},\n  year = {2026}\n}\n");

    std::string path = w.write(out);
    std::cout << "wrote " << path << " with "
              << w.build_manifest().items().back().second.size() << " sections\n";
    return 0;
}
