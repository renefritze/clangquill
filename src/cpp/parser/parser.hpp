#pragma once

#include <optional>
#include <string>
#include <vector>

#include "model/module.hpp"

/**
 * @file
 * @brief Translation-unit driver that turns C++ sources into the IR model.
 */

namespace clangquill::parser {

/// @brief Options controlling how a translation unit is parsed.
///
/// Mirrors the binding layer's `ParseOptions`.
struct ParseOptions {
  std::string std_flag = "c++20";  ///< C++ standard, passed as `-std=<flag>`.
  std::vector<std::string> include_dirs;  ///< `-I` include directories.
  std::vector<std::string> defines;       ///< `-D` preprocessor definitions.
  std::vector<std::string> extra_args;    ///< Extra compiler arguments appended verbatim.
  std::optional<std::string> compile_commands_dir;  ///< Directory holding a compile_commands.json.
  bool keep_going = true;  ///< Continue past recoverable parse errors.
};

/// @brief Drives libclang over one translation unit at a time.
///
/// Appends extracted IR into a ParsedModule and owns a reusable CXIndex.
class Parser {
 public:
  /// @brief Constructs a parser with the given options.
  /// @param options Parse configuration applied to every file.
  explicit Parser(ParseOptions options);
  ~Parser();
  Parser(const Parser&) = delete;
  Parser& operator=(const Parser&) = delete;

  /// @brief Parses one input file, appending its IR into @p out.
  /// @param path Path of the translation unit to parse.
  /// @param out Module that extracted rows are appended to.
  /// @return `false` on hard failure (the translation unit could not be created).
  bool parse_file(const std::string& path, model::ParsedModule& out);

 private:
  std::vector<std::string> build_args(const std::string& path) const;

  ParseOptions options_;
  void* index_ = nullptr;  // CXIndex (opaque here to keep the header clang-free)
};

}  // namespace clangquill::parser
