#pragma once

#include <string>

namespace clangquill::model {

// A function/method parameter, keyed by the owning function's USR.
struct FunctionParameter {
  std::string function_usr;
  int index = 0;
  std::string name;           // may be empty
  std::string type_repr;
  std::string default_value;  // raw token text if present, else ""
};

// A template parameter on a class/function template.
struct TemplateParameter {
  enum class Kind {
    Type = 0,
    NonType,
    Template,
  };

  std::string owner_usr;
  int index = 0;
  Kind kind = Kind::Type;
  std::string name;
  std::string type_repr;     // for non-type params
  std::string default_repr;  // default argument text, else ""
};

}  // namespace clangquill::model
