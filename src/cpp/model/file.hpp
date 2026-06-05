#pragma once

#include <cstdint>
#include <string>

/**
 * @file
 * @brief Record for a source file encountered during parsing.
 */

namespace clangquill::model {

/// @brief A source file encountered during parsing, with a content hash for caching.
struct SourceFile {
  std::int64_t id = -1;       ///< Row id assigned by the store; -1 until written.
  std::string path;           ///< Absolute, normalized path.
  std::string sha256;         ///< Hex digest of the file bytes.
  std::int64_t size_bytes = 0;  ///< File size in bytes.
};

}  // namespace clangquill::model
