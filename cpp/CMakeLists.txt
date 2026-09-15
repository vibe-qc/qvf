cmake_minimum_required(VERSION 3.16)
project(qvf_writer LANGUAGES CXX C VERSION 0.1.0)

# Zero external dependencies — only the C++17 standard library.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# --- library ---------------------------------------------------------------
# src/qvf.cpp is the C++ writer; src/qvf_c.cpp is the extern "C" ABI wrapper;
# src/qvf_reader.cpp is the C++ reader (ZIP + INFLATE + JSON parse).
add_library(qvf STATIC src/qvf.cpp src/qvf_c.cpp src/qvf_reader.cpp)
include(GNUInstallDirs)
target_include_directories(qvf
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)   # internal sha256/zip headers
if(MSVC)
  target_compile_options(qvf PRIVATE /W4)
else()
  target_compile_options(qvf PRIVATE -Wall -Wextra)
endif()

# Alias so downstream `target_link_libraries(foo qvf::qvf)` works when this is
# added via add_subdirectory().
add_library(qvf::qvf ALIAS qvf)

# --- example ---------------------------------------------------------------
add_executable(write_h2o examples/write_h2o.cpp)
target_link_libraries(write_h2o PRIVATE qvf)

add_executable(write_all_kinds examples/write_all_kinds.cpp)
target_link_libraries(write_all_kinds PRIVATE qvf)

# The C++ reader CLI: open + validate + summarize any .qvf.
add_executable(read_qvf examples/read_qvf.cpp)
target_link_libraries(read_qvf PRIVATE qvf)

# A pure-C example driving the extern "C" ABI. Linked with the C++ driver so the
# C++ runtime is pulled in.
add_executable(write_h2o_c examples/write_h2o_c.c)
target_link_libraries(write_h2o_c PRIVATE qvf)
set_target_properties(write_h2o_c PROPERTIES LINKER_LANGUAGE CXX)

# Single-header amalgamation demo. Compiled against ONLY qvf_single.hpp (the
# amalgamated header lives at the cpp/ root) — it does NOT see include/ or src/
# and does NOT link the qvf library, so building it proves the single header is
# fully self-contained (STB-style, with QVF_IMPLEMENTATION in this one TU).
add_executable(write_single_header examples/write_single_header.cpp)
target_include_directories(write_single_header PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# --- tests -----------------------------------------------------------------
enable_testing()
add_executable(qvf_tests tests/test_writer.cpp)
target_link_libraries(qvf_tests PRIVATE qvf)
target_include_directories(qvf_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
add_test(NAME qvf_tests COMMAND qvf_tests)

# --- install / export ------------------------------------------------------
# Lets adopters consume the library with `find_package(qvf CONFIG)` or
# FetchContent + `target_link_libraries(app PRIVATE qvf::qvf)`.
include(CMakePackageConfigHelpers)

install(TARGETS qvf EXPORT qvfTargets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(DIRECTORY include/qvf DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
# The single-header amalgamation ships alongside for header-only consumers.
install(FILES qvf_single.hpp DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/qvf)
install(EXPORT qvfTargets
        NAMESPACE qvf::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/qvf
        FILE qvfTargets.cmake)

write_basic_package_version_file(
  "${CMAKE_CURRENT_BINARY_DIR}/qvfConfigVersion.cmake"
  VERSION ${PROJECT_VERSION}
  COMPATIBILITY SameMajorVersion)
configure_package_config_file(
  "${CMAKE_CURRENT_SOURCE_DIR}/cmake/qvfConfig.cmake.in"
  "${CMAKE_CURRENT_BINARY_DIR}/qvfConfig.cmake"
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/qvf)
install(FILES
  "${CMAKE_CURRENT_BINARY_DIR}/qvfConfig.cmake"
  "${CMAKE_CURRENT_BINARY_DIR}/qvfConfigVersion.cmake"
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/qvf)

# Also usable straight from a build tree via FetchContent (the qvf::qvf alias
# above resolves without an install step).
export(EXPORT qvfTargets NAMESPACE qvf::
       FILE "${CMAKE_CURRENT_BINARY_DIR}/qvfTargets.cmake")
