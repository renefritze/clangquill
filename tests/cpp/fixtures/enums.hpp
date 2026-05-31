#pragma once

/// A scoped enum with explicit values.
enum class Color {
  Red,
  Green = 5,
  Blue,  // 6
};

/// An unscoped enum.
enum Direction {
  North,
  East,
  South,
  West,
};
