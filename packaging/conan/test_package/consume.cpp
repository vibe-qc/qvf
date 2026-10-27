#include <qvf/reader.hpp>
#include <qvf/c_api.h>
#include <string_view>

int main() {
    const std::string_view kind = "structure";
    qvf::QvfWriter writer({"package-test", "1", "geometry"});
    writer.add_structure({{"H", 1, {{0.0, 0.0, 0.0}}}});
    auto reader = qvf::Reader::from_bytes(writer.to_bytes());
    return qvf_abi_version() == 1 && reader.sections_of(kind).size() == 1
        && reader.validate().ok ? 0 : 1;
}
