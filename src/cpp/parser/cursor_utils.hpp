#pragma once

#include <clang-c/Index.h>

#include <string>

#include "model/symbol.hpp"

namespace clangquill::parser {

// RAII wrapper that guarantees clang_disposeString.
class ScopedCXString {
 public:
  explicit ScopedCXString(CXString s) : s_(s) {}
  ~ScopedCXString() { clang_disposeString(s_); }
  ScopedCXString(const ScopedCXString&) = delete;
  ScopedCXString& operator=(const ScopedCXString&) = delete;

  std::string str() const {
    const char* c = clang_getCString(s_);
    return c ? c : "";
  }

 private:
  CXString s_;
};

inline std::string to_string(CXString s) { return ScopedCXString(s).str(); }

inline std::string spelling(CXCursor c) {
  return to_string(clang_getCursorSpelling(c));
}
inline std::string display_name(CXCursor c) {
  return to_string(clang_getCursorDisplayName(c));
}
inline std::string usr(CXCursor c) {
  return to_string(clang_getCursorUSR(c));
}

// Maps a libclang cursor kind to our SymbolKind, or Unknown if not a documented
// entity in M2.
model::SymbolKind map_kind(CXCursorKind kind);

// USR of the canonical cursor (collapses forward decls and definitions).
std::string canonical_usr(CXCursor c);

// Qualified name built by walking semantic parents (e.g. "geo::Circle").
std::string qualified_name(CXCursor c);

// Pretty-printed declaration with terse output (no body); empty on failure.
std::string pretty_signature(CXCursor c);

model::AccessKind map_access(CXCursor c);
model::StorageKind map_storage(CXCursor c);

// True when the cursor's location is in the given main file path.
bool in_file(CXCursor c, const std::string& main_file);

}  // namespace clangquill::parser
