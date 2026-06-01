#include <catch2/catch_test_macros.hpp>

#include <cstdio>
#include <cstdlib>
#include <string>
#include <unistd.h>

#include "store/sqlite_store.hpp"

using namespace clangquill;

namespace {

std::string temp_db_path() {
  char tmpl[] = "/tmp/clangquill_test_XXXXXX";
  int fd = mkstemp(tmpl);
  if (fd != -1) close(fd);
  return std::string(tmpl);
}

model::ParsedModule make_module() {
  model::ParsedModule m;

  model::SourceFile f;
  f.path = "/tmp/example.hpp";
  f.sha256 = std::string(64, 'a');
  f.size_bytes = 123;
  m.files.push_back(f);

  model::Symbol s;
  s.usr = "c:@S@Widget";
  s.kind = model::SymbolKind::Class;
  s.spelling = "Widget";
  s.qualified_name = "Widget";
  s.display_name = "Widget";
  s.is_definition = true;
  s.is_documented = true;
  s.content_hash = "deadbeef";
  s.location.file_path = "/tmp/example.hpp";
  s.location.line = 10;
  s.location.column = 7;
  m.symbols.push_back(s);

  // Owning symbols referenced by the parameter/enumerator rows below, so the
  // foreign keys are satisfied (mirrors what the parser always produces).
  model::Symbol method;
  method.usr = "c:@S@Widget@F@resize";
  method.kind = model::SymbolKind::Method;
  method.spelling = "resize";
  method.qualified_name = "Widget::resize";
  method.display_name = "resize(int)";
  m.symbols.push_back(method);

  model::Symbol enm;
  enm.usr = "c:@E@Color";
  enm.kind = model::SymbolKind::Enum;
  enm.spelling = "Color";
  enm.qualified_name = "Color";
  enm.display_name = "Color";
  m.symbols.push_back(enm);

  model::FunctionParameter p;
  p.function_usr = "c:@S@Widget@F@resize";
  p.index = 0;
  p.name = "size";
  p.type_repr = "int";
  m.parameters.push_back(p);

  model::Reference r;
  r.from_usr = "c:@S@Widget";
  r.kind = model::RefKind::BaseClass;
  r.to_usr = "c:@S@Base";
  r.to_spelling = "Base";
  r.is_resolved = true;
  r.access = model::AccessKind::Public;
  m.references.push_back(r);

  model::Enumerator e;
  e.usr = "c:@E@Color@Red";
  e.enum_usr = "c:@E@Color";
  e.name = "Red";
  e.value = 0;
  m.enumerators.push_back(e);

  model::RawComment c;
  c.symbol_usr = "c:@S@Widget";
  c.text = "/// A widget.";
  m.comments.push_back(c);

  return m;
}

}  // namespace

TEST_CASE("SqliteStore write/read round-trips the IR", "[store]") {
  std::string path = temp_db_path();
  model::ParsedModule original = make_module();

  {
    store::SqliteStore writer(path);
    writer.write(original, store::Meta::current());
  }

  store::SqliteStore reader(path);
  model::ParsedModule got = reader.read();

  REQUIRE(got.files.size() == 1);
  CHECK(got.files[0].path == "/tmp/example.hpp");
  CHECK(got.files[0].sha256 == std::string(64, 'a'));

  REQUIRE(got.symbols.size() == 3);
  const model::Symbol* widget = nullptr;
  for (const auto& s : got.symbols) {
    if (s.usr == "c:@S@Widget") widget = &s;
  }
  REQUIRE(widget != nullptr);
  CHECK(widget->kind == model::SymbolKind::Class);
  CHECK(widget->is_definition);
  CHECK(widget->is_documented);
  CHECK(widget->location.file_path == "/tmp/example.hpp");
  CHECK(widget->location.line == 10);

  REQUIRE(got.parameters.size() == 1);
  CHECK(got.parameters[0].name == "size");

  REQUIRE(got.references.size() == 1);
  CHECK(got.references[0].to_spelling == "Base");
  CHECK(got.references[0].is_resolved);
  CHECK(got.references[0].access == model::AccessKind::Public);

  REQUIRE(got.enumerators.size() == 1);
  CHECK(got.enumerators[0].name == "Red");

  REQUIRE(got.comments.size() == 1);
  CHECK(got.comments[0].text == "/// A widget.");

  std::remove(path.c_str());
}
