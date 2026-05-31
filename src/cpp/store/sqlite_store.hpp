#pragma once

#include <string>

#include "model/module.hpp"
#include "store/sqlite_raii.hpp"

namespace clangquill::store {

// Metadata written into the `meta` table.
struct Meta {
  int schema_version = 0;
  std::string core_version;
  std::string libclang_version;

  static Meta current();
};

// Persists a ParsedModule into the SQLite intermediate artifact and reads it
// back. The production Python layer reads the DB directly via stdlib sqlite3;
// read() exists mainly for round-trip testing.
class SqliteStore {
 public:
  explicit SqliteStore(const std::string& path);

  // Writes the whole module in a single transaction. files.id is resolved from
  // each symbol's location path.
  void write(const model::ParsedModule& module, const Meta& meta);

  // Reconstructs a ParsedModule from the database.
  model::ParsedModule read();

 private:
  Db db_;
};

}  // namespace clangquill::store
