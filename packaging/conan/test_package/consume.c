#include <qvf/c_api.h>

int main(void) {
    qvf_writer* writer = NULL;
    qvf_reader* reader = NULL;
    const char* symbols[] = {"H"};
    const int numbers[] = {1};
    const double positions[] = {0.0, 0.0, 0.0};
    const void* bytes = NULL;
    size_t size = 0, count = 0;
    int result = 1;
    if (qvf_abi_version() != 1 ||
        qvf_writer_create("package-test", "1", "geometry", NULL, &writer) != QVF_OK)
        return 1;
    if (qvf_writer_add_structure(writer, "structure", 1, symbols, numbers,
                                positions, NULL, NULL, NULL) != QVF_OK ||
        qvf_writer_finish(writer) != QVF_OK ||
        qvf_writer_bytes(writer, &bytes, &size) != QVF_OK ||
        qvf_reader_from_bytes(bytes, size, NULL, &reader) != QVF_OK)
        goto cleanup;
    result = qvf_reader_section_count(reader, &count) != QVF_OK || count != 1;
cleanup:
    if (reader != NULL) qvf_reader_destroy(reader);
    qvf_writer_destroy(writer);
    return result;
}
