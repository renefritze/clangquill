#pragma once

#include <clang-c/Index.h>

#include <string>
#include <vector>

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

/// @brief Walks the translation unit, extracting from a *set* of files.
///
/// Used for umbrella translation units that `#include` several inputs: only
/// declarations physically located in one of @p main_files are extracted, and
/// each of those files is scanned for free-floating comment blocks (group
/// definitions, macro docs) exactly as a per-file parse would scan its main
/// file.
///
/// @param tu_cursor Cursor for the translation unit to traverse.
/// @param main_files Accepted file spellings; entries that name the same file
///        under different spellings are deduplicated.
/// @param trust_main_file Whether a cursor in the TU's main file is accepted
///        regardless of path spelling (`true` only when the main file is a real
///        input rather than a synthetic umbrella).
/// @param out Module that extracted rows are appended to.
void visit_translation_unit(CXCursor tu_cursor,
                            const std::vector<std::string>& main_files,
                            bool trust_main_file, model::ParsedModule& out);

}  // namespace clangquill::parser
