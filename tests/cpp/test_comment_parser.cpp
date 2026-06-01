#include <catch2/catch_test_macros.hpp>

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

// Collects the comment_fields of one symbol into a list of (name, arg, value).
struct Field {
  std::string name, arg, value;
};
std::vector<Field> fields_of(const model::ParsedModule& m,
                             const std::string& usr) {
  std::vector<Field> out;
  for (const auto& f : m.comment_fields) {
    if (f.symbol_usr == usr) out.push_back({f.name, f.arg, f.value});
  }
  return out;
}

const Field* field(const std::vector<Field>& fs, const std::string& name,
                   const std::string& arg = "") {
  for (const auto& f : fs) {
    if (f.name == name && (arg.empty() || f.arg == arg)) return &f;
  }
  return nullptr;
}

}  // namespace

TEST_CASE("doxygen parser covers the common commands", "[comments]") {
  auto m = parse_fixture("doxygen.hpp");
  const auto* divide = find(m, "doc::divide");
  REQUIRE(divide != nullptr);
  auto fs = fields_of(m, divide->usr);
  REQUIRE_FALSE(fs.empty());

  const Field* brief = field(fs, "brief");
  REQUIRE(brief != nullptr);
  CHECK(brief->value.find("quotient") != std::string::npos);

  const Field* detail = field(fs, "detail");
  REQUIRE(detail != nullptr);
  CHECK(detail->value.find("integer division") != std::string::npos);

  const Field* num = field(fs, "param", "numerator");
  REQUIRE(num != nullptr);
  CHECK(num->value.find("divide") != std::string::npos);

  const Field* den = field(fs, "param", "denominator");
  REQUIRE(den != nullptr);

  const Field* ret = field(fs, "returns");
  REQUIRE(ret != nullptr);
  CHECK(ret->value.find("quotient") != std::string::npos);

  const Field* retval = field(fs, "retval", "0");
  REQUIRE(retval != nullptr);
  CHECK(retval->value.find("numerator is zero") != std::string::npos);

  const Field* thr = field(fs, "throws", "std::domain_error");
  REQUIRE(thr != nullptr);

  CHECK(field(fs, "note") != nullptr);
  CHECK(field(fs, "warning") != nullptr);

  const Field* since = field(fs, "since");
  REQUIRE(since != nullptr);
  CHECK(since->value == "1.2");

  CHECK(field(fs, "see") != nullptr);

  // Unknown command lands under its own name (the "custom" bucket).
  const Field* author = field(fs, "author");
  REQUIRE(author != nullptr);
  CHECK(author->value == "Ada");
}

TEST_CASE("doxygen parser handles /// brief and tparam", "[comments]") {
  auto m = parse_fixture("doxygen.hpp");
  const auto* mul = find(m, "doc::multiply");
  REQUIRE(mul != nullptr);
  auto fs = fields_of(m, mul->usr);

  const Field* brief = field(fs, "brief");
  REQUIRE(brief != nullptr);
  CHECK(brief->value == "Multiplies two values.");

  const Field* tp = field(fs, "tparam", "T");
  REQUIRE(tp != nullptr);
  CHECK(tp->value.find("arithmetic") != std::string::npos);
}

TEST_CASE("doxygen parser captures deprecated", "[comments]") {
  auto m = parse_fixture("doxygen.hpp");
  const auto* od = find(m, "doc::old_divide");
  REQUIRE(od != nullptr);
  auto fs = fields_of(m, od->usr);
  const Field* dep = field(fs, "deprecated");
  REQUIRE(dep != nullptr);
  CHECK(dep->value.find("divide") != std::string::npos);
}

TEST_CASE("parsed comments store a format and JSON projection", "[comments]") {
  auto m = parse_fixture("doxygen.hpp");
  const auto* divide = find(m, "doc::divide");
  REQUIRE(divide != nullptr);

  bool found = false;
  for (const auto& c : m.comments) {
    if (c.symbol_usr == divide->usr) {
      found = true;
      CHECK(c.format == "doxygen");
      CHECK(c.fields_json.find("\"brief\"") != std::string::npos);
      CHECK(c.fields_json.find("quotient") != std::string::npos);
    }
  }
  CHECK(found);
}

#else  // !CLANGQUILL_HAVE_LIBCLANG

TEST_CASE("comment parser tests skipped without libclang", "[comments][!mayfail]") {
  SUCCEED("built without libclang");
}

#endif
