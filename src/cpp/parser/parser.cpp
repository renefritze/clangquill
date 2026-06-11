#include "parser/parser.hpp"

#include <clang-c/Index.h>

#include <algorithm>
#include <atomic>
#include <exception>
#include <fstream>
#include <iterator>
#include <sstream>
#include <thread>
#include <unordered_set>
#include <vector>

#include "hash/sha256.hpp"
#include "parser/ast_visitor.hpp"
#include "parser/compile_db.hpp"
#include "parser/cursor_utils.hpp"

namespace clangquill::parser {
namespace {

CXIndex as_index(void* p) { return static_cast<CXIndex>(p); }

// RAII guard so the translation unit is disposed on every exit path,
// including exceptions thrown while collecting diagnostics or visiting.
struct TuGuard {
  CXTranslationUnit tu;
  ~TuGuard() {
    if (tu) clang_disposeTranslationUnit(tu);
  }
};

// Reads a file and appends a SourceFile row (path, sha256, size) if not already
// present in the module.
void record_file(const std::string& path, model::ParsedModule& out) {
  for (const auto& f : out.files) {
    if (f.path == path) return;
  }
  std::ifstream in(path, std::ios::binary);
  if (!in) return;
  std::ostringstream ss;
  ss << in.rdbuf();
  std::string contents = ss.str();

  model::SourceFile file;
  file.path = path;
  file.sha256 = hash::sha256_hex(contents);
  file.size_bytes = static_cast<std::int64_t>(contents.size());
  out.files.push_back(std::move(file));
}

// libclang inclusion visitor: records every file pulled into the translation
// unit (the main file plus everything it transitively `#include`s) so the M6
// cache can invalidate a re-parse when any tracked dependency changes.
void record_inclusion(CXFile included_file, CXSourceLocation* /*stack*/,
                      unsigned /*len*/, CXClientData data) {
  auto& out = *static_cast<model::ParsedModule*>(data);
  CXString name = clang_getFileName(included_file);
  const char* cstr = clang_getCString(name);
  if (cstr != nullptr && cstr[0] != '\0') record_file(cstr, out);
  clang_disposeString(name);
}

}  // namespace

Parser::Parser(ParseOptions options) : options_(std::move(options)) {
  index_ = clang_createIndex(/*excludeDeclarationsFromPCH=*/0,
                             /*displayDiagnostics=*/0);
}

Parser::~Parser() {
  if (index_) clang_disposeIndex(as_index(index_));
}

std::vector<std::string> Parser::build_args(const std::string& path) const {
  std::vector<std::string> args;

  if (options_.compile_commands_dir) {
    CompileDb db;
    if (db.load(*options_.compile_commands_dir)) {
      auto from_db = db.args_for(path);
      args.insert(args.end(), from_db.begin(), from_db.end());
    }
  }

  if (args.empty()) {
    args.push_back("-std=" + options_.std_flag);
    for (const auto& inc : options_.include_dirs) args.push_back("-I" + inc);
    for (const auto& def : options_.defines) args.push_back("-D" + def);
    for (const auto& extra : options_.extra_args) args.push_back(extra);
  }

  // Parse headers as C++ even without a .cpp extension.
  args.push_back("-xc++");
  return args;
}

bool Parser::parse_file(const std::string& path, model::ParsedModule& out) {
  std::vector<std::string> args = build_args(path);
  std::vector<const char*> argv;
  argv.reserve(args.size());
  for (const auto& a : args) argv.push_back(a.c_str());

  unsigned flags = CXTranslationUnit_SkipFunctionBodies |
                   CXTranslationUnit_DetailedPreprocessingRecord;
  if (options_.keep_going) flags |= CXTranslationUnit_KeepGoing;

  CXTranslationUnit tu = nullptr;
  CXErrorCode rc = clang_parseTranslationUnit2(
      as_index(index_), path.c_str(), argv.data(),
      static_cast<int>(argv.size()), nullptr, 0, flags, &tu);
  if (rc != CXError_Success || tu == nullptr) {
    out.diagnostics.push_back("failed to parse: " + path);
    if (tu) clang_disposeTranslationUnit(tu);
    return false;
  }
  TuGuard guard{tu};

  // Collect non-fatal diagnostics.
  unsigned n = clang_getNumDiagnostics(tu);
  for (unsigned i = 0; i < n; ++i) {
    CXDiagnostic d = clang_getDiagnostic(tu, i);
    if (clang_getDiagnosticSeverity(d) >= CXDiagnostic_Error) {
      out.diagnostics.push_back(to_string(clang_formatDiagnostic(
          d, clang_defaultDiagnosticDisplayOptions())));
    }
    clang_disposeDiagnostic(d);
  }

  record_file(path, out);
  // Track transitive #include dependencies so a header edit invalidates the
  // cached parse for every translation unit that pulled it in.
  clang_getInclusions(tu, record_inclusion, &out);
  visit_translation_unit(clang_getTranslationUnitCursor(tu), path, out);

  return true;
}

namespace {

// Move-appends every element of `src` onto the end of `dst`.
template <typename T>
void append(std::vector<T>& dst, std::vector<T>& src) {
  dst.insert(dst.end(), std::make_move_iterator(src.begin()),
             std::make_move_iterator(src.end()));
}

// Merges `part` into `out` in place, deduplicating source files by path
// (`files.path` is UNIQUE in the schema). All other rows are concatenated:
// each translation unit only emits symbols/references physically located in its
// own main file, so distinct inputs never collide, and symbol-keyed tables use
// INSERT OR REPLACE on write to absorb any genuine cross-file duplicates.
void merge_into(model::ParsedModule& out, model::ParsedModule& part,
                std::unordered_set<std::string>& seen_files) {
  for (auto& f : part.files) {
    if (seen_files.insert(f.path).second) out.files.push_back(std::move(f));
  }
  append(out.symbols, part.symbols);
  append(out.parameters, part.parameters);
  append(out.template_parameters, part.template_parameters);
  append(out.enumerators, part.enumerators);
  append(out.references, part.references);
  append(out.comments, part.comments);
  append(out.comment_fields, part.comment_fields);
  append(out.groups, part.groups);
  append(out.group_members, part.group_members);
  append(out.diagnostics, part.diagnostics);
}

}  // namespace

model::ParsedModule parse_files(const std::vector<std::string>& inputs,
                                const ParseOptions& options) {
  // One result slot per input keeps the merge deterministic (input order)
  // regardless of which thread parses which file or in what order it finishes.
  std::vector<model::ParsedModule> parts(inputs.size());

  unsigned effective_jobs = options.jobs > 0
                                ? static_cast<unsigned>(options.jobs)
                                : std::thread::hardware_concurrency();
  if (effective_jobs == 0) effective_jobs = 1;
  effective_jobs =
      std::min<unsigned>(effective_jobs, static_cast<unsigned>(inputs.size()));

  // Each worker owns its own Parser (hence its own CXIndex) and pulls the next
  // unclaimed input until the queue drains.
  std::atomic<std::size_t> next{0};
  auto worker = [&]() {
    Parser parser(options);
    std::size_t i;
    while ((i = next.fetch_add(1)) < inputs.size()) {
      // Parse into a local module so a mid-parse exception cannot leave
      // half-built rows in the slot: only a clean parse is published, and an
      // exception escaping a worker thread (which would otherwise call
      // std::terminate) is contained as a diagnostic (parse errors are already
      // reported this way) so the run carries on with the next input.
      try {
        model::ParsedModule part;
        parser.parse_file(inputs[i], part);
        parts[i] = std::move(part);
      } catch (const std::exception& e) {
        parts[i] = model::ParsedModule{};
        parts[i].diagnostics.push_back("exception parsing " + inputs[i] + ": " +
                                       e.what());
      } catch (...) {
        parts[i] = model::ParsedModule{};
        parts[i].diagnostics.push_back("unknown exception parsing " +
                                       inputs[i]);
      }
    }
  };

  if (effective_jobs <= 1) {
    worker();  // Avoid spawning a thread for the trivial single-job case.
  } else {
    std::vector<std::thread> threads;
    threads.reserve(effective_jobs);
    // Destroying a joinable std::thread calls std::terminate, so if launching
    // one throws (e.g. the OS refuses a new thread) join the ones already
    // started before letting the exception propagate.
    try {
      for (unsigned t = 0; t < effective_jobs; ++t) threads.emplace_back(worker);
    } catch (...) {
      for (auto& t : threads) {
        if (t.joinable()) t.join();
      }
      throw;
    }
    for (auto& t : threads) t.join();
  }

  model::ParsedModule merged;
  std::unordered_set<std::string> seen_files;
  for (auto& part : parts) merge_into(merged, part, seen_files);
  return merged;
}

}  // namespace clangquill::parser
