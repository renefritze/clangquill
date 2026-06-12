#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

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

namespace {

std::vector<std::string> all_inputs() {
  const std::string dir = CLANGQUILL_FIXTURE_DIR;
  return {dir + "/shapes.hpp", dir + "/enums.hpp", dir + "/undocumented.hpp",
          dir + "/doxygen.hpp", dir + "/m7.hpp"};
}

// USR set is the stable identity of a parse, independent of row order.
std::set<std::string> symbol_usrs(const model::ParsedModule& m) {
  std::set<std::string> usrs;
  for (const auto& s : m.symbols) usrs.insert(s.usr);
  return usrs;
}

}  // namespace

TEST_CASE("parse_files merges every input into one module", "[parser]") {
  parser::ParseOptions opts;
  opts.jobs = 4;
  auto merged = parser::parse_files(all_inputs(), opts);

  // Symbols from each separate input are present in the combined module.
  CHECK(find(merged, "geo::Circle") != nullptr);  // shapes.hpp
  CHECK(merged.enumerators.size() >= 7);           // enums.hpp

  // Each fixture's main file is recorded exactly once, and paths are unique.
  std::set<std::string> paths;
  for (const auto& f : merged.files) {
    CHECK(paths.insert(f.path).second);  // no duplicate file rows after merge
  }
  CHECK(paths.size() >= all_inputs().size());
}

TEST_CASE("parse_files is deterministic regardless of job count", "[parser]") {
  auto inputs = all_inputs();

  parser::ParseOptions serial;
  serial.jobs = 1;
  parser::ParseOptions parallel;
  parallel.jobs = 4;

  auto a = parser::parse_files(inputs, serial);
  auto b = parser::parse_files(inputs, parallel);

  CHECK(symbol_usrs(a) == symbol_usrs(b));
  CHECK(a.symbols.size() == b.symbols.size());
  CHECK(a.references.size() == b.references.size());
  CHECK(a.files.size() == b.files.size());

  // Merge order follows input order, not thread completion order: the file
  // rows land in a stable sequence whether parsed serially or concurrently.
  std::vector<std::string> pa;
  std::vector<std::string> pb;
  for (const auto& f : a.files) pa.push_back(f.path);
  for (const auto& f : b.files) pb.push_back(f.path);
  CHECK(pa == pb);
}

TEST_CASE("umbrella batching extracts the same symbols as per-file parsing",
          "[parser]") {
  auto inputs = all_inputs();

  parser::ParseOptions isolated;
  isolated.tu_batch = 1;
  parser::ParseOptions batched;
  batched.tu_batch = static_cast<int>(inputs.size());

  auto a = parser::parse_files(inputs, isolated);
  auto b = parser::parse_files(inputs, batched);

  CHECK(symbol_usrs(a) == symbol_usrs(b));

  std::set<std::string> fa;
  std::set<std::string> fb;
  for (const auto& f : a.files) fa.insert(f.path);
  for (const auto& f : b.files) fb.insert(f.path);
  CHECK(fa == fb);
}

TEST_CASE("umbrella batching attributes dependencies per member exactly",
          "[parser]") {
  // m7.hpp is self-contained while shapes.hpp has no includes: inside one
  // umbrella TU each member's dependency closure must stay its own (built from
  // the preprocessing record, so even guard-skipped includes attribute).
  const std::string dir = CLANGQUILL_FIXTURE_DIR;
  std::vector<std::string> inputs{dir + "/shapes.hpp", dir + "/enums.hpp"};

  parser::ParseOptions batched;
  batched.tu_batch = 2;
  std::vector<std::vector<std::string>> tu_files;
  std::vector<bool> tu_ok;
  parser::parse_files(inputs, batched, &tu_files, &tu_ok);

  REQUIRE(tu_files.size() == 2);
  REQUIRE(tu_ok == std::vector<bool>{true, true});
  // Each member's closure starts with (a spelling of) itself and never lists
  // the sibling input.
  for (std::size_t i = 0; i < inputs.size(); ++i) {
    REQUIRE_FALSE(tu_files[i].empty());
    CHECK(tu_files[i].front().find(i == 0 ? "shapes.hpp" : "enums.hpp") !=
          std::string::npos);
    for (const auto& dep : tu_files[i]) {
      CHECK(dep.find(i == 0 ? "enums.hpp" : "shapes.hpp") == std::string::npos);
    }
  }
}

namespace {

// A throwaway directory of generated headers, so the PCH tests control how
// many inputs exist (parse_files only builds a PCH past kMinBatchesForPch
// batches) and which headers they share.
struct TempTree {
  std::filesystem::path dir;
  explicit TempTree(const std::string& name)
      : dir(std::filesystem::temp_directory_path() /
            ("clangquill-test-" + name + "-" +
             std::to_string(
                 std::chrono::steady_clock::now().time_since_epoch().count()))) {
    std::filesystem::create_directories(dir);
  }
  ~TempTree() {
    std::error_code ec;
    std::filesystem::remove_all(dir, ec);
  }
  std::string write(const std::string& name, const std::string& contents) {
    auto path = dir / name;
    std::ofstream out(path);
    if (!out) throw std::runtime_error("failed to write fixture " + name);
    out << contents;
    return path.string();
  }
};

}  // namespace

TEST_CASE("shared PCH preserves extraction and dependency tracking",
          "[parser]") {
  // Eight inputs sharing <string>/<vector> at tu_batch=2 span four batches —
  // comfortably past the PCH threshold, so parse_files precompiles the shared
  // closure for every batch after the first.
  TempTree tree("pch");
  std::vector<std::string> inputs;
  for (int i = 0; i < 8; ++i) {
    std::string n = std::to_string(i);
    inputs.push_back(tree.write(
        "in" + n + ".hpp",
        "#pragma once\n#include <string>\n#include <vector>\n"
        "namespace pch_test { std::string f" + n + "(std::vector<int>); }\n"));
  }

  parser::ParseOptions isolated;
  isolated.tu_batch = 1;
  parser::ParseOptions batched;
  batched.tu_batch = 2;

  std::vector<std::vector<std::string>> iso_files;
  std::vector<bool> iso_ok;
  auto a = parser::parse_files(inputs, isolated, &iso_files, &iso_ok);
  std::vector<std::vector<std::string>> pch_files;
  std::vector<bool> pch_ok;
  auto b = parser::parse_files(inputs, batched, &pch_files, &pch_ok);

  CHECK(iso_ok == std::vector<bool>(inputs.size(), true));
  CHECK(pch_ok == std::vector<bool>(inputs.size(), true));
  CHECK(symbol_usrs(a) == symbol_usrs(b));

  // Members of PCH-backed batches keep their full dependency closure: the
  // <string> header lives inside the PCH, yet editing it must still
  // invalidate every member, so it has to stay in each member's file set.
  for (std::size_t i = 0; i < inputs.size(); ++i) {
    REQUIRE_FALSE(pch_files[i].empty());
    CHECK(pch_files[i].front() == inputs[i]);
    auto is_string_header = [](const std::string& dep) {
      return dep == "string" || dep.ends_with("/string");
    };
    bool has_string = false;
    for (const auto& dep : iso_files[i]) {
      if (is_string_header(dep)) has_string = true;
    }
    REQUIRE(has_string);  // the fixture really pulls <string> in
    bool tracked = false;
    for (const auto& dep : pch_files[i]) {
      if (is_string_header(dep)) tracked = true;
    }
    CHECK(tracked);
  }

  // Every dependency a batched member reports has a hashed file row.
  std::set<std::string> rows;
  for (const auto& f : b.files) rows.insert(f.path);
  for (const auto& deps : pch_files) {
    for (const auto& dep : deps) CHECK(rows.count(dep) == 1);
  }
}

TEST_CASE("an input reachable from a common header never enters the PCH",
          "[parser]") {
  // `shared.hpp` is included by every member, so it is a PCH candidate — but
  // its own include closure contains `inner.hpp`, which is itself an input.
  // Baking inner.hpp into the PCH would guard-skip its #include in the batch
  // that owns it and silently drop its symbols; build_pch must drop the
  // candidate instead.
  TempTree tree("pch-excl");
  std::string inner = tree.write(
      "inner.hpp", "#pragma once\nnamespace pch_excl { int inner_fn(); }\n");
  std::string shared = tree.write(
      "shared.hpp",
      "#pragma once\n#include \"inner.hpp\"\n#include <string>\n"
      "namespace pch_excl { std::string shared_fn(); }\n");
  std::vector<std::string> inputs;
  for (int i = 0; i < 6; ++i) {
    std::string n = std::to_string(i);
    inputs.push_back(tree.write(
        "in" + n + ".hpp",
        "#pragma once\n#include \"shared.hpp\"\n"
        "namespace pch_excl { int f" + n + "(); }\n"));
  }
  inputs.push_back(inner);  // parsed by the last batch, alone

  parser::ParseOptions batched;
  batched.tu_batch = 2;  // 4 batches: PCH active, inner.hpp in the tail batch
  std::vector<bool> ok;
  auto m = parser::parse_files(inputs, batched, nullptr, &ok);

  CHECK(ok == std::vector<bool>(7, true));
  CHECK(find(m, "pch_excl::inner_fn") != nullptr);
  for (int i = 0; i < 6; ++i) {
    CHECK(find(m, "pch_excl::f" + std::to_string(i)) != nullptr);
  }
}

#else  // !CLANGQUILL_HAVE_LIBCLANG

TEST_CASE("parser tests skipped without libclang", "[parser][!mayfail]") {
  SUCCEED("built without libclang");
}

#endif
