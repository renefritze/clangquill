#pragma once

#include <clang-c/Index.h>

#include <string>
#include <vector>

#include "model/comment.hpp"
#include "model/comment_model.hpp"

namespace clangquill::parser {

// Pluggable comment-parsing strategy.
//
// The default implementation is DoxygenCommentParser; this interface keeps the
// comment format swappable without touching the AST visitor or the store.
// Implementations receive both the libclang cursor (for the parsed CXComment
// tree) and the verbatim raw text (for command scanning that libclang does not
// surface).
class ICommentParser {
 public:
  virtual ~ICommentParser() = default;

  // Stable identifier persisted in `comments.format` (e.g. "doxygen").
  virtual std::string format() const = 0;

  virtual model::CommentModel parse(CXCursor cursor,
                                    const std::string& raw) const = 0;
};

// Serializes a CommentModel into the JSON stored in `comments.fields_json`.
std::string to_fields_json(const model::CommentModel& model);

// Flattens a CommentModel into normalized `comment_fields` rows for `usr`.
// Order is preserved via a running ordinal so reads round-trip the model.
std::vector<model::CommentField> to_comment_fields(
    const std::string& usr, const model::CommentModel& model);

}  // namespace clangquill::parser
