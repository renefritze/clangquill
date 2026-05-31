#pragma once

#include <optional>
#include <string>
#include <vector>

namespace clangquill::parser {

// Looks up per-file compile arguments from a compile_commands.json directory.
// Implemented with libclang's CXCompilationDatabase so we don't hand-parse JSON
// for this purpose.
class CompileDb {
 public:
  CompileDb() = default;
  ~CompileDb();
  CompileDb(const CompileDb&) = delete;
  CompileDb& operator=(const CompileDb&) = delete;

  // Loads compile_commands.json from `dir`. Returns false if not available.
  bool load(const std::string& dir);

  bool loaded() const { return db_ != nullptr; }

  // Returns the compile args for `path` (without the compiler argv[0] and
  // without the source file itself), or empty if there is no entry.
  std::vector<std::string> args_for(const std::string& path) const;

 private:
  void* db_ = nullptr;  // CXCompilationDatabase
};

}  // namespace clangquill::parser
