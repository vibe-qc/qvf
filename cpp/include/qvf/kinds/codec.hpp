// Typed JSON codecs shared by schema-generated payload records.
// License: Apache-2.0.
#ifndef QVF_KINDS_CODEC_HPP
#define QVF_KINDS_CODEC_HPP
#include <array>
#include <cmath>
#include <limits>
#include <map>
#include <optional>
#include <tuple>
#include <variant>
#include <vector>
#include "qvf/json.hpp"
namespace qvf { namespace kinds { namespace codec {
inline void require(bool ok, const char* what) { if (!ok) throw std::invalid_argument(what); }
template<class T, class Enable = void> struct Value {
    static Json encode(const T& v) { return v.to_json(); }
    static T decode(const Json& j) { return T::from_json(j); }
};
template<> struct Value<Json> {
    static Json encode(const Json& j) { return j; }
    static Json decode(const Json& j) { return j; }
};
template<> struct Value<std::string> {
    static Json encode(const std::string& v) { return Json(v); }
    static std::string decode(const Json& j) { require(j.is_string(), "expected string"); return j.as_string(); }
};
template<> struct Value<bool> {
    static Json encode(bool v) { return Json(v); }
    static bool decode(const Json& j) { require(j.is_bool(), "expected boolean"); return j.as_bool(); }
};
template<> struct Value<double> {
    static Json encode(double v) { return Json(v); }
    static double decode(const Json& j) { require(j.is_number(), "expected number"); return j.as_double(); }
};
template<> struct Value<int64_t> {
    static Json encode(int64_t v) { return Json(static_cast<long long>(v)); }
    static int64_t decode(const Json& j) {
        if (j.type() == Json::Type::Int) return j.as_int();
        require(j.is_number(), "expected integer"); const double v = j.as_double();
        require(std::isfinite(v) && std::trunc(v) == v && v >= -9223372036854775808.0 &&
                v < 9223372036854775808.0, "integer is outside int64 range");
        return static_cast<int64_t>(v);
    }
};
template<> struct Value<std::monostate> {
    static Json encode(std::monostate) { return Json(); }
    static std::monostate decode(const Json& j) { require(j.is_null(), "expected null"); return {}; }
};
template<class T> struct Value<std::optional<T>> {
    static Json encode(const std::optional<T>& v) { return v ? Value<T>::encode(*v) : Json(); }
    static std::optional<T> decode(const Json& j) {
        if (j.is_null()) return std::nullopt;
        return Value<T>::decode(j);
    }
};
template<class T> struct Value<std::vector<T>> {
    static Json encode(const std::vector<T>& v) {
        Json out = Json::array(); for (const T& x : v) out.push_back(Value<T>::encode(x)); return out;
    }
    static std::vector<T> decode(const Json& j) {
        require(j.is_array(), "expected array"); std::vector<T> out;
        for (const auto& x : j.elements()) {
            out.push_back(Value<T>::decode(x));
        }
        return out;
    }
};
template<class T, size_t N> struct Value<std::array<T, N>> {
    static Json encode(const std::array<T, N>& v) {
        Json out = Json::array(); for (const auto& x : v) out.push_back(Value<T>::encode(x)); return out;
    }
    static std::array<T, N> decode(const Json& j) {
        require(j.is_array() && j.elements().size() == N, "wrong fixed array length");
        std::array<T, N> out{};
        for (size_t i = 0; i < N; ++i) {
            out[i] = Value<T>::decode(j.elements()[i]);
        }
        return out;
    }
};
template<class T> struct Value<std::map<std::string, T>> {
    static Json encode(const std::map<std::string, T>& v) {
        Json out = Json::object(); for (const auto& x : v) out.set(x.first, Value<T>::encode(x.second)); return out;
    }
    static std::map<std::string, T> decode(const Json& j) {
        require(j.is_object(), "expected object"); std::map<std::string, T> out;
        for (const auto& x : j.items()) {
            out[x.first] = Value<T>::decode(x.second);
        }
        return out;
    }
};
template<class... Ts> struct Value<std::tuple<Ts...>> {
    template<size_t... Is> static Json encode_at(const std::tuple<Ts...>& v, std::index_sequence<Is...>) {
        Json out = Json::array(); (out.push_back(Value<std::tuple_element_t<Is, std::tuple<Ts...>>>::encode(std::get<Is>(v))), ...); return out;
    }
    static Json encode(const std::tuple<Ts...>& v) { return encode_at(v, std::index_sequence_for<Ts...>{}); }
    template<size_t... Is> static std::tuple<Ts...> decode_at(const Json& j, std::index_sequence<Is...>) {
        return {Value<std::tuple_element_t<Is, std::tuple<Ts...>>>::decode(j.elements()[Is])...};
    }
    static std::tuple<Ts...> decode(const Json& j) {
        require(j.is_array() && j.elements().size() == sizeof...(Ts), "wrong tuple length");
        return decode_at(j, std::index_sequence_for<Ts...>{});
    }
};
template<class... Ts> struct Value<std::variant<Ts...>> {
    using V = std::variant<Ts...>;
    static Json encode(const V& v) { return std::visit([](const auto& x) { return Value<std::decay_t<decltype(x)>>::encode(x); }, v); }
    template<size_t I = 0> static V decode_next(const Json& j) {
        if constexpr (I == sizeof...(Ts)) throw std::invalid_argument("value matches no typed alternative");
        else {
            try { return V(std::in_place_index<I>, Value<std::variant_alternative_t<I, V>>::decode(j)); }
            catch (const std::invalid_argument&) { return decode_next<I + 1>(j); }
        }
    }
    static V decode(const Json& j) { return decode_next(j); }
};
template<class T> void put(Json& j, const char* key, const T& value) { j.set(key, Value<T>::encode(value)); }
template<class T> T get(const Json& j, const char* key) {
    require(j.has(key), "required typed field is absent"); return Value<T>::decode(j.at(key));
}
} } } // qvf::kinds::codec
#endif
