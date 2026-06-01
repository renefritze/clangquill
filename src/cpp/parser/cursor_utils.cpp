#include "parser/cursor_utils.hpp"

#include <vector>

namespace clangquill::parser {

model::SymbolKind map_kind(CXCursorKind kind) {
  switch (kind) {
    case CXCursor_Namespace:
      return model::SymbolKind::Namespace;
    case CXCursor_ClassDecl:
      return model::SymbolKind::Class;
    case CXCursor_StructDecl:
      return model::SymbolKind::Struct;
    case CXCursor_UnionDecl:
      return model::SymbolKind::Union;
    case CXCursor_ClassTemplate:
    case CXCursor_ClassTemplatePartialSpecialization:
      return model::SymbolKind::ClassTemplate;
    case CXCursor_FunctionDecl:
      return model::SymbolKind::Function;
    case CXCursor_FunctionTemplate:
      return model::SymbolKind::FunctionTemplate;
    case CXCursor_CXXMethod:
      return model::SymbolKind::Method;
    case CXCursor_Constructor:
      return model::SymbolKind::Constructor;
    case CXCursor_Destructor:
      return model::SymbolKind::Destructor;
    case CXCursor_FieldDecl:
      return model::SymbolKind::Field;
    case CXCursor_VarDecl:
      return model::SymbolKind::Variable;
    case CXCursor_EnumDecl:
      return model::SymbolKind::Enum;
    case CXCursor_TypedefDecl:
      return model::SymbolKind::Typedef;
    case CXCursor_TypeAliasDecl:
    case CXCursor_TypeAliasTemplateDecl:
      return model::SymbolKind::TypeAlias;
    default:
      return model::SymbolKind::Unknown;
  }
}

std::string canonical_usr(CXCursor c) {
  return usr(clang_getCanonicalCursor(c));
}

std::string qualified_name(CXCursor c) {
  std::vector<std::string> parts;
  parts.push_back(spelling(c));
  CXCursor parent = clang_getCursorSemanticParent(c);
  while (!clang_Cursor_isNull(parent)) {
    CXCursorKind pk = clang_getCursorKind(parent);
    if (pk == CXCursor_TranslationUnit || pk == CXCursor_InvalidFile) break;
    std::string s = spelling(parent);
    if (!s.empty()) parts.push_back(s);
    parent = clang_getCursorSemanticParent(parent);
  }
  std::string out;
  for (auto it = parts.rbegin(); it != parts.rend(); ++it) {
    if (!out.empty()) out += "::";
    out += *it;
  }
  return out;
}

std::string pretty_signature(CXCursor c) {
  CXPrintingPolicy policy = clang_getCursorPrintingPolicy(c);
  clang_PrintingPolicy_setProperty(policy, CXPrintingPolicy_TerseOutput, 1);
  clang_PrintingPolicy_setProperty(policy, CXPrintingPolicy_PolishForDeclaration,
                                   1);
  std::string out = to_string(clang_getCursorPrettyPrinted(c, policy));
  clang_PrintingPolicy_dispose(policy);
  return out;
}

model::AccessKind map_access(CXCursor c) {
  switch (clang_getCXXAccessSpecifier(c)) {
    case CX_CXXPublic:
      return model::AccessKind::Public;
    case CX_CXXProtected:
      return model::AccessKind::Protected;
    case CX_CXXPrivate:
      return model::AccessKind::Private;
    default:
      return model::AccessKind::None;
  }
}

model::StorageKind map_storage(CXCursor c) {
  switch (clang_Cursor_getStorageClass(c)) {
    case CX_SC_Static:
      return model::StorageKind::Static;
    case CX_SC_Extern:
      return model::StorageKind::Extern;
    case CX_SC_Register:
      return model::StorageKind::Register;
    case CX_SC_Auto:
      return model::StorageKind::Auto;
    default:
      return model::StorageKind::None;
  }
}

bool in_file(CXCursor c, const std::string& main_file) {
  CXSourceLocation loc = clang_getCursorLocation(c);
  if (clang_Location_isInSystemHeader(loc)) return false;
  // Primary check: entities declared in the TU's main file. Robust against path
  // spelling differences (relative vs absolute).
  if (clang_Location_isFromMainFile(loc)) return true;
  // Fallback: explicit path match for entities pulled from a sibling header
  // that the caller still wants documented.
  if (main_file.empty()) return false;
  CXFile file;
  unsigned line = 0, column = 0, offset = 0;
  clang_getFileLocation(loc, &file, &line, &column, &offset);
  if (file == nullptr) return false;
  std::string path = to_string(clang_getFileName(file));
  return path == main_file;
}

}  // namespace clangquill::parser
