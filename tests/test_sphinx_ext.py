"""Acceptance test: a minimal Sphinx project driven by the extension.

Builds generated ``api/*.md``, asserts the build is warning-free, and checks
that the generated ``cpp:`` domain objects appear in ``objects.inv``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from clangquill import _core

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(not _core.have_libclang(), reason="core built without libclang")

HEADER = """
/// Geometry primitives.
namespace geo {

/// Abstract base for shapes.
struct Shape {
  /// Compute the area.
  /// @return the area in square units.
  virtual double area() const = 0;
};

/// A circle.
struct Circle : Shape {
  /// Construct from a radius.
  /// @param r the radius
  explicit Circle(double r);
  /// Compute the area.
  double area() const;
};

/// Return a scaled copy of a circle.
/// @param c the circle to scale
/// @see geo::Circle
Circle scale(const Circle &c, double factor);

}  // namespace geo
"""

CONF = """
extensions = ["clangquill.sphinx_ext"]
master_doc = "index"
clangquill_input = ["geo.hpp"]
clangquill_output_dir = "api"
"""

ROOT_INDEX = """
# Project

```{toctree}
:maxdepth: 2

api/index
```
"""


def test_minimal_sphinx_project_builds(tmp_path: Path) -> None:
    pytest.importorskip("sphinx")
    pytest.importorskip("myst_parser")
    from sphinx.application import Sphinx  # noqa: PLC0415
    from sphinx.util.inventory import InventoryFile  # noqa: PLC0415

    src = tmp_path / "src"
    src.mkdir()
    (src / "geo.hpp").write_text(HEADER)
    (src / "conf.py").write_text(CONF)
    (src / "index.md").write_text(ROOT_INDEX)

    out = tmp_path / "out"
    warnings = tmp_path / "warnings.txt"
    app = Sphinx(
        str(src),
        str(src),
        str(out),
        str(tmp_path / "doctree"),
        "html",
        warningiserror=True,
        status=None,
        warning=warnings.open("w"),
    )
    app.build()

    # The extension generated MyST pages under the srcdir.
    assert (src / "api" / "index.md").is_file()
    assert (src / "api" / "geo.md").is_file()

    # objects.inv lists the expected cpp: domain objects.
    with (out / "objects.inv").open("rb") as handle:
        inv = InventoryFile.load(handle, "", lambda a, b: f"{a}/{b}")
    cpp_objects = {name for domain, entries in inv.items() if domain.startswith("cpp:") for name in entries}
    assert "geo::Circle" in cpp_objects
    assert "geo::scale" in cpp_objects

    # geo.html resolved the {cpp:any} cross-reference to a generated object id.
    html = (out / "api" / "geo.html").read_text()
    assert "_CPPv4N3geo6CircleE" in html
