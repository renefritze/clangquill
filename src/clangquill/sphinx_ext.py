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

from typing import TYPE_CHECKING, Any

from sphinx.errors import ExtensionError
from sphinx.util import logging

from clangquill import __version__, _core
from clangquill.config import CONFIG_FIELDS, CONFIG_PREFIX, Config, ConfigError
from clangquill.pipeline import build

if TYPE_CHECKING:
    from sphinx.application import Sphinx
    from sphinx.config import Config as SphinxConfig

logger = logging.getLogger(__name__)


def _warn_unknown_config(app: Sphinx, config: SphinxConfig) -> None:  # noqa: ARG001
    """``config-inited`` hook: flag ``clangquill_*`` names that match no option.

    ``Config.from_mapping`` deliberately ignores unknown keys (so any superset
    mapping can be passed), which means a conf.py typo like ``clangquill_inputs``
    would otherwise vanish silently — Sphinx itself accepts any variable in
    conf.py. Suppressible via ``suppress_warnings = ["clangquill.config"]``.
    """
    known = {name for name, _ in CONFIG_FIELDS}
    for name in config._raw_config:  # noqa: SLF001 - the conf.py namespace has no public accessor
        if name.startswith(CONFIG_PREFIX) and name not in known:
            logger.warning(
                "unknown config value %r — no clangquill option has that name (see clangquill.config.Config)",
                name,
                type="clangquill",
                subtype="config",
            )


def _run(app: Sphinx) -> None:
    """``builder-inited`` hook: parse, render, and index into the srcdir."""
    config = Config.from_mapping({name: getattr(app.config, name) for name, _ in CONFIG_FIELDS})
    if not config.input:
        logger.info("clangquill: no clangquill_input configured; skipping generation")
        return
    if not _core.have_libclang():
        # Degrade gracefully where the core was built without libclang (e.g. a
        # docs environment lacking the dev headers) rather than failing the
        # whole Sphinx build. Still write a placeholder root document so any
        # toctree pointing at the output keeps resolving. Suppressible via
        # ``suppress_warnings = ["clangquill.libclang"]`` (e.g. for -W builds).
        logger.warning(
            "core built without libclang; skipping API generation",
            type="clangquill",
            subtype="libclang",
        )
        _write_placeholder(app, config)
        return
    try:
        result = build(config, base_dir=app.srcdir)
    except (ConfigError, FileNotFoundError) as exc:
        # Anticipated user-input failures (a bad clangquill_* value, an input
        # pattern matching nothing) become a clean build error instead of a
        # raw traceback.
        msg = f"clangquill: {exc}"
        raise ExtensionError(msg) from exc
    # Remembered for the build-finished hook so a throwaway IR can be removed.
    app._clangquill_temp_db = result.db_path if result.db_is_temporary else None  # noqa: SLF001
    logger.info(
        "clangquill: wrote %d page(s) from %d symbol(s) to %s",
        len(result.pages),
        result.symbol_count,
        result.output_dir,
    )
    for diagnostic in result.diagnostics:
        logger.warning("%s", diagnostic, type="clangquill", subtype="parse")


def _write_placeholder(app: Sphinx, config: Config) -> None:
    """Write a stub root document so a toctree referencing the output resolves."""
    from pathlib import Path  # noqa: PLC0415

    out = Path(app.srcdir) / config.output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{config.root_document}.md").write_text(
        "# API Reference\n\nAPI generation was skipped (libclang unavailable).\n",
        encoding="utf-8",
    )


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
    # Generated pages are MyST, so a MyST parser must be active to read them.
    # Pull in myst_parser only when no MyST parser is already configured —
    # myst_nb supersedes it and registering both for ``.md`` raises a conflict.
    # Inspect both already-loaded extensions and the full configured list, so the
    # result does not depend on where the extension sits in conf.py's order.
    configured = set(app.extensions) | set(app.config.extensions)
    if not ({"myst_parser", "myst_nb"} & configured):
        app.setup_extension("myst_parser")

    for name, default in CONFIG_FIELDS:
        app.add_config_value(name, default, "env")

    app.connect("config-inited", _warn_unknown_config)
    app.connect("builder-inited", _run)
    app.connect("build-finished", _cleanup)

    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
