// License: Apache-2.0.
#include "qvf/tensor_view.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <type_traits>
namespace qvf {
namespace tensor_view_detail {
size_t width(DType d) {
    switch (d) {
        case DType::Int8: case DType::UInt8: return 1;
        case DType::Int16: case DType::UInt16: return 2;
        case DType::Int32: case DType::UInt32: case DType::Float32: return 4;
        case DType::Int64: case DType::UInt64: case DType::Float64: return 8;
    }
    throw std::invalid_argument("TensorView: invalid dtype");
}
bool host_little() { const uint16_t one = 1; return *reinterpret_cast<const uint8_t*>(&one) == 1; }
template <class T> T load(const uint8_t* p, bool swap) {
    uint8_t bytes[sizeof(T)];
    if (swap) std::reverse_copy(p, p + sizeof(T), bytes);
    else std::memcpy(bytes, p, sizeof(T));
    T value; std::memcpy(&value, bytes, sizeof(T)); return value;
}
template <class T, class U> T convert(U value) {
    if constexpr (std::is_integral<T>::value) {
        bool bad = false;
        if constexpr (std::is_integral<U>::value) {
            if constexpr (std::is_signed<U>::value) {
                const int64_t x = static_cast<int64_t>(value);
                if constexpr (std::is_signed<T>::value)
                    bad = x < static_cast<int64_t>(std::numeric_limits<T>::min()) ||
                          x > static_cast<int64_t>(std::numeric_limits<T>::max());
                else bad = x < 0 || static_cast<uint64_t>(x) > std::numeric_limits<T>::max();
            } else bad = static_cast<uint64_t>(value) >
                         static_cast<uint64_t>(std::numeric_limits<T>::max());
        } else {
            const long double x = std::trunc(static_cast<long double>(value));
            // Use exclusive powers-of-two bounds: INT64_MAX/UINT64_MAX may
            // round up on hosts whose long double has only 53 mantissa bits.
            const long double hi = std::ldexp(1.0L, std::numeric_limits<T>::digits);
            const long double lo = std::is_signed<T>::value ? -hi : 0.0L;
            bad = !std::isfinite(x) || x < lo || x >= hi;
        }
        if (bad) throw std::out_of_range("TensorView: integer conversion out of range");
    }
    return static_cast<T>(value);
}
template <class T, class U> void store(uint8_t* out, U value) {
    const T v = convert<T>(value);
    const auto* p = reinterpret_cast<const uint8_t*>(&v);
    if (host_little()) std::memcpy(out, p, sizeof(T));
    else std::reverse_copy(p, p + sizeof(T), out);
}
template <class U> void store_as(uint8_t* out, U value, DType dtype) {
    switch (dtype) {
#define QVF_TV_STORE(E, T) case DType::E: store<T>(out, value); return
        QVF_TV_STORE(Int8, int8_t); QVF_TV_STORE(UInt8, uint8_t);
        QVF_TV_STORE(Int16, int16_t); QVF_TV_STORE(UInt16, uint16_t);
        QVF_TV_STORE(Int32, int32_t); QVF_TV_STORE(UInt32, uint32_t);
        QVF_TV_STORE(Int64, int64_t); QVF_TV_STORE(UInt64, uint64_t);
        QVF_TV_STORE(Float32, float); QVF_TV_STORE(Float64, double);
#undef QVF_TV_STORE
    }
    throw std::invalid_argument("TensorView: invalid dtype");
}
void one(const uint8_t* in, uint8_t* out, DType src, DType dst, bool swap) {
    switch (src) {
#define QVF_TV_LOAD(E, T) case DType::E: store_as(out, load<T>(in, swap), dst); return
        QVF_TV_LOAD(Int8, int8_t); QVF_TV_LOAD(UInt8, uint8_t);
        QVF_TV_LOAD(Int16, int16_t); QVF_TV_LOAD(UInt16, uint16_t);
        QVF_TV_LOAD(Int32, int32_t); QVF_TV_LOAD(UInt32, uint32_t);
        QVF_TV_LOAD(Int64, int64_t); QVF_TV_LOAD(UInt64, uint64_t);
        QVF_TV_LOAD(Float32, float); QVF_TV_LOAD(Float64, double);
#undef QVF_TV_LOAD
    }
    throw std::invalid_argument("TensorView: invalid dtype");
}
} // namespace tensor_view_detail
uint64_t TensorView::element_count() const {
    uint64_t n = 1;
    for (int64_t d : shape) {
        if (d < 0) throw std::invalid_argument("TensorView: negative extent");
        if (d && n > UINT64_MAX / static_cast<uint64_t>(d))
            throw std::overflow_error("TensorView: shape overflow");
        n *= static_cast<uint64_t>(d);
    }
    return n;
}
uint64_t TensorView::byte_size() const {
    const size_t width = tensor_view_detail::width(dtype);
    const uint64_t n = element_count();
    if (n > SIZE_MAX / width) throw std::overflow_error("TensorView: storage exceeds address space");
    if (n && !data) throw std::invalid_argument("TensorView: null data for a nonempty tensor");
    return n * width;
}
void TensorView::write_into(const std::function<void(const uint8_t*, size_t)>& sink,
                            DType output_dtype) const {
    using namespace tensor_view_detail;
    if (!sink) throw std::invalid_argument("TensorView: empty sink callback");
    byte_size();
    const size_t src = width(dtype), dst = width(output_dtype);
    uint64_t left = element_count();
    const auto* p = static_cast<const uint8_t*>(data);
    const bool little = byte_order == ByteOrder::Native ? host_little() : byte_order == ByteOrder::Little;
    uint8_t buffer[65536];
    while (left) {
        const size_t n = static_cast<size_t>(std::min<uint64_t>(left, sizeof(buffer) / std::max(src, dst)));
        if (dtype == output_dtype && little) sink(p, n * src);
        else {
            for (size_t i = 0; i < n; ++i) {
                if (dtype == output_dtype) std::reverse_copy(p + i * src, p + (i + 1) * src, buffer + i * dst);
                else one(p + i * src, buffer + i * dst, dtype, output_dtype, little != host_little());
            }
            sink(buffer, n * dst);
        }
        p += n * src; left -= n;
    }
}
} // namespace qvf
