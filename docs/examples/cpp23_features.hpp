#pragma once

/// \file
/// Showcase header that clangquill dogfoods **only** when the linked libclang is
/// new enough to parse modern standards (see ``docs/conf.py``). On an older
/// toolchain it is simply not parsed, so the docs build never fails — it just
/// omits these pages.

namespace clangquill::demo {

/// A widget demonstrating C++23 *deducing this* and ``if consteval``.
struct Widget {
  /// The stored width.
  int width = 0;

  /// Return the width through an explicit object parameter (C++23 deducing
  /// ``this``), so the same body serves every value category.
  template <typename Self>
  auto value(this Self&& self) {
    return self.width;
  }

  /// Double the width, taking a constant-evaluation fast path (C++23
  /// ``if consteval``).
  constexpr int doubled() const {
    if consteval {
      return width + width;
    } else {
      return width * 2;
    }
  }

  /// Callable without an instance (C++23 ``static operator()``).
  static int identity(int x) { return x; }
};

/// A 2-D view demonstrating the C++23 multidimensional subscript operator.
struct Grid {
  /// Row-major access via ``grid[r, c]`` (C++23 multidimensional ``operator[]``).
  int operator[](int row, int col) const { return row * cols + col; }

  /// Number of columns backing the flat index.
  int cols = 1;
};

/// Return the first element of a parameter pack using C++26 pack indexing.
template <typename... Ts>
auto first(Ts... values) {
  return values...[0];
}

}  // namespace clangquill::demo
