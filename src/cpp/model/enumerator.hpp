#pragma once

#include <cstdint>
#include <string>

/**
 * @file
 * @brief Record for a single enumerator within an enum.
 */

namespace clangquill::model {

/// @brief A single enumerator within an enum.
///
/// Enumerators have their own USR so they can be referenced individually.
struct Enumerator {
  std::string usr;          ///< Stable identity of this enumerator.
  std::string enum_usr;     ///< USR of the enclosing enum.
  std::string name;         ///< The enumerator's name.
  std::int64_t value = 0;   ///< Its integer value.
  bool value_is_signed = true;  ///< Whether @ref value is interpreted as signed.
  int index = 0;            ///< 0-based declaration order within the enum.
};

}  // namespace clangquill::model
