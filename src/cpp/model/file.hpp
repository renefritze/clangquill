#pragma once

#include <cstdint>
#include <string>

namespace clangquill::model {

// A source file encountered during parsing, with a content hash for caching.
struct SourceFile {
  std::int64_t id = -1;  // assigned by the store
  std::string path;      // absolute, normalized
  std::string sha256;    // hex digest of file bytes
  std::int64_t size_bytes = 0;
};

}  // namespace clangquill::model
