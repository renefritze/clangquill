"""Post-build smoke test for the bundled-libclang wheel.

Run *after installing the wheel* in a clean image that has no system LLVM (see
the ``smoke_test`` job in the wheel workflows). It proves the wheel ships a
working, self-contained libclang: the extension imports, reports a libclang
version, and parses a trivial header into at least one symbol with no
diagnostics.
"""

from __future__ import annotations

import os
import tempfile

from clangquill import _core


def main() -> None:
    assert _core.have_libclang(), "wheel did not bundle libclang"
    print("libclang:", _core.libclang_version())

    with tempfile.TemporaryDirectory() as work:
        header = os.path.join(work, "widget.hpp")
        with open(header, "w", encoding="utf-8") as fh:
            fh.write("/// A documented widget.\nstruct Widget { int width; };\n")

        db = os.path.join(work, "out.sqlite")
        result = _core.parse_to_sqlite([header], db, _core.ParseOptions())
        assert result.symbol_count > 0, result.diagnostics
        assert not result.diagnostics, result.diagnostics
        print("parsed symbols:", result.symbol_count)


if __name__ == "__main__":
    main()
