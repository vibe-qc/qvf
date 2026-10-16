/* Native C sizes verify the generated Fortran descriptor layout. Apache-2.0. */
#include "qvf/qvf_c.h"
size_t qvf_test_c_size(int index) {
    const size_t sizes[] = {sizeof(qvf_limits), sizeof(qvf_tensor_view),
        sizeof(qvf_json_input), sizeof(qvf_binary_input), sizeof(qvf_opaque_input),
        sizeof(qvf_section_input), sizeof(qvf_member_info), sizeof(qvf_finding)};
    return index >= 0 && index < 8 ? sizes[index] : 0;
}
