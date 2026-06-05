#pragma once

#include <clang-c/Index.h>

#include <string>

#include "model/module.hpp"

/**
 * @file
 * @brief Entry point that walks a translation unit's AST into the IR model.
 */

namespace clangquill::parser {

/// @brief Walks the translation unit rooted at @p tu_cursor into @p out.
///
/// Appends symbols, references, parameters, enumerators, comments and file rows.
/// @param tu_cursor Cursor for the translation unit to traverse.
/// @param main_file Path passed to the parser, used to filter out included declarations.
/// @param out Module that extracted rows are appended to.
void visit_translation_unit(CXCursor tu_cursor, const std::string& main_file,
                            model::ParsedModule& out);

}  // namespace clangquill::parser
