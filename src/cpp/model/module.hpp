#pragma once

#include <string>
#include <vector>

#include "model/comment.hpp"
#include "model/enumerator.hpp"
#include "model/file.hpp"
#include "model/group.hpp"
#include "model/parameters.hpp"
#include "model/reference.hpp"
#include "model/symbol.hpp"

namespace clangquill::model {

// The complete extracted IR for one or more translation units. Owns all rows;
// the store writes it into SQLite and can read it back for round-trip tests.
struct ParsedModule {
  std::vector<SourceFile> files;
  std::vector<Symbol> symbols;
  std::vector<FunctionParameter> parameters;
  std::vector<TemplateParameter> template_parameters;
  std::vector<Enumerator> enumerators;
  std::vector<Reference> references;
  std::vector<RawComment> comments;
  std::vector<CommentField> comment_fields;
  std::vector<Group> groups;
  std::vector<GroupMember> group_members;
  std::vector<std::string> diagnostics;  // non-fatal parse warnings/errors
};

}  // namespace clangquill::model
