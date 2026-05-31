#pragma once

#include <clang-c/Index.h>

#include <string>

#include "model/reference.hpp"

namespace clangquill::parser {

// Resolves a CXType to a Reference, peeling pointers/refs/const/array to find
// the named declaration. `to_usr` is empty (is_resolved=false) for builtins,
// template parameters, and types whose declaration is absent.
model::Reference make_type_ref(const std::string& from_usr, model::RefKind kind,
                               CXType type, int ordinal);

}  // namespace clangquill::parser
