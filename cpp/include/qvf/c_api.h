/* Complete C facade. Included by qvf_c.h; existing signatures remain there.
 * License: Apache-2.0. */
#ifndef QVF_C_API_H
#define QVF_C_API_H
#include "qvf/qvf_c.h"
#ifdef __cplusplus
extern "C" {
#endif
#define QVF_ABI_VERSION 1
/* ABI 1 is additive to all earlier writer symbols. Struct layouts below are
 * fixed for ABI 1; a future incompatible layout gets a new type/function. */
typedef int qvf_status;
enum { QVF_OK=0, QVF_ERROR=1, QVF_UNKNOWN_ERROR=2,
       QVF_BUFFER_TOO_SMALL=3, QVF_CANCELLED=4, QVF_INVALID_HANDLE=-1 };
typedef struct qvf_reader qvf_reader;
typedef struct qvf_editor qvf_editor;
typedef struct qvf_report qvf_report;
typedef enum qvf_dtype {
    QVF_DTYPE_UNKNOWN=0, QVF_INT8=1, QVF_INT16=2, QVF_INT32=3, QVF_INT64=4,
    QVF_UINT8=5, QVF_UINT16=6, QVF_UINT32=7, QVF_UINT64=8,
    QVF_FLOAT32=9, QVF_FLOAT64=10
} qvf_dtype;
typedef enum qvf_byte_order { QVF_NATIVE=0, QVF_LITTLE_ENDIAN=1, QVF_BIG_ENDIAN=2 } qvf_byte_order;
typedef enum qvf_validation_level {
    QVF_VALIDATE_CONTAINER=0, QVF_VALIDATE_MANIFEST=1, QVF_VALIDATE_PAYLOADS=2,
    QVF_VALIDATE_SEMANTICS=3, QVF_VALIDATE_REFERENCES=4, QVF_VALIDATE_ALL=5
} qvf_validation_level;
typedef enum qvf_root_block {
    QVF_ROOT_PROVENANCE=0, QVF_ROOT_METADATA=1, QVF_ROOT_VIEWER_DEFAULTS=2,
    QVF_ROOT_THERMOCHEMISTRY=3, QVF_ROOT_DIPOLE_MOMENT=4, QVF_ROOT_CONSTRAINTS=5,
    QVF_ROOT_ENERGIES=6, QVF_ROOT_EXTENSIONS=7
} qvf_root_block;
typedef enum qvf_run_status { QVF_RUN_RUNNING=0, QVF_RUN_CONVERGED=1, QVF_RUN_FAILED=2 } qvf_run_status;
typedef enum qvf_member_format { QVF_MEMBER_JSON=0, QVF_MEMBER_BINARY=1, QVF_MEMBER_OPAQUE=2 } qvf_member_format;
typedef struct qvf_limits {
    uint64_t max_member_bytes, max_total_bytes;
    double max_ratio;
    uint64_t ratio_exempt_bytes, max_json_bytes;
    size_t max_json_depth;
} qvf_limits;
/* Tensor input is borrowed during the call, contiguous row-major. data_bytes
 * must equal dtype*prod(shape). output_dtype=UNKNOWN preserves dtype. */
typedef struct qvf_tensor_view {
    const void* data;
    size_t data_bytes;
    qvf_dtype dtype;
    size_t rank;
    const int64_t* shape;
    qvf_byte_order byte_order;
    qvf_dtype output_dtype;
} qvf_tensor_view;
typedef struct qvf_json_input { const char* role; const char* json; } qvf_json_input;
typedef struct qvf_binary_input { const char* role; qvf_tensor_view tensor; } qvf_binary_input;
typedef struct qvf_opaque_input {
    const char* role; const void* data; size_t size; const char* media_type;
} qvf_opaque_input;
/* section_json contains id/kind/label/references and kind-specific peer fields,
 * with no members. kind may instead be supplied by a named entry point. JSON payloads are complete payload objects, not fragments. */
typedef struct qvf_section_input {
    const char* section_json;
    const qvf_json_input* json; size_t json_count;
    const qvf_binary_input* binary; size_t binary_count;
    const qvf_opaque_input* opaque; size_t opaque_count;
} qvf_section_input;
typedef struct qvf_member_info {
    qvf_member_format format;
    qvf_dtype dtype;
    size_t rank;
    const int64_t* shape; /* borrowed until reader is destroyed */
    uint64_t nbytes;
    const char* path; const char* media_type; /* borrowed; NULL if absent */
} qvf_member_info;
typedef struct qvf_finding {
    int severity; /* 0 error, 1 warning */
    const char* code; const char* where; const char* message;
} qvf_finding;
/* Return zero to continue, nonzero to cancel. Borrowed bytes are valid only
 * in the callback. Do not re-enter the same handle. Partial output must be
 * discarded after cancellation, an I/O failure or a final CRC/SHA failure. */
typedef int (*qvf_chunk_callback)(const void* bytes, size_t size, void* user);

QVF_API unsigned qvf_abi_version(void);
QVF_API const char* qvf_toolkit_version(void);
/* Error strings are handle-owned fixed buffers, valid until the next call on
 * that handle. Creation/path-only errors use thread-local global_error.
 * Never free these pointers. Handles are not concurrently callable. */
QVF_API const char* qvf_global_error(void);
QVF_API const char* qvf_reader_last_error(const qvf_reader*);
QVF_API const char* qvf_editor_last_error(const qvf_editor*);
QVF_API const char* qvf_report_last_error(const qvf_report*);
QVF_API qvf_status qvf_limits_default(qvf_limits* out);

/* A NULL path selects memory. Callback output is non-seekable ZIP streaming.
 * Old qvf_add_* operations also work on these handles, sharing one backend. */
QVF_API qvf_status qvf_writer_create(const char* program, const char* version,
    const char* calculation, const char* path, qvf_writer** out);
QVF_API qvf_status qvf_writer_create_callback(const char* program, const char* version,
    const char* calculation, qvf_chunk_callback callback, void* user, qvf_writer** out);
QVF_API qvf_status qvf_writer_destroy(qvf_writer*);
QVF_API qvf_status qvf_writer_finish(qvf_writer*);
/* Memory bytes: borrowed until the handle is destroyed or bytes queried again.
 * Finishes once and retains the resulting buffer. */
QVF_API qvf_status qvf_writer_bytes(qvf_writer*, const void** bytes, size_t* size);
QVF_API qvf_status qvf_writer_set_root_json(qvf_writer*, qvf_root_block, const char* json);
QVF_API qvf_status qvf_writer_set_auto_metadata(qvf_writer*, int enabled);
QVF_API qvf_status qvf_writer_set_force_zip64(qvf_writer*, int enabled);
QVF_API qvf_status qvf_writer_add_section(qvf_writer*, const qvf_section_input*);
/* Declare an empty section, then add JSON/opaque/binary members manually. */
QVF_API qvf_status qvf_writer_declare_section(qvf_writer*, const char* section_json);
QVF_API qvf_status qvf_writer_add_json(qvf_writer*, const char* id, const char* role, const char* json);
QVF_API qvf_status qvf_writer_add_opaque(qvf_writer*, const char* id, const qvf_opaque_input*);
QVF_API qvf_status qvf_writer_begin_binary(qvf_writer*, const char* id, const char* role,
    qvf_dtype dtype, size_t rank, const int64_t* shape);
QVF_API qvf_status qvf_writer_write(qvf_writer*, const void* little_endian_bytes, size_t size);
QVF_API qvf_status qvf_writer_end_binary(qvf_writer*);
QVF_API qvf_status qvf_writer_abort_binary(qvf_writer*);
QVF_API qvf_status qvf_writer_set_section_field_json(qvf_writer*, const char* id, const char* key, const char* json);
/* Explicit periodic structure, lattice row vectors in Angstrom. positions is
 * n_atoms*3 doubles; symbols, atomic_numbers and positions are required
 * for nonzero n_atoms. pbc is NULL (molecule) or three 0/1 flags; lattice is NULL
 * or nine doubles. bonds_json is NULL or the complete BondsPayload object. */
QVF_API qvf_status qvf_writer_add_structure(qvf_writer*, const char* id, size_t n_atoms,
    const char* const* symbols, const int* atomic_numbers, const double* positions,
    const int pbc[3], const double lattice_rows[9], const char* bonds_json);
/* Schema-checked named entries for every canonical kind. The named entry sets
 * kind and accepts arbitrary valid id in section_json. All payload roles,
 * optional fields and binary arrays remain available through the descriptor. */
#define QVF_C_KIND(name, kind) QVF_API qvf_status qvf_writer_add_##name(qvf_writer*, const qvf_section_input*);
#include "qvf/c_kinds_generated.h"
#undef QVF_C_KIND
QVF_API qvf_status qvf_writer_add_volume(qvf_writer*, const char* kind, const qvf_section_input*);
QVF_API qvf_status qvf_writer_add_spectrum_json(qvf_writer*, const char* kind, const qvf_section_input*);
QVF_API qvf_status qvf_writer_add_spectrum_xy(qvf_writer*, const char* kind, const char* id,
    size_t count, const double* x, const double* y, const char* x_units, const char* y_units);
QVF_API qvf_status qvf_writer_add_wavefunction_gto_unrestricted(qvf_writer*, const qvf_section_input*);
QVF_API qvf_status qvf_writer_set_ecp_json(qvf_writer*, const char* id, const char* ecp_json);
QVF_API qvf_status qvf_writer_set_overlap(qvf_writer*, const char* id, const qvf_tensor_view*);
QVF_API qvf_status qvf_writer_add_dos_coop_cohp(qvf_writer*, const char* kind, const qvf_section_input*);
QVF_API qvf_status qvf_writer_add_eos(qvf_writer*, const qvf_section_input*);
QVF_API qvf_status qvf_writer_add_job_spec_json(qvf_writer*, const char* id, const char* json);
QVF_API qvf_status qvf_writer_add_excited_states_json(qvf_writer*, const char* id, const char* json);
QVF_API qvf_status qvf_writer_add_bond_orders_json(qvf_writer*, const char* id, const char* json);
QVF_API qvf_status qvf_writer_add_scf_history_json(qvf_writer*, const char* id, const char* json);
QVF_API qvf_status qvf_writer_add_vendor_json(qvf_writer*, const char* id, const char* kind, const char* role, const char* json);
QVF_API qvf_status qvf_writer_add_vendor_binary(qvf_writer*, const char* id, const char* kind, const qvf_opaque_input*);
QVF_API qvf_status qvf_writer_set_extensions_json(qvf_writer*, const char* json);

/* Reader owns file/byte storage. from_bytes copies the caller's input once.
 * JSON text is borrowed until the next text query or destruction. Section
 * ids/kinds/member-info pointers remain valid until reader destruction. */
QVF_API qvf_status qvf_reader_open(const char* path, const qvf_limits*, qvf_reader** out);
QVF_API qvf_status qvf_reader_from_bytes(const void*, size_t, const qvf_limits*, qvf_reader** out);
QVF_API qvf_status qvf_reader_destroy(qvf_reader*);
QVF_API qvf_status qvf_reader_manifest_json(qvf_reader*, const char** text, size_t* length);
QVF_API qvf_status qvf_reader_section_count(qvf_reader*, size_t* count);
QVF_API qvf_status qvf_reader_section_id(qvf_reader*, size_t index, const char** id);
QVF_API qvf_status qvf_reader_section_kind(qvf_reader*, size_t index, const char** kind);
/* Fields-only form is directly usable as qvf_section_input.section_json. */
QVF_API qvf_status qvf_reader_section_fields_json(qvf_reader*, const char* id, const char** text, size_t* length);
/* Missing root blocks are returned as the JSON text null. */
QVF_API qvf_status qvf_reader_root_json(qvf_reader*, qvf_root_block, const char** text, size_t* length);
QVF_API qvf_status qvf_reader_section_json(qvf_reader*, const char* id, const char** text, size_t* length);
QVF_API qvf_status qvf_reader_member_count(qvf_reader*, const char* id, size_t* count);
QVF_API qvf_status qvf_reader_member_role(qvf_reader*, const char* id, size_t index, const char** role);
QVF_API qvf_status qvf_reader_member_info(qvf_reader*, const char* id, const char* role, qvf_member_info* out);
QVF_API qvf_status qvf_reader_read_json(qvf_reader*, const char* id, const char* role,
    int verify_sha, const char** text, size_t* length);
/* Binary output is raw little-endian bytes. A NULL buffer queries needed size;
 * BUFFER_TOO_SMALL reports needed size and writes nothing. Includes opaque
 * members; typed arrays can also use read_binary_chunked. Discard buffer
 * contents on any error other than BUFFER_TOO_SMALL; final CRC/SHA errors
 * may follow partial delivery. */
QVF_API qvf_status qvf_reader_read_binary(qvf_reader*, const char* id, const char* role,
    int verify_sha, void* buffer, size_t capacity, size_t* needed);
QVF_API qvf_status qvf_reader_read_binary_chunked(qvf_reader*, const char* id, const char* role,
    int verify_sha, qvf_chunk_callback, void* user);
QVF_API qvf_status qvf_validate_path(const char* path, qvf_validation_level,
    const qvf_limits*, int schema_check, qvf_report** out);
QVF_API qvf_status qvf_reader_validate(qvf_reader*, qvf_validation_level, int schema_check, qvf_report** out);
QVF_API qvf_status qvf_report_destroy(qvf_report*);
QVF_API qvf_status qvf_report_ok(qvf_report*, int* ok);
QVF_API qvf_status qvf_report_count(qvf_report*, size_t* count);
/* Finding strings are report-owned until report destruction. */
QVF_API qvf_status qvf_report_get(qvf_report*, size_t index, qvf_finding* out);

QVF_API qvf_status qvf_editor_open(const char* path, int atomic, qvf_editor** out);
/* Returns a separately owned writer handle retaining the editor's state.
 * Destroy it with qvf_writer_destroy. It remains usable after editor_destroy,
 * but finish/bytes are forbidden: only editor_commit commits the update. */
QVF_API qvf_status qvf_editor_writer(qvf_editor*, qvf_writer** out);
QVF_API qvf_status qvf_editor_remove_section(qvf_editor*, const char* id);
QVF_API qvf_status qvf_editor_set_run_status(qvf_editor*, qvf_run_status, const char* run_id);
QVF_API qvf_status qvf_editor_commit(qvf_editor*);
QVF_API qvf_status qvf_editor_destroy(qvf_editor*);
QVF_API qvf_status qvf_repack(const char* in, const char* out, int deflate);
#ifdef __cplusplus
}
#endif
#endif
