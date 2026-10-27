# C ABI 1

The generated [C++ and C API reference](api/cpp.md) lists every declaration
of `qvf_c.h` with its header comment.

Include `<qvf/qvf_c.h>` and link `qvf::qvf`. The public header is valid C99;
implementations use only the C++17 standard library. All original `qvf_create`,
`qvf_add_*`, `qvf_write` and `qvf_destroy` signatures remain available.
`qvf_abi_version()` returns 1 and `qvf_toolkit_version()` returns the toolkit
version. ABI 1 structs have fixed layouts; future incompatible layouts require
new types/functions or another ABI version.

## Building and installing

```sh
cmake -S cpp -B build -DQVF_BUILD_SHARED=ON -DCMAKE_INSTALL_PREFIX=install
cmake --build build
cmake --install build
```

`QVF_BUILD_SHARED` defaults to `OFF`. Shared builds use `QVF_API` for C exports,
install the library/runtime and headers, and set the ABI library version to 1.
The installed CMake target supplies the required `QVF_SHARED` definition for
Windows imports. A manually compiled Windows shared-library client defines
`QVF_SHARED` itself. Non-CMake library builds must define
`QVF_TOOLKIT_VERSION` to the toolkit version; otherwise its query returns
`unknown`. A pure C installed-library client is in
[`cpp/tests/installed_c`](../cpp/tests/installed_c).

## Ownership and failures

New operations return `qvf_status`: `QVF_OK`, `QVF_ERROR`,
`QVF_UNKNOWN_ERROR`, `QVF_BUFFER_TOO_SMALL`, `QVF_CANCELLED`, or
`QVF_INVALID_HANDLE`. A validation that completes with invalid input returns
`QVF_OK` and a report with `ok == 0`. Constructors clear their output handle
before attempting allocation. Destroy functions accept `NULL`.

No C++ exception crosses the C boundary. `qvf_last_error`,
`qvf_reader_last_error`, `qvf_editor_last_error`, and `qvf_report_last_error`
return fixed handle-owned buffers, valid until the next operation on that
handle. `qvf_global_error` reports construction/path-only failures in
thread-local storage. Messages can be truncated to 1023 bytes. Never free these
pointers. Distinct handles may be used independently; a handle must not be
called concurrently or re-entered from its own callback.

Readers own their archive storage. `qvf_reader_from_bytes` copies the input
once, so the caller may immediately release it. JSON query text lasts until
the next JSON query on that reader. Section IDs, kind names, role names and
member-info shape/path pointers last until reader destruction. Finding
strings last until report destruction. Tensor inputs are borrowed only for
the duration of the writer call. Callback bytes are borrowed only for the
callback. Caller output buffers and accumulated callback output must be
discarded on an integrity or I/O failure, even if some bytes were delivered.

## Writing

`qvf_writer_create` chooses memory output when `path == NULL`, or streaming
file output otherwise. `qvf_writer_create_callback` streams a non-seekable
ZIP to a callback. Returning nonzero cancels the operation; discard its output.
Finish with `qvf_writer_finish`, or retrieve memory output using
`qvf_writer_bytes`. Finishing is idempotent. Returned memory bytes belong to
the writer. Destroying an unfinished writer does not finish it.

`qvf_writer_add_structure` accepts explicit symbols, atomic numbers and
row-major Cartesian positions in angstrom, with three `pbc` flags and optional
3×3 row-vector lattice in angstrom. All eight periodic-axis patterns work.
Use a `qvf_section_input` with `qvf_writer_add_structure_payload` for additional
structure fields such as biomolecular atom metadata.

Each canonical kind has a generated `qvf_writer_add_<kind>` entry (dots become
underscores). It accepts the section's JSON fields, named JSON payloads,
typed binary tensors and opaque members. The named entry fills `kind` and
rejects a conflicting value. Every payload role and optional field in the
schema remains accessible; the library checks the section/payload schema
before writing. `qvf_writer_add_section` also accepts declared vendor kinds.

`qvf_tensor_view` specifies borrowed contiguous row-major storage, dtype,
rank/shape, byte order and exact `data_bytes`. `output_dtype` can request a
checked conversion; `QVF_DTYPE_UNKNOWN` preserves the input dtype. Conversion
uses bounded chunks. Large producers can instead declare a section and use
`begin_binary`, repeated `write` calls with little-endian bytes, and
`end_binary`. `abort_binary` abandons an incomplete member and permits retry.

The original `qvf_add_*` functions also work on new handles and share the same
backend. Legacy `qvf_create` handles can use the new section operations.
Legacy `qvf_write(path)` retains its repeatable output behavior for handles
created by `qvf_create`; new streaming handles finish through
`qvf_writer_finish`, and editor handles commit through `qvf_editor_commit`.
Root metadata has the same existing hostname omission and validation behavior.

## Reading and validating

Open with `qvf_reader_open`, enumerate sections and members, and query their
metadata without reading binary payloads. `qvf_reader_section_json` includes
member descriptors; `qvf_reader_section_fields_json` omits them for direct use
in a writer descriptor. `qvf_reader_root_json` returns `null` for an absent
root block. Member byte-size queries enforce declared sizes and resource caps.

Read JSON with `qvf_reader_read_json`. For binary/opaque data, pass a NULL
buffer to `qvf_reader_read_binary` to obtain the needed size. An undersized
buffer is left untouched and returns `QVF_BUFFER_TOO_SMALL`. Chunked reads
support typed and opaque members, check CRC, and optionally verify SHA-256.
Typed array bytes always use the format's little-endian order.

`qvf_limits_default` initializes the documented archive resource limits.
`qvf_reader_validate` and `qvf_validate_path` expose the cumulative container,
manifest, payload, semantics, reference and all stages. Findings retain the
same code, location, severity and message as the C++ validator. Path validation
can report unreadable archives without opening a reader first.

## Editing

`qvf_editor_open(path, atomic, &editor)` uses the existing update backend.
Atomic mode preserves the original until a successful commit. Obtain a
separately owned writer handle through `qvf_editor_writer`, append sections or
remove them through the editor, set run status, then commit. Destroy the
acquired writer with `qvf_writer_destroy`.

The acquired writer retains the editor state if the editor handle is destroyed,
so it never dangles; without an editor handle the update cannot be committed.
After commit all writer mutations are rejected. Destroying an uncommitted
atomic edit discards its temporary archive. In-place mode has the existing
partial-update behavior when a stream fails. `qvf_repack` removes superseded
members and optionally recompresses into a complete replacement archive.

[`write_all_kinds_c.c`](../cpp/examples/write_all_kinds_c.c) round-trips an
archive through the named canonical writer functions without a JSON parser.
[`read_qvf_c.c`](../cpp/examples/read_qvf_c.c) prints sections and findings.
The release CI runs these examples across the positive corpus and validates
their output with the Python reference implementation.
