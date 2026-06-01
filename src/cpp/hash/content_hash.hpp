#pragma once

#include <string>
#include <vector>

#include "model/parameters.hpp"
#include "model/symbol.hpp"

namespace clangquill::hash {

// Stable hash of a symbol's documented surface. Source location is deliberately
// excluded so moving a symbol within a file does not invalidate the M6 cache;
// the raw comment text is included so doc edits do change the hash.
std::string content_hash(const model::Symbol& sym,
                         const std::vector<model::FunctionParameter>& params,
                         const std::string& raw_comment);

}  // namespace clangquill::hash
