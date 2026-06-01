#include "parser/ast_visitor.hpp"

#include <unordered_map>
#include <unordered_set>

#include "hash/content_hash.hpp"
#include "parser/comment_parser.hpp"
#include "parser/cursor_utils.hpp"
#include "parser/doxygen_comment_parser.hpp"
#include "parser/references.hpp"

namespace clangquill::parser {
namespace {

struct VisitCtx {
  model::ParsedModule* mod;
  std::string parent_usr;
  std::string main_file;
  // De-dup of symbols/comments by USR, and parameters collected per function
  // so content_hash can include them.
  std::unordered_set<std::string>* seen_symbols;
  std::unordered_set<std::string>* documented;
  std::unordered_map<std::string, std::vector<model::FunctionParameter>>*
      params_by_func;
  const ICommentParser* comment_parser;
};

bool is_record(model::SymbolKind k) {
  return k == model::SymbolKind::Class || k == model::SymbolKind::Struct ||
         k == model::SymbolKind::Union || k == model::SymbolKind::ClassTemplate;
}

bool is_scope(model::SymbolKind k) {
  return k == model::SymbolKind::Namespace || is_record(k);
}

bool is_function_like(model::SymbolKind k) {
  return k == model::SymbolKind::Function || k == model::SymbolKind::Method ||
         k == model::SymbolKind::Constructor ||
         k == model::SymbolKind::Destructor ||
         k == model::SymbolKind::FunctionTemplate;
}

void fill_location(CXCursor c, model::Symbol& sym) {
  CXSourceLocation loc = clang_getCursorLocation(c);
  CXFile file;
  unsigned line = 0, column = 0, offset = 0;
  clang_getFileLocation(loc, &file, &line, &column, &offset);
  if (file != nullptr) {
    sym.location.file_path = to_string(clang_getFileName(file));
  }
  sym.location.line = line;
  sym.location.column = column;
}

// Extracts function parameters and type references for a function-like cursor.
void extract_function_details(CXCursor c, const std::string& usr,
                              VisitCtx& ctx) {
  CXType fn_type = clang_getCursorType(c);
  // Return type reference (skip for constructors/destructors which have none
  // meaningful).
  CXType result = clang_getResultType(fn_type);
  if (result.kind != CXType_Invalid && result.kind != CXType_Void) {
    ctx.mod->references.push_back(
        make_type_ref(usr, model::RefKind::ReturnType, result, -1));
  }

  int n = clang_Cursor_getNumArguments(c);
  for (int i = 0; i < n; ++i) {
    CXCursor arg = clang_Cursor_getArgument(c, i);
    model::FunctionParameter p;
    p.function_usr = usr;
    p.index = i;
    p.name = spelling(arg);
    p.type_repr = to_string(clang_getTypeSpelling(clang_getCursorType(arg)));
    (*ctx.params_by_func)[usr].push_back(p);
    ctx.mod->parameters.push_back(p);

    ctx.mod->references.push_back(make_type_ref(
        usr, model::RefKind::ParamType, clang_getCursorType(arg), i));
  }
}

void extract_enum(CXCursor enum_cursor, const std::string& enum_usr,
                  VisitCtx& ctx);

void extract_base_classes(CXCursor record, const std::string& usr,
                          VisitCtx& ctx);

CXChildVisitResult visit(CXCursor c, CXCursor parent, CXClientData data);

// Records a symbol row (and its details) for a cursor, then recurses into
// scopes. Returns the symbol's USR (empty if skipped).
std::string handle_symbol(CXCursor c, model::SymbolKind kind, VisitCtx& ctx) {
  std::string usr = canonical_usr(c);
  if (usr.empty()) return {};  // anonymous/local entity: no stable identity

  bool is_def = clang_isCursorDefinition(c);

  // Raw comment (verbatim). Track documented USRs so the symbol flag is set
  // even if the comment is seen on a different (re)declaration.
  std::string raw = to_string(clang_Cursor_getRawCommentText(c));
  if (!raw.empty() && ctx.documented->insert(usr).second) {
    model::CommentModel parsed = ctx.comment_parser->parse(c, raw);

    model::RawComment comment;
    comment.symbol_usr = usr;
    comment.text = raw;
    comment.format = ctx.comment_parser->format();
    comment.fields_json = to_fields_json(parsed);
    ctx.mod->comments.push_back(std::move(comment));

    auto fields = to_comment_fields(usr, parsed);
    ctx.mod->comment_fields.insert(ctx.mod->comment_fields.end(),
                                   fields.begin(), fields.end());
  }

  // De-dup symbols: keep the first row, but let a definition supersede a prior
  // forward declaration.
  if (!ctx.seen_symbols->insert(usr).second) {
    if (is_def) {
      for (auto& existing : ctx.mod->symbols) {
        if (existing.usr == usr && !existing.is_definition) {
          existing.is_definition = true;
          existing.signature = is_function_like(kind) ? pretty_signature(c)
                                                       : existing.signature;
          break;
        }
      }
    }
    return usr;
  }

  model::Symbol sym;
  sym.usr = usr;
  sym.parent_usr = ctx.parent_usr;
  sym.kind = kind;
  sym.spelling = spelling(c);
  sym.qualified_name = qualified_name(c);
  sym.display_name = display_name(c);
  sym.type_repr = to_string(clang_getTypeSpelling(clang_getCursorType(c)));
  sym.access = map_access(c);
  sym.storage = map_storage(c);
  sym.is_definition = is_def;
  sym.is_documented = ctx.documented->count(usr) != 0;
  if (is_function_like(kind)) sym.signature = pretty_signature(c);
  fill_location(c, sym);

  if (is_function_like(kind)) extract_function_details(c, usr, ctx);
  if (is_record(kind)) extract_base_classes(c, usr, ctx);
  if (kind == model::SymbolKind::Enum) extract_enum(c, usr, ctx);

  if (kind == model::SymbolKind::Typedef) {
    CXType u = clang_getTypedefDeclUnderlyingType(c);
    ctx.mod->references.push_back(
        make_type_ref(usr, model::RefKind::UnderlyingType, u, 0));
  } else if (kind == model::SymbolKind::Field ||
             kind == model::SymbolKind::Variable) {
    model::RefKind rk = kind == model::SymbolKind::Field
                            ? model::RefKind::FieldType
                            : model::RefKind::VariableType;
    ctx.mod->references.push_back(
        make_type_ref(usr, rk, clang_getCursorType(c), 0));
  }

  ctx.mod->symbols.push_back(std::move(sym));
  return usr;
}

void extract_enum(CXCursor enum_cursor, const std::string& enum_usr,
                  VisitCtx& ctx) {
  bool is_signed = true;
  CXType underlying = clang_getEnumDeclIntegerType(enum_cursor);
  switch (underlying.kind) {
    case CXType_UChar:
    case CXType_UShort:
    case CXType_UInt:
    case CXType_ULong:
    case CXType_ULongLong:
    case CXType_UInt128:
      is_signed = false;
      break;
    default:
      break;
  }

  struct EnumCtx {
    model::ParsedModule* mod;
    std::string enum_usr;
    bool is_signed;
    int index;
  } ectx{ctx.mod, enum_usr, is_signed, 0};

  clang_visitChildren(
      enum_cursor,
      [](CXCursor child, CXCursor, CXClientData data) {
        auto& e = *static_cast<EnumCtx*>(data);
        if (clang_getCursorKind(child) != CXCursor_EnumConstantDecl) {
          return CXChildVisit_Continue;
        }
        model::Enumerator en;
        en.usr = canonical_usr(child);
        en.enum_usr = e.enum_usr;
        en.name = spelling(child);
        en.index = e.index++;
        en.value_is_signed = e.is_signed;
        if (e.is_signed) {
          en.value = clang_getEnumConstantDeclValue(child);
        } else {
          en.value = static_cast<std::int64_t>(
              clang_getEnumConstantDeclUnsignedValue(child));
        }
        e.mod->enumerators.push_back(std::move(en));
        return CXChildVisit_Continue;
      },
      &ectx);
}

void extract_base_classes(CXCursor record, const std::string& usr,
                          VisitCtx& ctx) {
  struct BaseCtx {
    model::ParsedModule* mod;
    std::string from_usr;
    int index;
  } bctx{ctx.mod, usr, 0};

  clang_visitChildren(
      record,
      [](CXCursor child, CXCursor, CXClientData data) {
        auto& b = *static_cast<BaseCtx*>(data);
        if (clang_getCursorKind(child) != CXCursor_CXXBaseSpecifier) {
          return CXChildVisit_Continue;
        }
        model::Reference ref = make_type_ref(b.from_usr,
                                             model::RefKind::BaseClass,
                                             clang_getCursorType(child),
                                             b.index++);
        ref.access = map_access(child);
        b.mod->references.push_back(std::move(ref));
        return CXChildVisit_Continue;
      },
      &bctx);
}

CXChildVisitResult visit(CXCursor c, CXCursor /*parent*/, CXClientData data) {
  auto& ctx = *static_cast<VisitCtx*>(data);

  if (!in_file(c, ctx.main_file)) return CXChildVisit_Continue;

  model::SymbolKind kind = map_kind(clang_getCursorKind(c));
  if (kind == model::SymbolKind::Unknown) return CXChildVisit_Continue;

  std::string usr = handle_symbol(c, kind, ctx);

  // Recurse into scopes with this symbol as the parent. Drive recursion
  // explicitly so children always get the correct parent_usr.
  if (is_scope(kind) && !usr.empty()) {
    VisitCtx child = ctx;
    child.parent_usr = usr;
    clang_visitChildren(c, visit, &child);
  }
  return CXChildVisit_Continue;
}

}  // namespace

void visit_translation_unit(CXCursor tu_cursor, const std::string& main_file,
                            model::ParsedModule& out) {
  std::unordered_set<std::string> seen_symbols;
  std::unordered_set<std::string> documented;
  std::unordered_map<std::string, std::vector<model::FunctionParameter>>
      params_by_func;
  DoxygenCommentParser comment_parser;

  VisitCtx ctx;
  ctx.mod = &out;
  ctx.parent_usr = "";
  ctx.main_file = main_file;
  ctx.seen_symbols = &seen_symbols;
  ctx.documented = &documented;
  ctx.params_by_func = &params_by_func;
  ctx.comment_parser = &comment_parser;

  clang_visitChildren(tu_cursor, visit, &ctx);

  // Finalize: set is_documented and content_hash now that all comments and
  // parameters have been collected. Index comments by USR first so the per
  // symbol lookup is O(1) rather than scanning all comments.
  static const std::vector<model::FunctionParameter> kNoParams;
  std::unordered_map<std::string, const std::string*> comment_by_usr;
  comment_by_usr.reserve(out.comments.size());
  for (const auto& cm : out.comments) comment_by_usr[cm.symbol_usr] = &cm.text;

  for (auto& sym : out.symbols) {
    if (documented.count(sym.usr)) sym.is_documented = true;

    std::string raw;
    if (auto cit = comment_by_usr.find(sym.usr); cit != comment_by_usr.end()) {
      raw = *cit->second;
    }
    auto it = params_by_func.find(sym.usr);
    const auto& params = it != params_by_func.end() ? it->second : kNoParams;
    sym.content_hash = hash::content_hash(sym, params, raw);
  }
}

}  // namespace clangquill::parser
