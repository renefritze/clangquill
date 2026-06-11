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
  int jobs = 0;  ///< Parse threads; `<= 0` means auto (hardware concurrency).
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
  /// @param tu_files Optional sink for this translation unit's full file set
  ///        (the main file plus every transitively `#include`d file). Unlike
  ///        @p out.files — which is deduplicated across every TU parsed into the
  ///        module — this captures exactly what *this* TU pulled in, so a caller
  ///        can attribute each dependency to the input that requires it.
  /// @return `false` on hard failure (the translation unit could not be created).
  bool parse_file(const std::string& path, model::ParsedModule& out,
                  std::vector<std::string>* tu_files = nullptr);

 private:
  std::vector<std::string> build_args(const std::string& path) const;

  ParseOptions options_;
  void* index_ = nullptr;  // CXIndex (opaque here to keep the header clang-free)
};

/// @brief Parses every input file and merges the per-file IR into one module.
///
/// Each translation unit is independent (libclang re-parses its includes from
/// scratch), so they are parsed concurrently across up to
/// `min(inputs, effective_jobs)` threads, each owning its own `Parser`/`CXIndex`
/// (libclang indices must not be shared between threads, but one per thread is
/// safe). Results are merged back in input order — deduplicating source files by
/// path — so the output is identical and deterministic regardless of how many
/// threads ran. `options.jobs <= 0` selects the hardware concurrency.
///
/// @param inputs Translation units to parse, in the order they should merge.
/// @param options Parse configuration applied to every file.
/// @param tu_files Optional sink, sized to and indexed by @p inputs, receiving
///        each translation unit's full file set (its main file plus every
///        transitive `#include`). Lets a caller attribute every dependency to
///        the input that pulled it in for per-TU incremental re-parses.
/// @return The merged IR for all inputs.
model::ParsedModule parse_files(const std::vector<std::string>& inputs,
                                const ParseOptions& options,
                                std::vector<std::vector<std::string>>* tu_files = nullptr);

}  // namespace clangquill::parser
