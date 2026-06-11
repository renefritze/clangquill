// nanobind entry point for the clangquill C++ core.
//
// Exposes the libclang-backed parser (parse_to_sqlite) and small probes used by
// tests. Reads of the SQLite artifact happen in Python via stdlib sqlite3.

#include <nanobind/nanobind.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <cstddef>
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
  int jobs = 0;
  int tu_batch = 0;
};

// One input translation unit and the full set of files it pulled in (the input
// itself plus every transitive `#include`). Lets the Python cache attribute each
// dependency to the input that needs it, so a header edit re-parses only the
// translation units that include it.
struct TuFiles {
  std::string input;
  std::vector<std::string> files;
};

struct ParseResult {
  int symbol_count = 0;
  int reference_count = 0;
  int file_count = 0;
  std::vector<std::string> diagnostics;
  std::vector<TuFiles> translation_units;
};

#if defined(CLANGQUILL_HAVE_LIBCLANG)
clangquill::parser::ParseOptions to_core_options(const PyParseOptions& opt) {
  clangquill::parser::ParseOptions po;
  po.std_flag = opt.std_flag;
  po.include_dirs = opt.include_dirs;
  po.defines = opt.defines;
  po.extra_args = opt.extra_args;
  po.compile_commands_dir = opt.compile_commands_dir;
  po.keep_going = opt.keep_going;
  po.jobs = opt.jobs;
  po.tu_batch = opt.tu_batch;
  return po;
}

ParseResult result_from_module(const clangquill::model::ParsedModule& mod) {
  ParseResult res;
  res.symbol_count = static_cast<int>(mod.symbols.size());
  res.reference_count = static_cast<int>(mod.references.size());
  res.file_count = static_cast<int>(mod.files.size());
  res.diagnostics = mod.diagnostics;
  return res;
}
#endif

#if defined(CLANGQUILL_HAVE_LIBCLANG)
// Shared implementation of the parse entry points. `replace_only` selects the
// incremental write path: only the given inputs' rows are replaced inside an
// existing IR (every input must parse, or the whole call fails before any
// write), while a full parse rebuilds the database and tolerates per-input
// failures as diagnostics.
ParseResult parse_inputs(const std::vector<std::string>& inputs,
                         const std::string& db_path, const PyParseOptions& opt,
                         bool replace_only) {
  // Parse all inputs (batched into umbrella TUs and parallel, honouring
  // opt.jobs/opt.tu_batch) while capturing each translation unit's file set so
  // the cache can attribute every dependency to the input that pulled it in.
  std::vector<std::vector<std::string>> tu_files;
  std::vector<bool> tu_ok;
  clangquill::model::ParsedModule mod = clangquill::parser::parse_files(
      inputs, to_core_options(opt), &tu_files, &tu_ok);

  if (replace_only) {
    // Bail before writing on any hard parse failure: otherwise that file's
    // existing rows would be deleted and replaced with nothing, wiping good
    // documentation.
    for (std::size_t i = 0; i < inputs.size(); ++i) {
      if (!tu_ok[i]) {
        throw std::runtime_error("failed to parse translation unit: " +
                                 inputs[i]);
      }
    }
  }

  clangquill::store::SqliteStore store(db_path);
  if (replace_only) {
    store.write_tus(mod, clangquill::store::Meta::current(), inputs);
  } else {
    store.write(mod, clangquill::store::Meta::current());
  }

  ParseResult res = result_from_module(mod);
  res.translation_units.reserve(inputs.size());
  for (std::size_t i = 0; i < inputs.size(); ++i) {
    TuFiles tu;
    tu.input = inputs[i];
    tu.files = std::move(tu_files[i]);
    res.translation_units.push_back(std::move(tu));
  }
  return res;
}
#endif

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
  return parse_inputs(inputs, db_path, opt, /*replace_only=*/false);
#endif
}

// Re-parses the given inputs into an existing IR, replacing only those
// translation units' rows in one transaction. The caller picks which inputs are
// stale (via the cache) and runs this once for the whole stale set instead of
// rebuilding the whole module.
ParseResult parse_tus_to_sqlite(const std::vector<std::string>& inputs,
                                const std::string& db_path,
                                const PyParseOptions& opt) {
#if !defined(CLANGQUILL_HAVE_LIBCLANG)
  (void)inputs;
  (void)db_path;
  (void)opt;
  throw std::runtime_error(
      "clangquill._core was built without libclang; cannot parse");
#else
  return parse_inputs(inputs, db_path, opt, /*replace_only=*/true);
#endif
}

// Single-input convenience form of parse_tus_to_sqlite.
ParseResult parse_tu_to_sqlite(const std::string& input,
                               const std::string& db_path,
                               const PyParseOptions& opt) {
  return parse_tus_to_sqlite({input}, db_path, opt);
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
      .def_rw("keep_going", &PyParseOptions::keep_going)
      .def_rw("jobs", &PyParseOptions::jobs)
      .def_rw("tu_batch", &PyParseOptions::tu_batch);

  nb::class_<TuFiles>(m, "TuFiles")
      .def_ro("input", &TuFiles::input)
      .def_ro("files", &TuFiles::files);

  nb::class_<ParseResult>(m, "ParseResult")
      .def_ro("symbol_count", &ParseResult::symbol_count)
      .def_ro("reference_count", &ParseResult::reference_count)
      .def_ro("file_count", &ParseResult::file_count)
      .def_ro("diagnostics", &ParseResult::diagnostics)
      .def_ro("translation_units", &ParseResult::translation_units);

  m.def("parse_to_sqlite", &parse_to_sqlite, nb::arg("inputs"),
        nb::arg("db_path"), nb::arg("options") = PyParseOptions{},
        "Parse C++ inputs and write the IR into a SQLite DB at db_path.");

  m.def("parse_tus_to_sqlite", &parse_tus_to_sqlite, nb::arg("inputs"),
        nb::arg("db_path"), nb::arg("options") = PyParseOptions{},
        "Re-parse the given inputs into an existing SQLite IR (in parallel, in "
        "one transaction), replacing only those translation units' rows.");

  m.def("parse_tu_to_sqlite", &parse_tu_to_sqlite, nb::arg("input"),
        nb::arg("db_path"), nb::arg("options") = PyParseOptions{},
        "Re-parse one input into an existing SQLite IR, replacing only that "
        "translation unit's rows.");
}
