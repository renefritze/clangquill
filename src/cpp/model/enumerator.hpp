#pragma once

#include <cstdint>
#include <string>

namespace clangquill::model {

// A single enumerator within an enum. Enumerators have their own USR.
struct Enumerator {
  std::string usr;
  std::string enum_usr;
  std::string name;
  std::int64_t value = 0;
  bool value_is_signed = true;
  int index = 0;
};

}  // namespace clangquill::model
