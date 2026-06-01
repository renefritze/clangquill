#pragma once

#include <clang-c/Index.h>

#include <string>

#include "model/module.hpp"

namespace clangquill::parser {

// Walks the translation unit rooted at `tu_cursor`, appending symbols,
// references, parameters, enumerators, comments and file rows into `out`.
// `main_file` is the path passed to the parser, used to filter out included
// declarations.
void visit_translation_unit(CXCursor tu_cursor, const std::string& main_file,
                            model::ParsedModule& out);

}  // namespace clangquill::parser
