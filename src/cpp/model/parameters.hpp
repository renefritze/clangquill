#pragma once

#include <string>

/**
 * @file
 * @brief Function and template parameter records.
 */

namespace clangquill::model {

/// @brief A function/method parameter, keyed by the owning function's USR.
struct FunctionParameter {
  std::string function_usr;   ///< USR of the function that owns this parameter.
  int index = 0;              ///< 0-based position in the parameter list.
  std::string name;           ///< Parameter name; may be empty.
  std::string type_repr;      ///< Spelling of the parameter's type.
  std::string default_value;  ///< Raw token text of the default, else "".
};

/// @brief A template parameter on a class/function template.
struct TemplateParameter {
  /// @brief The category of a template parameter.
  enum class Kind {
    Type = 0,  ///< A type parameter (`typename`/`class`).
    NonType,   ///< A non-type (value) parameter.
    Template,  ///< A template template parameter.
  };

  std::string owner_usr;     ///< USR of the template that owns this parameter.
  int index = 0;             ///< 0-based position in the template head.
  Kind kind = Kind::Type;    ///< Which category this parameter is.
  std::string name;          ///< Parameter name.
  std::string type_repr;     ///< Type spelling, for non-type params.
  std::string default_repr;  ///< Default argument text, else "".
};

}  // namespace clangquill::model
