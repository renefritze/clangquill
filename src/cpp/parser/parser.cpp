#include "parser/parser.hpp"

#include <clang-c/Index.h>

#include <fstream>
#include <sstream>
#include <unordered_set>

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
  visit_translation_unit(clang_getTranslationUnitCursor(tu), path, out);

  return true;
}

}  // namespace clangquill::parser
