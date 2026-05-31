#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <string>

#include "model/module.hpp"

#if defined(CLANGQUILL_HAVE_LIBCLANG)
#include "parser/parser.hpp"
#endif

#ifndef CLANGQUILL_FIXTURE_DIR
#define CLANGQUILL_FIXTURE_DIR "tests/cpp/fixtures"
#endif

using namespace clangquill;

#if defined(CLANGQUILL_HAVE_LIBCLANG)

namespace {

model::ParsedModule parse_fixture(const std::string& name) {
  parser::ParseOptions opts;
  parser::Parser p(opts);
  model::ParsedModule mod;
  p.parse_file(std::string(CLANGQUILL_FIXTURE_DIR) + "/" + name, mod);
  return mod;
}

const model::Symbol* find(const model::ParsedModule& m, const std::string& qn) {
  for (const auto& s : m.symbols) {
    if (s.qualified_name == qn) return &s;
  }
  return nullptr;
}

}  // namespace

TEST_CASE("parser extracts symbols and hierarchy", "[parser]") {
  auto m = parse_fixture("shapes.hpp");

  const auto* ns = find(m, "geo");
  REQUIRE(ns != nullptr);
  CHECK(ns->kind == model::SymbolKind::Namespace);

  const auto* circle = find(m, "geo::Circle");
  REQUIRE(circle != nullptr);
  CHECK(circle->kind == model::SymbolKind::Class);
  CHECK(circle->is_definition);
  CHECK(circle->parent_usr == ns->usr);

  const auto* area = find(m, "geo::Shape::area");
  REQUIRE(area != nullptr);
  const auto* shape = find(m, "geo::Shape");
  REQUIRE(shape != nullptr);
  CHECK(area->parent_usr == shape->usr);
}

TEST_CASE("parser resolves base-class references", "[parser]") {
  auto m = parse_fixture("shapes.hpp");
  const auto* circle = find(m, "geo::Circle");
  REQUIRE(circle != nullptr);

  bool found_base = false;
  for (const auto& r : m.references) {
    if (r.from_usr == circle->usr && r.kind == model::RefKind::BaseClass) {
      found_base = true;
      CHECK(r.to_spelling.find("Shape") != std::string::npos);
      CHECK(r.is_resolved);
    }
  }
  CHECK(found_base);
}

TEST_CASE("parser stores raw comments verbatim", "[parser]") {
  auto m = parse_fixture("shapes.hpp");
  const auto* circle = find(m, "geo::Circle");
  REQUIRE(circle != nullptr);
  CHECK(circle->is_documented);

  bool found = false;
  for (const auto& c : m.comments) {
    if (c.symbol_usr == circle->usr) {
      found = true;
      CHECK(c.text.find("@param r") != std::string::npos);
      CHECK(c.text.find("/**") != std::string::npos);
    }
  }
  CHECK(found);
}

TEST_CASE("parser keeps undocumented symbols", "[parser]") {
  auto m = parse_fixture("undocumented.hpp");

  const auto* undoc = find(m, "undocumented_function");
  REQUIRE(undoc != nullptr);
  CHECK_FALSE(undoc->is_documented);

  const auto* doc = find(m, "documented_function");
  REQUIRE(doc != nullptr);
  CHECK(doc->is_documented);

  // The undocumented symbol must not have a comment row.
  for (const auto& c : m.comments) {
    CHECK(c.symbol_usr != undoc->usr);
  }
}

TEST_CASE("parser reads enumerators with values", "[parser]") {
  auto m = parse_fixture("enums.hpp");
  REQUIRE(m.enumerators.size() >= 7);

  auto value_of = [&](const std::string& name) -> long long {
    for (const auto& e : m.enumerators) {
      if (e.name == name) return e.value;
    }
    return -999;
  };
  CHECK(value_of("Red") == 0);
  CHECK(value_of("Green") == 5);
  CHECK(value_of("Blue") == 6);
}

TEST_CASE("parser populates content and file hashes", "[parser]") {
  auto m = parse_fixture("shapes.hpp");
  REQUIRE(m.files.size() == 1);
  CHECK(m.files[0].sha256.size() == 64);

  for (const auto& s : m.symbols) {
    CHECK_FALSE(s.content_hash.empty());
  }
}

TEST_CASE("content_hash is deterministic across parses", "[parser]") {
  auto a = parse_fixture("shapes.hpp");
  auto b = parse_fixture("shapes.hpp");

  auto hash_of = [](const model::ParsedModule& m, const std::string& qn) {
    for (const auto& s : m.symbols) {
      if (s.qualified_name == qn) return s.content_hash;
    }
    return std::string{};
  };
  CHECK(hash_of(a, "geo::Circle") == hash_of(b, "geo::Circle"));
  CHECK_FALSE(hash_of(a, "geo::Circle").empty());
}

#else  // !CLANGQUILL_HAVE_LIBCLANG

TEST_CASE("parser tests skipped without libclang", "[parser][!mayfail]") {
  SUCCEED("built without libclang");
}

#endif
