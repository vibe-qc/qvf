// qvf/validation.hpp — staged validation facade. License: Apache-2.0.
#ifndef QVF_VALIDATION_HPP
#define QVF_VALIDATION_HPP

#include <cstddef>
#include <string>
#include <vector>

#include "qvf/container.hpp"
#include "qvf/qvf_reader.hpp"

namespace qvf {
namespace validate {

// Cumulative stages. Container inspects the directory and manifest presence,
// without reading entry payloads. Manifest reads only manifest.json and checks
// its schema, section/member declarations and orphan entries. Payloads adds
// member integrity, decoding, declared shapes and payload schemas. Semantics
// adds kind-specific consistency (including shapes across declared sections).
// References adds section-reference resolution. All is the complete validator.
// A lower stage's successful report does not certify the later stages.
enum class Level { Container, Manifest, Payloads, Semantics, References, All };
using Finding = qvf::Finding;

struct Report {
    bool ok = true;
    std::vector<Finding> findings;
    // Number of entries in manifest.sections when a manifest was parsed;
    // zero at Container level or when no sections array could be read.
    size_t n_sections = 0;
};

Report run(const container::ZipReader& archive, Level level = Level::All,
           const Limits& limits = Limits{}, const ValidationOptions& options = {});
// These entry points also report an unreadable ZIP as E_ZIP_UNREADABLE, so
// malformed input need not be opened as a Reader before it can be validated.
Report run_file(const std::string& path, Level level = Level::All,
                const Limits& limits = Limits{}, const ValidationOptions& options = {});
Report run_bytes(std::vector<uint8_t> archive, Level level = Level::All,
                 const Limits& limits = Limits{}, const ValidationOptions& options = {});

}  // namespace validate
}  // namespace qvf
#endif  // QVF_VALIDATION_HPP
