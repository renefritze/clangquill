"""Sphinx extension that runs the clangquill pipeline at build time.

Enable it with ``extensions = ["clangquill.sphinx_ext"]`` and point
``clangquill_input`` at your headers. On ``builder-inited`` the extension
parses the C++, renders MyST pages into ``clangquill_output_dir`` (under the
Sphinx srcdir), and writes a toctree index — so the generated ``cpp:`` domain
objects participate in cross-references and ``objects.inv`` like any other
page. ``myst_parser`` is pulled in automatically since the output is MyST.

Every knob is a ``clangquill_*`` config value mirroring a field of
:class:`clangquill.config.Config`; see that module for the full list.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from clangquill import __version__
from clangquill.config import CONFIG_FIELDS, Config
from clangquill.pipeline import build

if TYPE_CHECKING:
    from sphinx.application import Sphinx

logger = logging.getLogger(__name__)


def _run(app: Sphinx) -> None:
    """``builder-inited`` hook: parse, render, and index into the srcdir."""
    config = Config.from_mapping({name: getattr(app.config, name) for name, _ in CONFIG_FIELDS})
    if not config.input:
        logger.info("clangquill: no clangquill_input configured; skipping generation")
        return
    result = build(config, base_dir=app.srcdir)
    # Remembered for the build-finished hook so a throwaway IR can be removed.
    app._clangquill_temp_db = result.db_path if result.db_is_temporary else None  # noqa: SLF001
    logger.info(
        "clangquill: wrote %d page(s) from %d symbol(s) to %s",
        len(result.pages),
        result.symbol_count,
        result.output_dir,
    )
    for diagnostic in result.diagnostics:
        logger.warning("clangquill: %s", diagnostic)


def _cleanup(app: Sphinx, exception: Exception | None) -> None:  # noqa: ARG001
    """``build-finished`` hook: drop the throwaway IR when not caching.

    Stale *page* pruning happens during generation (see
    :func:`clangquill.pipeline.build`); here we only remove the temporary SQLite
    database so a build leaves no artifacts behind unless ``clangquill_cache_dir``
    asked for a persistent one.
    """
    db_path = getattr(app, "_clangquill_temp_db", None)
    if db_path is not None:
        db_path.unlink(missing_ok=True)
        app._clangquill_temp_db = None  # noqa: SLF001


def setup(app: Sphinx) -> dict[str, Any]:
    """Register config values and hooks; return extension metadata."""
    # Generated pages are MyST, so the parser must be active to read them.
    app.setup_extension("myst_parser")

    for name, default in CONFIG_FIELDS:
        app.add_config_value(name, default, "env")

    app.connect("builder-inited", _run)
    app.connect("build-finished", _cleanup)

    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
