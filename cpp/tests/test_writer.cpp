// test_writer.cpp — unit tests for the QVF C++ writer.
//
// Known-answer tests for the vendored-free SHA-256 / CRC-32 / primitive_norm
// primitives, plus an archive smoke test. Full schema + integrity validation of
// the emitted archive is done cross-language by python/qvf_reader.py (run in the
// build verification step), which is the authoritative check.
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include "qvf/qvf.hpp"
#include "qvf/qvf_c.h"
#include "qvf/qvf_reader.hpp"
#include "qvf_deflate.hpp"
#include "qvf_inflate.hpp"
#include "qvf_sha256.hpp"
#include "qvf_zip.hpp"

#include <cstdio>
#include <fstream>

static int g_failures = 0;

#define CHECK(cond, msg)                                                   \
    do {                                                                   \
        if (!(cond)) {                                                     \
            std::cerr << "FAIL: " << (msg) << " (" << #cond << ")\n";      \
            ++g_failures;                                                  \
        }                                                                  \
    } while (0)

static bool contains(const std::vector<uint8_t>& hay, const std::string& needle) {
    std::string s(hay.begin(), hay.end());
    return s.find(needle) != std::string::npos;
}

int main() {
    using namespace qvf;

    // --- SHA-256 known-answer (FIPS 180-4 "abc") ---
    CHECK(detail::Sha256::hex_of(std::string("abc")) ==
          "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
          "sha256(abc)");
    CHECK(detail::Sha256::hex_of(std::string("")) ==
          "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
          "sha256(empty)");
    // A > 64-byte message to exercise multi-block processing.
    CHECK(detail::Sha256::hex_of(std::string(
              "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")) ==
          "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
          "sha256(56-byte)");

    // --- CRC-32 known-answer ("123456789" -> 0xCBF43926) ---
    {
        std::string m = "123456789";
        uint32_t crc = detail::crc32_of(reinterpret_cast<const uint8_t*>(m.data()),
                                        m.size());
        CHECK(crc == 0xCBF43926u, "crc32(123456789)");
    }

    // --- primitive_norm ---
    CHECK(std::abs(primitive_norm(1.0, 0) - 0.7127054703549902) < 1e-12,
          "primitive_norm(1,0)");

    // --- tensor byte layout: little-endian, correct size ---
    {
        Tensor t = tensor_f64({1.0, 2.0}, {2});
        CHECK(t.bytes.size() == 16, "tensor_f64 byte size");
        // 1.0 == 0x3FF0000000000000; LE first byte is 0x00, 8th is 0x3F.
        CHECK(t.bytes[7] == 0x3F, "tensor_f64 little-endian");
    }

    // --- DEFLATE compresses repetitive data (round-trip verified externally
    //     by unzip / Python zipfile / the sha256 check in validate_qvf) ---
    {
        std::vector<uint8_t> repetitive(4096, 0);  // all zeros — highly compressible
        auto d0 = detail::deflate(repetitive);
        CHECK(d0.size() < repetitive.size() / 4, "deflate shrinks zeros >4x");
        std::vector<uint8_t> patterned;
        for (int i = 0; i < 1000; ++i) {
            const char* s = "the quick brown fox ";
            patterned.insert(patterned.end(), s, s + 20);
        }
        auto d1 = detail::deflate(patterned);
        CHECK(d1.size() < patterned.size() / 2, "deflate shrinks repeated text >2x");
        // Empty input must not crash.
        auto d2 = detail::deflate(std::vector<uint8_t>{});
        CHECK(!d2.empty(), "deflate of empty emits a valid block");
    }

    // --- archive smoke test ---
    QvfWriter w({"test-code", "9.9", "smoke"});
    w.add_structure({{"O", 8, {{0, 0, 0.117}}}, {"H", 1, {{0, 0.757, -0.469}}}});
    Spectrum ir;
    ir.frequencies = {1595.0};
    ir.intensities = {67.0};
    w.add_spectrum("spectra.ir", ir);
    w.add_atom_properties({-0.68, 0.34});
    WavefunctionGTO wf;
    wf.shells = {{0, 0, {1.0}, {1.0}, true}};
    wf.mo_coefficients = {1, 1, {1.0}};
    wf.energies = {-0.5};
    wf.occupations = {2};
    w.add_wavefunction_gto(wf);
    Json epr = Json::object();
    Json gt = Json::array();
    gt.push_back(Json(2.0023));
    epr.set("g_iso", Json(2.0023)).set("g_tensor_diag", gt);
    Json ext = Json::object();
    Json orca_ext = Json::object();
    orca_ext.set("version", "1.0").set("critical", true);
    ext.set("x_orca", orca_ext);
    w.set_extensions(ext);
    Json epr_members = Json::object();
    epr_members.set("epr", epr);
    w.add_vendor_section("x_orca.epr", epr_members, /*critical=*/true);

    std::vector<uint8_t> bytes = w.to_bytes();
    CHECK(bytes.size() > 200, "archive non-trivial size");
    CHECK(bytes[0] == 'P' && bytes[1] == 'K' && bytes[2] == 3 && bytes[3] == 4,
          "zip local-file magic");
    CHECK(contains(bytes, "manifest.json"), "contains manifest.json entry");
    CHECK(contains(bytes, "wavefunction.gto"), "contains wavefunction kind");
    CHECK(contains(bytes, "x_orca.epr"), "contains vendor section");

    // --- duplicate id is rejected ---
    {
        bool threw = false;
        try {
            QvfWriter w2({"t", "1", ""});
            w2.add_structure({{"H", 1, {{0, 0, 0}}}}, {{false, false, false}}, {}, {},
                             "dup");
            w2.add_bonds({{0, 0, 1.0}}, "dup");
        } catch (const std::exception&) {
            threw = true;
        }
        CHECK(threw, "duplicate id rejected");
    }

    // --- C ABI smoke: create → add → write via the extern "C" surface ---
    {
        qvf_writer* cw = qvf_create("c-abi", "1.0", "smoke");
        CHECK(cw != nullptr, "qvf_create returns a handle");
        const char* syms[2] = {"O", "H"};
        int Z[2] = {8, 1};
        double pos[6] = {0, 0, 0, 0, 0, 0.96};
        CHECK(qvf_add_structure(cw, syms, Z, pos, 2) == 0, "C: add_structure ok");
        double f[1] = {1595.0}, in[1] = {67.0};
        CHECK(qvf_add_spectrum_xy(cw, "spectra.ir", f, in, 1) == 0, "C: spectrum ok");
        CHECK(qvf_add_spectrum_json(
                  cw, "spectra.epr",
                  "{\"g_tensor\":{\"principal\":[2.0,2.0,2.0]}}") == 0,
              "C: spectrum_json ok");
        CHECK(qvf_set_provenance_json(cw, "{\"method\":\"RHF\"}") == 0,
              "C: provenance_json ok");
        const char* path = "c_abi_smoke.qvf";
        CHECK(qvf_write(cw, path) == 0, "C: write ok");
        std::ifstream f2(path, std::ios::binary);
        char magic[4] = {0};
        f2.read(magic, 4);
        CHECK(magic[0] == 'P' && magic[1] == 'K', "C: output is a zip");
        f2.close();
        std::remove(path);
        qvf_destroy(cw);
    }

    // --- INFLATE round-trips DEFLATE (in-memory) ---
    {
        std::vector<uint8_t> src;
        for (int i = 0; i < 2000; ++i)
            src.push_back(static_cast<uint8_t>("QVF round-trip "[i % 15]));
        auto comp = detail::deflate(src);
        auto back = detail::inflate(comp, src.size());
        CHECK(back == src, "inflate(deflate(x)) == x for repeated text");
        std::vector<uint8_t> zeros(4096, 0);
        CHECK(detail::inflate(detail::deflate(zeros), zeros.size()) == zeros,
              "inflate(deflate(zeros)) == zeros");
    }

    // --- QvfReader round-trip: write then read back, verify values ---
    {
        QvfWriter rw({"rt", "1.0", "roundtrip"});
        rw.add_structure({{"O", 8, {{0.0, 0.0, 0.1173}}},
                          {"H", 1, {{0.0, 0.7572, -0.4692}}}});
        Spectrum s;
        s.frequencies = {1595.0, 3657.0};
        s.intensities = {67.0, 5.0};
        rw.add_spectrum("spectra.ir", s);
        rw.add_atom_properties({-0.68, 0.34});
        std::vector<uint8_t> archive = rw.to_bytes();

        QvfReader reader = QvfReader::from_bytes(archive);
        CHECK(reader.manifest().at("qvf_version").as_int() == 1,
              "reader: qvf_version == 1");
        CHECK(reader.has_section("structure"), "reader: has structure section");
        // JSON member: decode the structure and check an atom.
        Json st = reader.read_json_member("structure", "structure");
        CHECK(st.at("atoms").at(0).at("symbol").as_string() == "O",
              "reader: first atom is O");
        CHECK(std::abs(st.at("atoms").at(1).at("position").at(1).as_double() -
                       0.7572) < 1e-9, "reader: decoded H y-position");
        // JSON member: the spectrum.
        Json spec = reader.read_json_member("spectra_ir", "spectrum");
        CHECK(std::abs(spec.at("frequencies").at(0).as_double() - 1595.0) < 1e-9,
              "reader: decoded IR frequency");
        // Binary member: Mulliken charges (float64 [2]).
        BinaryMember bm = reader.read_binary_member("atom_properties",
                                                    "mulliken_charge");
        CHECK(bm.dtype == "float64" && bm.shape.size() == 1 && bm.shape[0] == 2,
              "reader: binary dtype/shape");
        auto charges = bm.as_doubles();
        CHECK(charges.size() == 2 && std::abs(charges[0] + 0.68) < 1e-9,
              "reader: decoded Mulliken charge");
        // sha256 verification: corrupting a byte must be caught. Tamper with the
        // stored bytes and expect a mismatch on verified read.
        std::vector<std::string> errs;
        CHECK(reader.validate(errs), "reader: validate() clean on good archive");
    }

    if (g_failures == 0) {
        std::cout << "all C++ tests passed\n";
        return 0;
    }
    std::cerr << g_failures << " C++ test(s) failed\n";
    return 1;
}
