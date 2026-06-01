#pragma once

#include <optional>
#include <string>
#include <vector>

#include "model/module.hpp"

namespace clangquill::parser {

// Options controlling how a translation unit is parsed. Mirrors the binding
// layer's ParseOptions.
struct ParseOptions {
  std::string std_flag = "c++20";  // -> -std=c++20
  std::vector<std::string> include_dirs;
  std::vector<std::string> defines;
  std::vector<std::string> extra_args;
  std::optional<std::string> compile_commands_dir;
  bool keep_going = true;
};

// Drives libclang over one translation unit at a time, appending extracted IR
// into a ParsedModule. Owns a reusable CXIndex.
class Parser {
 public:
  explicit Parser(ParseOptions options);
  ~Parser();
  Parser(const Parser&) = delete;
  Parser& operator=(const Parser&) = delete;

  // Parses one input file, appending into `out`. Returns false on hard failure
  // (translation unit could not be created).
  bool parse_file(const std::string& path, model::ParsedModule& out);

 private:
  std::vector<std::string> build_args(const std::string& path) const;

  ParseOptions options_;
  void* index_ = nullptr;  // CXIndex (opaque here to keep the header clang-free)
};

}  // namespace clangquill::parser
