#pragma once

#include <sqlite3.h>

#include <cstdint>
#include <stdexcept>
#include <string>
#include <string_view>

namespace clangquill::store {

// Owning wrapper around sqlite3*. Enables foreign keys and WAL on open.
class Db {
 public:
  explicit Db(const std::string& path) {
    if (sqlite3_open(path.c_str(), &db_) != SQLITE_OK) {
      std::string msg = db_ ? sqlite3_errmsg(db_) : "out of memory";
      sqlite3_close(db_);
      throw std::runtime_error("sqlite3_open: " + msg);
    }
    exec("PRAGMA foreign_keys=ON;");
    exec("PRAGMA journal_mode=WAL;");
    exec("PRAGMA synchronous=NORMAL;");
  }
  ~Db() { sqlite3_close(db_); }
  Db(const Db&) = delete;
  Db& operator=(const Db&) = delete;

  sqlite3* get() const { return db_; }

  void exec(const char* sql) {
    char* err = nullptr;
    if (sqlite3_exec(db_, sql, nullptr, nullptr, &err) != SQLITE_OK) {
      std::string msg = err ? err : "exec failed";
      sqlite3_free(err);
      throw std::runtime_error("sqlite3_exec: " + msg);
    }
  }

 private:
  sqlite3* db_ = nullptr;
};

// Owning wrapper around a prepared statement with typed bind/column helpers.
class Stmt {
 public:
  Stmt(Db& db, std::string_view sql) : db_(db.get()) {
    if (sqlite3_prepare_v2(db_, sql.data(), static_cast<int>(sql.size()), &st_,
                           nullptr) != SQLITE_OK) {
      throw std::runtime_error(std::string("sqlite3_prepare_v2: ") +
                               sqlite3_errmsg(db_));
    }
  }
  ~Stmt() { sqlite3_finalize(st_); }
  Stmt(const Stmt&) = delete;
  Stmt& operator=(const Stmt&) = delete;

  void bind(int i, std::string_view s) {
    // SQLITE_TRANSIENT: sqlite copies the bytes, so the source may outlive the
    // call or not — safe regardless of the bound string's lifetime.
    sqlite3_bind_text(st_, i, s.data(), static_cast<int>(s.size()),
                      SQLITE_TRANSIENT);
  }
  void bind(int i, std::int64_t v) { sqlite3_bind_int64(st_, i, v); }
  void bind(int i, int v) { sqlite3_bind_int64(st_, i, v); }
  void bind_null(int i) { sqlite3_bind_null(st_, i); }

  // Steps the statement. Returns true if a row is available (SQLITE_ROW).
  bool step() {
    int rc = sqlite3_step(st_);
    if (rc != SQLITE_ROW && rc != SQLITE_DONE) {
      throw std::runtime_error(std::string("sqlite3_step: ") +
                               sqlite3_errmsg(db_));
    }
    return rc == SQLITE_ROW;
  }

  void reset() {
    sqlite3_reset(st_);
    sqlite3_clear_bindings(st_);
  }

  std::string column_text(int i) const {
    const auto* p = sqlite3_column_text(st_, i);
    return p ? reinterpret_cast<const char*>(p) : "";
  }
  std::int64_t column_int64(int i) const { return sqlite3_column_int64(st_, i); }

 private:
  sqlite3* db_;
  sqlite3_stmt* st_ = nullptr;
};

// RAII transaction: commit() on success; rolls back if destroyed uncommitted.
class Transaction {
 public:
  explicit Transaction(Db& db) : db_(db) { db_.exec("BEGIN;"); }
  ~Transaction() {
    if (!done_) {
      try {
        db_.exec("ROLLBACK;");
      } catch (...) {  // nothing actionable during stack unwinding
      }
    }
  }
  Transaction(const Transaction&) = delete;
  Transaction& operator=(const Transaction&) = delete;

  void commit() {
    db_.exec("COMMIT;");
    done_ = true;
  }

 private:
  Db& db_;
  bool done_ = false;
};

}  // namespace clangquill::store
