#pragma once

#include <string>

#include "model/symbol.hpp"

/**
 * @file
 * @brief Cross-reference edges between symbols and the types they mention.
 */

namespace clangquill::model {

/// @brief The kind of relationship a Reference records between two symbols/types.
enum class RefKind {
  BaseClass = 0,    ///< A record inherits from another record.
  ParamType,        ///< A function/method parameter's type.
  ReturnType,       ///< A function/method return type.
  FieldType,        ///< A data member's type.
  VariableType,     ///< A variable's type.
  UnderlyingType,   ///< A typedef / alias target.
  EnumIntegerType,  ///< An enum's fixed underlying integer type.
  Friend,           ///< A record to a befriended function/class.
};

/// @brief A directed edge in the cross-reference graph.
///
/// `to_usr` may be empty when the target is a builtin, a template parameter, or
/// a declaration not present in this translation unit; `to_spelling` is always
/// populated. There is deliberately no foreign key on `to_usr` so cross-TU
/// references are first class.
struct Reference {
  std::string from_usr;     ///< USR of the symbol the edge originates from.
  RefKind kind = RefKind::BaseClass;  ///< The relationship this edge records.
  std::string to_usr;       ///< Target USR; empty when unresolved.
  std::string to_spelling;  ///< The written type text; always populated.
  bool is_resolved = false; ///< True when `to_usr` names a known symbol.
  AccessKind access = AccessKind::None;  ///< Inheritance access; meaningful for base classes.
  int ordinal = 0;          ///< Param/base index for stable ordering.
};

}  // namespace clangquill::model
