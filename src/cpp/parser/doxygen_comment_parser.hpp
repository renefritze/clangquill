#pragma once

#include <clang-c/Index.h>

#include <string>

#include "model/comment_model.hpp"
#include "parser/comment_parser.hpp"

namespace clangquill::parser {

// Default comment parser.
//
// Walks libclang's parsed CXComment tree for structure (brief, paragraphs,
// @param/@tparam, block commands) and supplements it with raw-text command
// scanning for arguments libclang does not split out (@retval / @throws value
// names). The two passes are merged into a single format-agnostic CommentModel.
class DoxygenCommentParser : public ICommentParser {
 public:
  std::string format() const override { return "doxygen"; }
  model::CommentModel parse(CXCursor cursor,
                            const std::string& raw) const override;

  // Parses a comment from its raw text alone (no cursor / parsed CXComment).
  // Used to recover free-floating `\defgroup` blocks that attach to no cursor.
  static model::CommentModel parse_raw_text(const std::string& raw);
};

}  // namespace clangquill::parser
