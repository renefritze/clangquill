#pragma once

#include <optional>
#include <string>
#include <vector>

/**
 * @file
 * @brief Reader for per-file flags from a compile_commands.json directory.
 */

namespace clangquill::parser {

/// @brief Looks up per-file compile arguments from a compile_commands.json directory.
///
/// Implemented with libclang's CXCompilationDatabase so we don't hand-parse JSON
/// for this purpose.
class CompileDb {
 public:
  CompileDb() = default;
  ~CompileDb();
  CompileDb(const CompileDb&) = delete;
  CompileDb& operator=(const CompileDb&) = delete;

  /// @brief Loads compile_commands.json from @p dir.
  /// @param dir Directory containing a compile_commands.json.
  /// @return `false` if the database is not available.
  bool load(const std::string& dir);

  /// @brief Whether a database is currently loaded.
  /// @return `true` once @ref load has succeeded.
  bool loaded() const { return db_ != nullptr; }

  /// @brief Returns the compile args for @p path.
  ///
  /// Excludes the compiler `argv[0]` and the source file itself.
  /// @param path The source file to look up.
  /// @return The argument list, or empty if there is no entry.
  std::vector<std::string> args_for(const std::string& path) const;

 private:
  void* db_ = nullptr;  // CXCompilationDatabase
};

}  // namespace clangquill::parser
