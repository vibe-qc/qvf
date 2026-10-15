// zip_reader_fuzzer.cpp — libFuzzer target: the ZIP container reader and the
// validator on arbitrary bytes.
//
// Every input goes through container::ZipReader (central directory, ZIP64
// records, local headers, streaming inflate of every entry under small caps),
// ZipWriter::append over it, QvfReader::from_bytes and validate_bytes. None
// of these may crash, hang, or trip a sanitizer on any input; exceptions are
// the expected way to refuse one.
//
// Built only with -DQVF_FUZZ=ON (clang). With libFuzzer (which adds the inputs
// it finds to the first directory, so make that a scratch one):
//     zip_reader_fuzzer -max_total_time=60 SCRATCH_DIR conformance/corpus
// Where clang ships no libFuzzer runtime, the same target links
// standalone_fuzz_main.cpp instead (replay + random mutation, no coverage
// feedback) and takes the same arguments.
#include <cstddef>
#include <cstdint>
#include <exception>
#include <string>
#include <vector>

#include "qvf/container.hpp"
#include "qvf/qvf_reader.hpp"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    // Small caps keep each input cheap: a lying header cannot make the
    // reader inflate gigabytes.
    qvf::Limits lim;
    lim.max_member_bytes = uint64_t(1) << 24;
    lim.max_total_bytes = uint64_t(1) << 26;
    lim.max_json_bytes = uint64_t(1) << 22;
    const std::vector<uint8_t> bytes(data, data + size);

    try {
        const qvf::container::ZipReader zip(bytes);
        for (const auto& e : zip.entries()) {
            try {
                (void)zip.local_header(e);
            } catch (const std::exception&) {
            }
            try {
                uint64_t n = 0;
                zip.read_into(e.name, [&n](const uint8_t*, size_t k) { n += k; }, lim);
            } catch (const std::exception&) {
            }
        }
        (void)zip.names();
        (void)zip.total_size();
    } catch (const std::exception&) {
    }

    try {
        qvf::container::ZipWriter w = qvf::container::ZipWriter::append(bytes);
        w.write("fuzz/appended.txt", std::string("appended"));
        w.finish();
    } catch (const std::exception&) {
    }

    try {
        const qvf::QvfReader r = qvf::QvfReader::from_bytes(bytes, lim);
        (void)r.manifest().dump(0);
    } catch (const std::exception&) {
    }

    (void)qvf::QvfReader::validate_bytes(bytes, lim);
    return 0;
}
