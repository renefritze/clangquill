#pragma once

#include <string>

/**
 * @file
 * @brief Version probe for the native C++ core.
 */

namespace clangquill {

/// @brief Version of the C++ core.
///
/// Kept separate from the Python package version (which comes from
/// setuptools_scm) so the native layer can be probed independently.
/// @return The core version string.
inline std::string core_version() { return "0.0.0"; }

}  // namespace clangquill
