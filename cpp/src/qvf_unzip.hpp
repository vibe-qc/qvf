// qvf_unzip.hpp — the ZIP reader under its original internal name.
//
// `detail::ZipReader` is qvf::container::ZipReader (qvf/container.hpp): it
// parses the central directory (ZIP64 end records and extra fields
// included) and extracts entries by name, decompressing STORE (method 0) and
// DEFLATE (method 8), from memory or from a file.
//
// The archive is untrusted input: every offset is bounds-checked, entry names
// that occur more than once are recorded (duplicates() — spec § 2.1 forbids
// them; the caller decides whether to refuse), a member is never inflated
// past the uncompressed size its central-directory record declares, and its
// CRC-32 is verified. License: Apache-2.0.
#ifndef QVF_UNZIP_HPP
#define QVF_UNZIP_HPP

#include "qvf/container.hpp"

namespace qvf {
namespace detail {

using ZipReader = container::ZipReader;

}  // namespace detail
}  // namespace qvf

#endif  // QVF_UNZIP_HPP
