// nanobind entry point for the clangquill C++ core.
//
// M1 keeps this intentionally small: it proves the scikit-build-core + CMake +
// nanobind toolchain and, when libclang is linked, that the libclang C API is
// actually callable. Real parsing (M2) builds on top of this module.

#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>

#include "core/version.hpp"

#if defined(CLANGQUILL_HAVE_LIBCLANG)
#include <clang-c/Index.h>
#endif

namespace nb = nanobind;

namespace {

// True when the extension was compiled and linked against libclang.
bool have_libclang() {
#if defined(CLANGQUILL_HAVE_LIBCLANG)
  return true;
#else
  return false;
#endif
}

// The libclang version string, or empty when the stub backend is in use. This
// exercises a real libclang C-API call so the linkage is verified at runtime.
std::string libclang_version() {
#if defined(CLANGQUILL_HAVE_LIBCLANG)
  CXString s = clang_getClangVersion();
  const char *cstr = clang_getCString(s);
  std::string out = cstr ? cstr : "";
  clang_disposeString(s);
  return out;
#else
  return {};
#endif
}

}  // namespace

NB_MODULE(_core, m) {
  m.doc() = "clangquill C++ core (libclang-backed API extraction)";
  m.attr("__core_version__") = clangquill::core_version();
  m.def("have_libclang", &have_libclang,
        "Whether the core was built against libclang.");
  m.def("libclang_version", &libclang_version,
        "libclang version string, or '' when built without libclang.");
}
