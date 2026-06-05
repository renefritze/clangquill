#pragma once

#include <string>

/**
 * @file
 * @brief Raw and lightly-normalized documentation-comment records.
 */

namespace clangquill::model {

/// @brief The verbatim documentation comment attached to a symbol.
///
/// The structured, format-specific parse is added by a later milestone; M2
/// stores raw text so the comment format stays swappable.
struct RawComment {
  std::string symbol_usr;        ///< USR of the documented symbol.
  std::string text;              ///< Verbatim comment, markers included.
  std::string format = "doxygen-raw";  ///< Identifier of the comment dialect.
  std::string fields_json;       ///< Serialized structured model; `"{}"`/empty in M2.
};

/// @brief A normalized projection of a single structured comment field.
///
/// For example a `\@param` entry. Empty in M2; the table exists so the schema
/// round-trips.
struct CommentField {
  std::string symbol_usr;  ///< USR of the documented symbol.
  std::string name;        ///< Field name: brief / param / return / tparam / ...
  std::string arg;         ///< Argument, e.g. the parameter name.
  std::string value;       ///< The field text.
  int ordinal = 0;         ///< Position for stable ordering.
};

}  // namespace clangquill::model
