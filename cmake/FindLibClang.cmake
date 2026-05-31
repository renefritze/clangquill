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

# Allow an llvm-config to point us at the right prefix.
find_program(LLVM_CONFIG_EXECUTABLE NAMES llvm-config llvm-config-18 llvm-config-17)
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
  NAMES clang libclang clang-18 clang-17
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
