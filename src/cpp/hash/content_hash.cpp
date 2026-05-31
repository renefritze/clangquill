#include "hash/content_hash.hpp"

#include "hash/sha256.hpp"

namespace clangquill::hash {

std::string content_hash(const model::Symbol& sym,
                         const std::vector<model::FunctionParameter>& params,
                         const std::string& raw_comment) {
  Sha256 h;
  const char kSep = '\x1f';  // unit separator
  auto field = [&](std::string_view v) {
    h.update(v);
    h.update(&kSep, 1);
  };

  field(sym.usr);
  field(std::to_string(static_cast<int>(sym.kind)));
  field(sym.qualified_name);
  field(sym.signature);
  field(sym.type_repr);
  field(std::to_string(static_cast<int>(sym.access)));
  field(std::to_string(static_cast<int>(sym.storage)));
  field(sym.is_definition ? "1" : "0");
  for (const auto& p : params) {
    field(p.type_repr);
    field(p.name);
    field(p.default_value);
  }
  field(raw_comment);
  return h.hexdigest();
}

}  // namespace clangquill::hash
