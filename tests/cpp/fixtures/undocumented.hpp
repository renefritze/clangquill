#pragma once

/// This function is documented.
int documented_function(int x);

int undocumented_function(int y);

struct Mixed {
  /// documented field
  int a;
  int b;  // undocumented field
};
