#pragma once

#include <string>

namespace clangquill::model {

// The verbatim documentation comment attached to a symbol. The structured,
// format-specific parse is added by a later milestone; M2 stores raw text so
// the comment format stays swappable.
struct RawComment {
  std::string symbol_usr;
  std::string text;             // verbatim, comment markers included
  std::string format = "doxygen-raw";
  std::string fields_json;      // serialized structured model; "{}" / empty in M2
};

// A normalized projection of a single structured comment field (e.g. a
// @param entry). Empty in M2; the table exists so the schema round-trips.
struct CommentField {
  std::string symbol_usr;
  std::string name;   // brief / param / return / tparam / ...
  std::string arg;    // e.g. the parameter name
  std::string value;  // the field text
  int ordinal = 0;
};

}  // namespace clangquill::model
