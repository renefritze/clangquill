#pragma once

#include <string>

namespace clangquill::model {

// The kind of C++ entity a symbol represents. Stored as an integer in SQLite.
enum class SymbolKind {
  Unknown = 0,
  Namespace,
  Class,
  Struct,
  Union,
  Function,
  Method,
  Constructor,
  Destructor,
  Field,
  Variable,
  Enum,
  Enumerator,
  Typedef,
  TypeAlias,
  FunctionTemplate,
  ClassTemplate,
};

// C++ access specifier. None is used for namespace/file-scope entities.
enum class AccessKind {
  None = 0,
  Public,
  Protected,
  Private,
};

// Storage class. None means "unspecified".
enum class StorageKind {
  None = 0,
  Static,
  Extern,
  Register,
  ThreadLocal,
  Auto,
};

// Where a symbol is declared/defined. file_path is resolved to files.id at
// write time so the IR stays serializable without pointers.
struct SourceLocation {
  std::string file_path;  // absolute, normalized; empty when unknown
  unsigned line = 0;
  unsigned column = 0;
};

// A documented (or undocumented) C++ entity. `usr` is the stable identity key
// (clang USR of the canonical cursor) and the primary key in SQLite.
struct Symbol {
  std::string usr;
  std::string parent_usr;      // enclosing namespace/record USR; empty at TU scope
  SymbolKind kind = SymbolKind::Unknown;
  std::string spelling;        // unqualified name
  std::string qualified_name;  // e.g. geo::Circle
  std::string display_name;    // includes parameters for overloads
  std::string signature;       // pretty-printed declaration (functions/methods)
  std::string type_repr;       // spelling of the cursor's type
  AccessKind access = AccessKind::None;
  StorageKind storage = StorageKind::None;
  bool is_definition = false;
  bool is_documented = false;  // carries a non-empty raw comment
  std::string content_hash;    // stable hash of semantic fields (feeds M6 caching)
  SourceLocation location;
};

}  // namespace clangquill::model
