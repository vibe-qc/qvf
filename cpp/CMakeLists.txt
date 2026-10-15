cmake_minimum_required(VERSION 3.16)
project(qvf_writer LANGUAGES CXX C VERSION 0.3.0)

# Zero external dependencies — only the C++17 standard library.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

if(MSVC)
  # The sources are UTF-8 (comments and one string literal contain non-ASCII
  # text). Without /utf-8 MSVC reads them in the active ANSI code page, which
  # raises warning C4819 on some locales (an error under /WX).
  add_compile_options(/utf-8)
endif()

# --- fuzzing (off by default) -------------------------------------------------
# -DQVF_FUZZ=ON (clang only) builds cpp/fuzz/zip_reader_fuzzer, a libFuzzer
# target over the ZIP reader and the validator. Everything in such a build is
# compiled with ASan + UBSan and coverage instrumentation, so the fuzzer
# reaches into the library. Where clang ships no libFuzzer runtime (Apple
# clang), the target links fuzz/standalone_fuzz_main.cpp instead.
option(QVF_FUZZ "Build the fuzz targets in cpp/fuzz (clang)" OFF)
if(QVF_FUZZ)
  if(NOT CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    message(FATAL_ERROR "QVF_FUZZ=ON needs clang (-fsanitize=fuzzer)")
  endif()
  add_compile_options(-fsanitize=address,undefined -fno-sanitize-recover=undefined
                      -fno-omit-frame-pointer -g -fsanitize=fuzzer-no-link)
  add_link_options(-fsanitize=address,undefined)
endif()

# --- library ---------------------------------------------------------------
# src/qvf.cpp is the C++ writer; src/qvf_c.cpp is the extern "C" ABI wrapper;
# src/qvf_reader.cpp is the C++ reader (manifest, members, validation);
# src/qvf_container.cpp is the ZIP layer both use (qvf/container.hpp).
add_library(qvf STATIC src/qvf.cpp src/qvf_c.cpp src/qvf_reader.cpp
                       src/qvf_container.cpp)
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

# The conformance runner: the expected.json check format of
# conformance/README.md over the positive, negative and legacy corpora.
add_executable(run_conformance examples/run_conformance.cpp)
target_link_libraries(run_conformance PRIVATE qvf)

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

# The container layer (ZIP64, data descriptors, streaming, caps) and the
# streaming / updating writer entry points. Scratch files go to the build tree;
# the corpus' zip64.qvf and data_descriptor.qvf are updated too when present.
add_executable(qvf_container_tests tests/test_container.cpp)
target_link_libraries(qvf_container_tests PRIVATE qvf)
target_include_directories(qvf_container_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
add_test(NAME qvf_container_tests
         COMMAND qvf_container_tests ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/corpus
         WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR})

# Validator hardening: malformed archives built in memory, plus the negative
# conformance corpus (every archive must yield exactly its expected finding
# codes). A standalone copy of cpp/ without ../conformance skips the latter.
add_executable(qvf_reader_tests tests/test_reader.cpp)
target_link_libraries(qvf_reader_tests PRIVATE qvf)
target_include_directories(qvf_reader_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
add_test(NAME qvf_reader_tests COMMAND qvf_reader_tests)
# Drives the generated JSON Schema checker for the parity test against the
# Python reference (python/tests/test_schema_checker_parity.py).
add_executable(qvf_schema_check tests/schema_check_tool.cpp)
target_link_libraries(qvf_schema_check PRIVATE qvf)
target_include_directories(qvf_schema_check PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
add_test(NAME qvf_negative_corpus
         COMMAND qvf_reader_tests --negative
                 ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/negative)
set_tests_properties(qvf_negative_corpus PROPERTIES SKIP_RETURN_CODE 77)
# The typed manifest model (qvf/model.hpp) round-trips every conformance
# manifest losslessly.
add_test(NAME qvf_model_roundtrip
         COMMAND qvf_reader_tests --model-roundtrip
                 ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/corpus
                 ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/negative
                 ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/legacy)
set_tests_properties(qvf_model_roundtrip PROPERTIES SKIP_RETURN_CODE 77)

# The whole conformance suite through the C++ reader: every positive archive
# must decode to its expected.json values, every must-fail archive must be
# rejected with its codes, and the legacy archives (qvf_version 2) judged as
# their expected.json says: valid, with the warning W_VERSION_WITHDRAWN. A
# standalone copy of cpp/ without ../conformance skips it.
add_test(NAME qvf_conformance
         COMMAND run_conformance
                 ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/corpus
                 --negative ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/negative
                 --legacy ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/legacy)
set_tests_properties(qvf_conformance PROPERTIES SKIP_RETURN_CODE 77)
# The same without the generated JSON Schema check: the behaviour of a
# validator without a schema engine (W_SCHEMA_SKIPPED) stays testable.
add_test(NAME qvf_conformance_no_schema
         COMMAND run_conformance
                 ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/corpus
                 --negative ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/negative
                 --legacy ${CMAKE_CURRENT_SOURCE_DIR}/../conformance/legacy
                 --no-schema-check)
set_tests_properties(qvf_conformance_no_schema PROPERTIES SKIP_RETURN_CODE 77)

# --- fuzz targets (QVF_FUZZ=ON) ---------------------------------------------
if(QVF_FUZZ)
  include(CheckCXXSourceCompiles)
  set(CMAKE_REQUIRED_FLAGS "-fsanitize=fuzzer")
  set(CMAKE_REQUIRED_LINK_OPTIONS "-fsanitize=fuzzer")
  check_cxx_source_compiles(
    "#include <cstddef>\n#include <cstdint>\nextern \"C\" int LLVMFuzzerTestOneInput(const uint8_t*, size_t) { return 0; }"
    QVF_HAVE_LIBFUZZER)
  unset(CMAKE_REQUIRED_FLAGS)
  unset(CMAKE_REQUIRED_LINK_OPTIONS)
  add_executable(zip_reader_fuzzer fuzz/zip_reader_fuzzer.cpp)
  target_link_libraries(zip_reader_fuzzer PRIVATE qvf)
  if(QVF_HAVE_LIBFUZZER)
    target_compile_options(zip_reader_fuzzer PRIVATE -fsanitize=fuzzer)
    target_link_options(zip_reader_fuzzer PRIVATE -fsanitize=fuzzer)
  else()
    message(WARNING "QVF_FUZZ: this clang has no libFuzzer runtime; zip_reader_fuzzer "
                    "links fuzz/standalone_fuzz_main.cpp (replay and random mutation, "
                    "no coverage feedback)")
    target_sources(zip_reader_fuzzer PRIVATE fuzz/standalone_fuzz_main.cpp)
  endif()
endif()

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
