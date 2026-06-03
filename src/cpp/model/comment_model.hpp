#pragma once

#include <map>
#include <string>
#include <vector>

namespace clangquill::model {

// A documented parameter or template parameter (@param / @tparam).
struct CommentParam {
  std::string name;
  std::string description;
};

// A documented named return value (@retval <value> <description>).
struct CommentRetval {
  std::string value;
  std::string description;
};

// A documented thrown exception (@throws / @throw / @exception).
struct CommentThrow {
  std::string exception;
  std::string description;
};

// Format-agnostic structured documentation comment.
//
// Produced by an ICommentParser (the default being the Doxygen parser) from a
// symbol's raw comment. Downstream code consumes this model without knowing the
// source comment format, so the format stays swappable. Commands the model does
// not name explicitly land in `custom`, keyed by the command word.
struct CommentModel {
  std::string brief;
  std::vector<std::string> detail;  // free-form paragraphs / blocks
  std::vector<CommentParam> params;
  std::vector<CommentParam> tparams;
  std::string returns;
  std::vector<CommentRetval> retvals;
  std::vector<CommentThrow> throws;
  std::vector<std::string> see;
  std::vector<std::string> since;
  std::vector<std::string> deprecated;
  std::vector<std::string> note;
  std::vector<std::string> warning;
  std::vector<std::string> pre;
  std::vector<std::string> post;
  std::map<std::string, std::vector<std::string>> custom;

  bool empty() const {
    return brief.empty() && detail.empty() && params.empty() &&
           tparams.empty() && returns.empty() && retvals.empty() &&
           throws.empty() && see.empty() && since.empty() &&
           deprecated.empty() && note.empty() && warning.empty() &&
           pre.empty() && post.empty() && custom.empty();
  }
};

}  // namespace clangquill::model
