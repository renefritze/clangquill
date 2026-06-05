#pragma once

#include <string>

#include "model/symbol.hpp"

namespace clangquill::model {

// The kind of relationship a Reference records between two symbols/types.
enum class RefKind {
  BaseClass = 0,
  ParamType,
  ReturnType,
  FieldType,
  VariableType,
  UnderlyingType,   // typedef / alias target
  EnumIntegerType,
  Friend,           // record -> befriended function/class
};

// A directed edge in the cross-reference graph. `to_usr` may be empty when the
// target is a builtin, a template parameter, or a declaration not present in
// this translation unit; `to_spelling` is always populated. There is
// deliberately no foreign key on `to_usr` so cross-TU references are first
// class.
struct Reference {
  std::string from_usr;
  RefKind kind = RefKind::BaseClass;
  std::string to_usr;       // empty when unresolved
  std::string to_spelling;  // the written type text, always populated
  bool is_resolved = false;
  AccessKind access = AccessKind::None;  // meaningful for base classes
  int ordinal = 0;                       // param/base index for stable ordering
};

}  // namespace clangquill::model
