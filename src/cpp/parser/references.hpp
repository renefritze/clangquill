#pragma once

#include <clang-c/Index.h>

#include <string>

#include "model/reference.hpp"

/**
 * @file
 * @brief Helper that turns a libclang type into a cross-reference edge.
 */

namespace clangquill::parser {

/// @brief Resolves a `CXType` to a Reference.
///
/// Peels pointers/refs/const/array to find the named declaration. `to_usr` is
/// empty (`is_resolved=false`) for builtins, template parameters, and types
/// whose declaration is absent.
/// @param from_usr USR of the symbol the edge originates from.
/// @param kind The kind of relationship the edge records.
/// @param type The type to resolve.
/// @param ordinal Position used for stable ordering of sibling edges.
/// @return The constructed reference edge.
model::Reference make_type_ref(const std::string& from_usr, model::RefKind kind,
                               CXType type, int ordinal);

}  // namespace clangquill::parser
