cmake_minimum_required(VERSION 3.26...3.29)

project(
  clangquill
  LANGUAGES CXX
  DESCRIPTION "libclang -> Sphinx MyST API-docs generator core")

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# --- Python + nanobind -------------------------------------------------------
# scikit-build-core puts the right Python here; find nanobind via its pip wheel.
find_package(Python 3.11 REQUIRED COMPONENTS Interpreter Development.Module)

execute_process(
  COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
  OUTPUT_STRIP_TRAILING_WHITESPACE
  OUTPUT_VARIABLE nanobind_ROOT)
find_package(nanobind CONFIG REQUIRED)

# --- Optional libclang -------------------------------------------------------
# CLANGQUILL_WITH_LIBCLANG: ON | OFF | AUTO (default). When ON/AUTO and libclang
# is found, the core links it and CLANGQUILL_HAVE_LIBCLANG is defined. This keeps
# M1 (build system) independent of the libclang-sourcing spike (#4).
set(CLANGQUILL_WITH_LIBCLANG "AUTO" CACHE STRING "Link libclang: ON, OFF or AUTO")
include(cmake/FindLibClang.cmake)

# --- Core extension ----------------------------------------------------------
nanobind_add_module(
  _core
  STABLE_ABI
  NB_STATIC
  src/cpp/bindings/module.cpp)

target_include_directories(_core PRIVATE src/cpp)

if(CLANGQUILL_LIBCLANG_FOUND)
  target_link_libraries(_core PRIVATE clangquill::libclang)
  target_compile_definitions(_core PRIVATE CLANGQUILL_HAVE_LIBCLANG=1)
  message(STATUS "clangquill: building WITH libclang")
else()
  message(STATUS "clangquill: building WITHOUT libclang (stub backend)")
endif()

install(TARGETS _core LIBRARY DESTINATION clangquill)
