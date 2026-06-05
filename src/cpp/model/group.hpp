#pragma once

#include <string>

namespace clangquill::model {

// A Doxygen documentation group (`\defgroup`/`\addtogroup`). `id` is the group
// token (stable identity); `parent_group_id` is set when the group's own block
// carries an `\ingroup` to nest it under another group.
struct Group {
  std::string id;
  std::string title;
  std::string brief;
  std::string detail;
  std::string parent_group_id;  // empty for a top-level group
};

// Membership of a symbol in a group, recorded from an `\ingroup` (or inline
// `\defgroup`) on the symbol's own comment.
struct GroupMember {
  std::string group_id;
  std::string member_usr;
  int ordinal = 0;
};

}  // namespace clangquill::model
