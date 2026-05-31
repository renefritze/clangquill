#pragma once

#include <string>

namespace clangquill {

// Version of the C++ core. Kept separate from the Python package version (which
// comes from setuptools_scm) so the native layer can be probed independently.
inline std::string core_version() { return "0.0.0"; }

}  // namespace clangquill
