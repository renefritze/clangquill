#include "parser/references.hpp"

#include "parser/cursor_utils.hpp"

namespace clangquill::parser {
namespace {

// Strips pointer/reference/const/array layers to reach a named type.
CXType peel_to_named(CXType t) {
  for (;;) {
    switch (t.kind) {
      case CXType_Pointer:
      case CXType_LValueReference:
      case CXType_RValueReference:
        t = clang_getPointeeType(t);
        continue;
      case CXType_ConstantArray:
      case CXType_IncompleteArray:
      case CXType_VariableArray:
      case CXType_DependentSizedArray:
        t = clang_getArrayElementType(t);
        continue;
      case CXType_Elaborated:
        t = clang_Type_getNamedType(t);
        continue;
      default:
        return t;
    }
  }
}

}  // namespace

model::Reference make_type_ref(const std::string& from_usr, model::RefKind kind,
                               CXType type, int ordinal) {
  model::Reference ref;
  ref.from_usr = from_usr;
  ref.kind = kind;
  ref.ordinal = ordinal;
  ref.to_spelling = to_string(clang_getTypeSpelling(type));

  CXType named = peel_to_named(type);
  CXCursor decl = clang_getTypeDeclaration(named);
  if (!clang_Cursor_isNull(decl) &&
      clang_getCursorKind(decl) != CXCursor_NoDeclFound) {
    ref.to_usr = canonical_usr(decl);
    ref.is_resolved = !ref.to_usr.empty();
  }
  return ref;
}

}  // namespace clangquill::parser
