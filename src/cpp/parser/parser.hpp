#pragma once

#include <memory>
#include <optional>
#include <string>
#include <unordered_set>
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
  /// Inputs grouped into one umbrella translation unit. Grouping amortises the
  /// dominant parse cost — re-lexing the shared `#include` closure — across the
  /// batch. `0` selects a default batch size; `1` parses every input as its own
  /// translation unit. Forced to `1` when `compile_commands_dir` is set, since
  /// per-file compile flags cannot be merged into one unit.
  int tu_batch = 0;
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

  /// @brief Parses a batch of inputs as one umbrella translation unit.
  ///
  /// A synthetic in-memory main file `#include`s every member, so the shared
  /// transitive include closure is lexed and parsed once for the whole batch
  /// instead of once per input. Only declarations physically located in the
  /// member files are extracted, so the result matches per-file parsing for
  /// self-contained headers. A batch of one delegates to @ref parse_file. If
  /// the umbrella itself cannot be created, every member is re-parsed
  /// individually as a fallback.
  ///
  /// @param paths The batch members, in input order.
  /// @param out Module that extracted rows are appended to.
  /// @param member_files Optional sink (sized to @p paths) receiving each
  ///        member's file set — the member plus its transitive `#include`s,
  ///        recovered exactly from the preprocessing record even when an
  ///        include was guard-skipped because a sibling pulled it in first.
  /// @param member_ok Optional sink (sized to @p paths) flagging members whose
  ///        translation unit (or umbrella inclusion) hard-failed as `false`.
  /// @return `false` when any member hard-failed.
  bool parse_batch(const std::vector<std::string>& paths,
                   model::ParsedModule& out,
                   std::vector<std::vector<std::string>>* member_files = nullptr,
                   std::vector<bool>* member_ok = nullptr);

  /// @brief Precompiles @p headers into a PCH at @p out_path.
  ///
  /// A synthetic header `#include`-ing every entry (in order, by the given
  /// spelling) is parsed once and serialized with `clang_saveTranslationUnit`,
  /// so later umbrella batches can load the result instead of re-parsing the
  /// shared closure. Any candidate whose transitive closure reaches a file in
  /// @p exclude is dropped and the PCH is re-built without it: baking an
  /// excluded file (in practice: a parse *input*) into the PCH would
  /// guard-skip its `#include` in member files and hide its declarations from
  /// extraction.
  ///
  /// @param headers Candidate headers, in the order they should be compiled.
  /// @param exclude Files that must not end up inside the PCH closure.
  /// @param out_path Where the serialized PCH is written.
  /// @param pch_files Receives the PCH's own file closure (every header baked
  ///        in). Pass it to @ref set_pch, and record those files wherever the
  ///        module's file rows are assembled — translation units that load the
  ///        PCH no longer report them.
  /// @return `false` when nothing could be precompiled (unwritable output, a
  ///         hard error in a common header, every candidate excluded); the
  ///         caller simply proceeds without a PCH.
  bool build_pch(std::vector<std::string> headers,
                 const std::unordered_set<std::string>& exclude,
                 const std::string& out_path,
                 std::vector<std::string>* pch_files);

  /// @brief Loads @p pch_path (via `-include-pch`) into every subsequent
  ///        umbrella batch, so the precompiled common headers are deserialized
  ///        instead of re-parsed.
  ///
  /// The headers baked into the PCH must not include any batch member (see
  /// @ref build_pch's @p exclude). Because a PCH-backed unit's preprocessing
  /// record cannot see edges *between* files the PCH owns, @p pch_files (the
  /// PCH's closure) is appended to every member's dependency closure —
  /// conservative for members that use only part of the PCH, which can only
  /// cause extra incremental re-parses, never missed ones. If the PCH fails to
  /// load, the batch is retried without it, so a stale or clobbered file costs
  /// speed, not symbols.
  ///
  /// @param pch_path Serialized PCH produced by @ref build_pch; empty disables.
  /// @param pch_files That PCH's file closure, as reported by @ref build_pch.
  void set_pch(std::string pch_path, std::vector<std::string> pch_files);

 private:
  std::vector<std::string> build_args(const std::string& path) const;

  ParseOptions options_;
  void* index_ = nullptr;  // CXIndex (opaque here to keep the header clang-free)
  std::string pch_path_;   // set_pch: -include-pch for umbrella batches
  std::vector<std::string> pch_files_;  // that PCH's own include closure
  // Lazily-loaded compile_commands.json reader, shared across this parser's
  // translation units (mutable: caching it does not change observable state).
  mutable std::unique_ptr<class CompileDb> compile_db_;
};

/// @brief Parses every input file and merges the per-batch IR into one module.
///
/// Inputs are grouped into batches of `options.tu_batch` (see ParseOptions) and
/// each batch is parsed as one umbrella translation unit, so the shared
/// `#include` closure is parsed once per batch rather than once per input.
/// Batches are parsed concurrently across up to `min(batches, effective_jobs)`
/// threads, each owning its own `Parser`/`CXIndex` (libclang indices must not
/// be shared between threads, but one per thread is safe). Batch composition
/// depends only on the input order — never on the job count — and results merge
/// back in batch order, so the output is deterministic regardless of how many
/// threads ran. `options.jobs <= 0` selects the hardware concurrency.
///
/// When the run spans enough batches, the first batch is parsed up front and
/// the headers most of its members share are precompiled into a temporary PCH
/// that every remaining batch loads instead of re-parsing (see
/// Parser::build_pch / Parser::set_pch), eliminating most of the per-batch
/// fixed cost. Inputs are never baked into the PCH, and the PCH widens the
/// same cross-member preprocessor-context tradeoff batching already makes —
/// `tu_batch = 1` opts out of both.
///
/// @param inputs Translation units to parse, in the order they should merge.
/// @param options Parse configuration applied to every file.
/// @param tu_files Optional sink, sized to and indexed by @p inputs, receiving
///        each input's file set (the input plus every transitive `#include`).
///        Lets a caller attribute every dependency to the input that pulled it
///        in for per-TU incremental re-parses.
/// @param tu_parsed Optional sink, sized to and indexed by @p inputs, flagging
///        inputs whose translation unit hard-failed as `false`.
/// @return The merged IR for all inputs.
model::ParsedModule parse_files(const std::vector<std::string>& inputs,
                                const ParseOptions& options,
                                std::vector<std::vector<std::string>>* tu_files = nullptr,
                                std::vector<bool>* tu_parsed = nullptr);

}  // namespace clangquill::parser
