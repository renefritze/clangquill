#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>

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

  /// @brief Re-writes a single translation unit's rows into an existing DB.
  ///
  /// Replaces only the IR sourced from @p module's files: every `symbols` row
  /// whose `file_id` belongs to one of those files (and, via the schema's
  /// `ON DELETE CASCADE` chain, that symbol's parameters, references, comments
  /// and group memberships) is deleted, then @p module is inserted afresh. Rows
  /// owned by other translation units are left untouched, so touching one input
  /// re-parses only that input rather than the whole module.
  ///
  /// @param module The single-TU IR to persist (its files plus their symbols).
  /// @param meta Metadata refreshed alongside the IR.
  void write_tu(const model::ParsedModule& module, const Meta& meta);

  /// @brief Reconstructs a ParsedModule from the database.
  /// @return The IR read back from storage.
  model::ParsedModule read();

 private:
  /// Map from source-file path to its assigned `files.id`.
  using FileIds = std::unordered_map<std::string, std::int64_t>;

  /// Upserts the `meta` rows describing this build.
  void put_meta(const Meta& meta);
  /// Inserts @p module's files (assumes an empty `files` table) and returns ids.
  FileIds insert_files(const model::ParsedModule& module);
  /// Upserts @p module's files (insert-or-update on path) and returns their ids.
  FileIds upsert_files(const model::ParsedModule& module);
  /// Deletes every symbol (and cascaded child rows) sourced from @p file_ids.
  void delete_files_rows(const FileIds& file_ids);
  /// Inserts all non-file IR rows (symbols, params, refs, comments, groups, …).
  void insert_rows(const model::ParsedModule& module, const FileIds& file_ids);

  Db db_;
};

}  // namespace clangquill::store
