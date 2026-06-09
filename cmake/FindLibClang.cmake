# Locate libclang (the C API) and expose it as the imported target
# clangquill::libclang plus the cache variable CLANGQUILL_LIBCLANG_FOUND.
#
# Honors CLANGQUILL_WITH_LIBCLANG (ON | OFF | AUTO):
#   OFF  - never look; build the stub backend.
#   AUTO - look; build with libclang only if found (default, no hard failure).
#   ON   - look; fail the configure if it cannot be found.
#
# Discovery order: an explicit hint (LibClang_ROOT / llvm-config), then common
# system locations. The manylinux build wires this to a prebuilt LLVM (see #4).

set(CLANGQUILL_LIBCLANG_FOUND FALSE)

if(CLANGQUILL_WITH_LIBCLANG STREQUAL "OFF")
  return()
endif()

# Build versioned tool/library name lists from the bundled-libclang pin (the
# single source of truth in tools/ci/llvm-version.txt) down to a supported floor,
# so the search ceiling tracks the pin without a second place to edit.
file(STRINGS "${CMAKE_CURRENT_LIST_DIR}/../tools/ci/llvm-version.txt"
     _llvm_pin LIMIT_COUNT 1)
# Fail clearly on a malformed/edited pin rather than with a cryptic foreach error.
if(NOT _llvm_pin MATCHES "^[0-9]+\\.[0-9]+\\.[0-9]+$")
  message(FATAL_ERROR
    "Invalid LLVM pin '${_llvm_pin}' in tools/ci/llvm-version.txt; "
    "expected MAJOR.MINOR.PATCH")
endif()
string(REGEX REPLACE "^([0-9]+)\\..*$" "\\1" _llvm_major "${_llvm_pin}")
if(_llvm_major LESS 17)
  message(FATAL_ERROR
    "LLVM pin major ${_llvm_major} is below the supported floor (17)")
endif()
# foreach(RANGE) only counts up, so collect ascending then reverse to newest-first.
set(_llvm_config_versioned "")
set(_llvm_lib_versioned "")
foreach(_v RANGE 17 ${_llvm_major})
  list(APPEND _llvm_config_versioned "llvm-config-${_v}")
  list(APPEND _llvm_lib_versioned "clang-${_v}")
endforeach()
list(REVERSE _llvm_config_versioned)
list(REVERSE _llvm_lib_versioned)
# Unversioned names first (a system default wins), then versioned newest-first.
set(_llvm_config_names llvm-config ${_llvm_config_versioned})
set(_llvm_lib_names clang libclang ${_llvm_lib_versioned})

# Allow an llvm-config to point us at the right prefix. Newer versions are
# listed first so a recent toolchain wins (c++23/c++26 need a recent clang).
find_program(LLVM_CONFIG_EXECUTABLE NAMES ${_llvm_config_names})
if(LLVM_CONFIG_EXECUTABLE)
  execute_process(
    COMMAND "${LLVM_CONFIG_EXECUTABLE}" --includedir
    OUTPUT_STRIP_TRAILING_WHITESPACE OUTPUT_VARIABLE _llvm_incdir
    ERROR_QUIET)
  execute_process(
    COMMAND "${LLVM_CONFIG_EXECUTABLE}" --libdir
    OUTPUT_STRIP_TRAILING_WHITESPACE OUTPUT_VARIABLE _llvm_libdir
    ERROR_QUIET)
endif()

find_path(
  LibClang_INCLUDE_DIR
  NAMES clang-c/Index.h
  HINTS ${LibClang_ROOT} ${_llvm_incdir}
  PATH_SUFFIXES include)

find_library(
  LibClang_LIBRARY
  NAMES ${_llvm_lib_names}
  HINTS ${LibClang_ROOT} ${_llvm_libdir}
  PATH_SUFFIXES lib lib64)

if(LibClang_INCLUDE_DIR AND LibClang_LIBRARY)
  add_library(clangquill::libclang UNKNOWN IMPORTED)
  set_target_properties(
    clangquill::libclang PROPERTIES
    IMPORTED_LOCATION "${LibClang_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${LibClang_INCLUDE_DIR}")
  set(CLANGQUILL_LIBCLANG_FOUND TRUE)
  message(STATUS "clangquill: found libclang at ${LibClang_LIBRARY}")
elseif(CLANGQUILL_WITH_LIBCLANG STREQUAL "ON")
  message(
    FATAL_ERROR
    "CLANGQUILL_WITH_LIBCLANG=ON but libclang was not found. "
    "Install libclang-dev or set LibClang_ROOT to an LLVM prefix.")
else()
  message(STATUS "clangquill: libclang not found; building stub backend")
endif()
