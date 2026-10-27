// qvf_validation.cpp — staged validation input adapters. License: Apache-2.0.
#include "qvf/validation.hpp"

#include <memory>
#include <stdexcept>
#include <utility>

namespace qvf {
namespace validate {
namespace validation_adapter_detail {
Report unreadable(const std::exception& e) {
    Report report;
    report.ok = false;
    report.findings.push_back({Finding::Severity::Error, "E_ZIP_UNREADABLE", "archive",
                               std::string("not a readable zip: ") + e.what()});
    return report;
}
}  // namespace validation_adapter_detail

Report run_file(const std::string& path, Level level, const Limits& limits,
                const ValidationOptions& options) {
    std::unique_ptr<container::ZipReader> archive;
    try {
        archive.reset(new container::ZipReader(container::ZipReader::open(path)));
    } catch (const std::exception& e) {
        return validation_adapter_detail::unreadable(e);
    }
    return run(*archive, level, limits, options);
}

Report run_bytes(std::vector<uint8_t> bytes, Level level, const Limits& limits,
                 const ValidationOptions& options) {
    std::unique_ptr<container::ZipReader> archive;
    try {
        archive.reset(new container::ZipReader(
            container::ZipReader::from_bytes(std::move(bytes))));
    } catch (const std::exception& e) {
        return validation_adapter_detail::unreadable(e);
    }
    return run(*archive, level, limits, options);
}

}  // namespace validate
}  // namespace qvf
