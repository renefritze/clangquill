#pragma once

/// \file
/// Showcase header that clangquill dogfoods **only** when the linked libclang is
/// new enough to parse modern standards (see ``docs/conf.py``). On an older
/// toolchain it is simply not parsed, so the docs build never fails — it just
/// omits these pages.
///
/// \note The C++23 *deducing this* explicit object parameter is deliberately
/// exercised by the test suite rather than here: clang parses it, but Sphinx's
/// C++ domain cannot yet render the ``this Self&&`` signature, which would fail
/// the warning-as-error docs build.

namespace clangquill::demo {

/// A widget demonstrating the C++23 ``if consteval`` fast path.
struct Widget {
  /// The stored width.
  int width = 0;

  /// Double the width, taking a constant-evaluation fast path (C++23
  /// ``if consteval``).
  constexpr int doubled() const {
    if consteval {
      return width + width;
    } else {
      return width * 2;
    }
  }
};

/// A 2-D view demonstrating the C++23 multidimensional subscript operator.
struct Grid {
  /// Row-major access via ``grid[r, c]`` (C++23 multidimensional ``operator[]``).
  int operator[](int row, int col) const { return row * cols + col; }

  /// Number of columns backing the flat index.
  int cols = 1;
};

/// A summer that is callable without an instance (C++23 ``static operator()``).
struct Adder {
  /// Add two values.
  static int operator()(int a, int b) { return a + b; }
};

/// Return the first element of a parameter pack using C++26 pack indexing.
///
/// The ``requires`` constraint keeps the example well-formed for the empty-pack
/// case (``first()`` would otherwise be ill-formed).
template <typename... Ts>
  requires (sizeof...(Ts) > 0)
auto first(Ts... values) {
  return values...[0];
}

}  // namespace clangquill::demo
