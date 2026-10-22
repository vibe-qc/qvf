cmake_minimum_required(VERSION 3.16)
project(qvf_package_test LANGUAGES C CXX)
find_package(qvf CONFIG REQUIRED)
# Ask for C++11 initially: qvf::qvf must raise the consumer to C++17 itself.
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_executable(consume_cpp consume.cpp)
target_link_libraries(consume_cpp PRIVATE qvf::qvf)
add_executable(consume_c consume.c)
set_target_properties(consume_c PROPERTIES C_STANDARD 99 C_STANDARD_REQUIRED ON
                      LINKER_LANGUAGE CXX)
target_link_libraries(consume_c PRIVATE qvf::qvf)
