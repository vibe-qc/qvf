/* Linked only against the installed shared library. License: Apache-2.0. */
#include <qvf/qvf_c.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    qvf_writer* w = NULL;
    qvf_reader* r = NULL;
    qvf_report* report = NULL;
    const void* bytes = NULL;
    size_t size = 0;
    int valid = 0;
    const char* symbols[] = {"He"};
    const int numbers[] = {2}, pbc[] = {0, 0, 1};
    const double positions[] = {0, 0, 0}, lattice[] = {5,0,0,0,5,0,0,0,5};
    if (qvf_abi_version() != QVF_ABI_VERSION || !strcmp(qvf_toolkit_version(), "unknown")) return 1;
    if (qvf_writer_create("installed-c", "1", "periodic", NULL, &w)) return 2;
    if (qvf_writer_add_structure(w, "structure", 1, symbols, numbers, positions, pbc, lattice, NULL)) return 3;
    if (qvf_writer_bytes(w, &bytes, &size)) return 4;
    if (qvf_reader_from_bytes(bytes, size, NULL, &r)) return 5;
    if (qvf_reader_validate(r, QVF_VALIDATE_ALL, 1, &report)) return 6;
    if (qvf_report_ok(report, &valid) || !valid) return 7;
    qvf_report_destroy(report);
    qvf_reader_destroy(r);
    qvf_writer_destroy(w);
    printf("installed C client: toolkit %s, ABI %u\n", qvf_toolkit_version(), qvf_abi_version());
    return 0;
}
