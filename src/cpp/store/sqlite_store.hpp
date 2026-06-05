#pragma once

#include <string>

#include "model/module.hpp"
#include "store/sqlite_raii.hpp"

/**
 * @file
 * @brief SQLite-backed persistence for the parsed IR.
 */

namespace clangquill::store {

/// @brief Metadata written into the `meta` table.
struct Meta {
  int schema_version = 0;        ///< On-disk schema version.
  std::string core_version;      ///< Version of the native core that wrote the DB.
  std::string libclang_version;  ///< Version of libclang used for the parse.

  /// @brief Builds the Meta describing the current build.
  /// @return Metadata populated from the compiled-in versions.
  static Meta current();
};

/// @brief Persists a ParsedModule into the SQLite artifact and reads it back.
///
/// The production Python layer reads the DB directly via stdlib sqlite3;
/// @ref read exists mainly for round-trip testing.
class SqliteStore {
 public:
  /// @brief Opens (creating if needed) the database at @p path.
  /// @param path Filesystem path of the SQLite database.
  explicit SqliteStore(const std::string& path);

  /// @brief Writes the whole module in a single transaction.
  ///
  /// `files.id` is resolved from each symbol's location path.
  /// @param module The IR to persist.
  /// @param meta Metadata stored alongside the IR.
  void write(const model::ParsedModule& module, const Meta& meta);

  /// @brief Reconstructs a ParsedModule from the database.
  /// @return The IR read back from storage.
  model::ParsedModule read();

 private:
  Db db_;
};

}  // namespace clangquill::store
