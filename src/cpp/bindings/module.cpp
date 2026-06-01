// nanobind entry point for the clangquill C++ core.
//
// Exposes the libclang-backed parser (parse_to_sqlite) and small probes used by
// tests. Reads of the SQLite artifact happen in Python via stdlib sqlite3.

#include <nanobind/nanobind.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <stdexcept>

#include "core/version.hpp"
#include "store/schema.hpp"

#if defined(CLANGQUILL_HAVE_LIBCLANG)
#include <clang-c/Index.h>

#include "parser/parser.hpp"
#include "store/sqlite_store.hpp"
#endif

namespace nb = nanobind;

namespace {

bool have_libclang() {
#if defined(CLANGQUILL_HAVE_LIBCLANG)
  return true;
#else
  return false;
#endif
}

std::string libclang_version() {
#if defined(CLANGQUILL_HAVE_LIBCLANG)
  CXString s = clang_getClangVersion();
  const char* cstr = clang_getCString(s);
  std::string out = cstr ? cstr : "";
  clang_disposeString(s);
  return out;
#else
  return {};
#endif
}

// nanobind-friendly mirror of parser::ParseOptions.
struct PyParseOptions {
  std::string std_flag = "c++20";
  std::vector<std::string> include_dirs;
  std::vector<std::string> defines;
  std::vector<std::string> extra_args;
  std::optional<std::string> compile_commands_dir;
  bool keep_going = true;
};

struct ParseResult {
  int symbol_count = 0;
  int reference_count = 0;
  int file_count = 0;
  std::vector<std::string> diagnostics;
};

ParseResult parse_to_sqlite(const std::vector<std::string>& inputs,
                            const std::string& db_path,
                            const PyParseOptions& opt) {
#if !defined(CLANGQUILL_HAVE_LIBCLANG)
  (void)inputs;
  (void)db_path;
  (void)opt;
  throw std::runtime_error(
      "clangquill._core was built without libclang; cannot parse");
#else
  clangquill::parser::ParseOptions po;
  po.std_flag = opt.std_flag;
  po.include_dirs = opt.include_dirs;
  po.defines = opt.defines;
  po.extra_args = opt.extra_args;
  po.compile_commands_dir = opt.compile_commands_dir;
  po.keep_going = opt.keep_going;

  clangquill::parser::Parser parser(po);
  clangquill::model::ParsedModule mod;
  for (const auto& in : inputs) parser.parse_file(in, mod);

  clangquill::store::SqliteStore store(db_path);
  store.write(mod, clangquill::store::Meta::current());

  ParseResult res;
  res.symbol_count = static_cast<int>(mod.symbols.size());
  res.reference_count = static_cast<int>(mod.references.size());
  res.file_count = static_cast<int>(mod.files.size());
  res.diagnostics = mod.diagnostics;
  return res;
#endif
}

}  // namespace

NB_MODULE(_core, m) {
  m.doc() = "clangquill C++ core (libclang-backed API extraction)";
  m.attr("__core_version__") = clangquill::core_version();
  m.attr("SCHEMA_VERSION") = clangquill::store::kSchemaVersion;
  m.def("have_libclang", &have_libclang,
        "Whether the core was built against libclang.");
  m.def("libclang_version", &libclang_version,
        "libclang version string, or '' when built without libclang.");

  nb::class_<PyParseOptions>(m, "ParseOptions")
      .def(nb::init<>())
      .def_rw("std_flag", &PyParseOptions::std_flag)
      .def_rw("include_dirs", &PyParseOptions::include_dirs)
      .def_rw("defines", &PyParseOptions::defines)
      .def_rw("extra_args", &PyParseOptions::extra_args)
      .def_rw("compile_commands_dir", &PyParseOptions::compile_commands_dir)
      .def_rw("keep_going", &PyParseOptions::keep_going);

  nb::class_<ParseResult>(m, "ParseResult")
      .def_ro("symbol_count", &ParseResult::symbol_count)
      .def_ro("reference_count", &ParseResult::reference_count)
      .def_ro("file_count", &ParseResult::file_count)
      .def_ro("diagnostics", &ParseResult::diagnostics);

  m.def("parse_to_sqlite", &parse_to_sqlite, nb::arg("inputs"),
        nb::arg("db_path"), nb::arg("options") = PyParseOptions{},
        "Parse C++ inputs and write the IR into a SQLite DB at db_path.");
}
