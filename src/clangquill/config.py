"""Configuration dataclass shared by the Sphinx extension and the CLI.

A single :class:`Config` describes one clangquill run: which inputs to parse,
how to invoke libclang, and how to render the resulting MyST. The Sphinx
extension reads the ``clangquill_*`` config values into a :class:`Config`; the
``clangquill build`` CLI constructs one directly. Keeping the schema in one
place means both front ends validate identically and stay in sync.

The Sphinx config name of a field is always ``clangquill_<field-name>`` (see
:data:`CONFIG_FIELDS`), so the extension can register and read every value by
iterating the dataclass rather than repeating each name.
"""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# Sphinx config values are namespaced with this prefix.
CONFIG_PREFIX = "clangquill_"

# Permitted values for ``group_by`` (how generated pages are partitioned).
GROUP_BY_CHOICES = ("symbol", "file")


class ConfigError(ValueError):
    """Raised when a :class:`Config` fails validation."""


@dataclass
class Config:
    """Everything one clangquill run needs, validated in :meth:`validate`.

    Field names map onto Sphinx config values by prefixing ``clangquill_``; for
    example :attr:`output_dir` is ``clangquill_output_dir``.
    """

    # -- inputs ---------------------------------------------------------------
    #: Header/source paths (or globs) to parse, relative to the base directory.
    input: list[str] = field(default_factory=list)
    #: Directory holding a ``compile_commands.json`` (overrides std/include/define).
    compile_commands: str | None = None
    #: Extra compiler arguments appended verbatim when no compile DB is used.
    compile_args: list[str] = field(default_factory=list)
    #: ``-I`` include directories.
    include_dirs: list[str] = field(default_factory=list)
    #: C++ standard passed as ``-std=<std>``.
    std: str = "c++20"
    #: ``-D`` preprocessor definitions (``NAME`` or ``NAME=value``).
    defines: list[str] = field(default_factory=list)
    #: Clang resource directory (``-resource-dir``); ``None`` lets clang decide.
    clang_resource_dir: str | None = None

    # -- output ---------------------------------------------------------------
    #: Directory (under the Sphinx srcdir / CWD) that generated pages go into.
    output_dir: str = "api"
    #: Directories searched before the bundled templates for overrides.
    template_dirs: list[str] = field(default_factory=list)
    #: Per-kind template overrides, e.g. ``{"class": "my_class"}``.
    templates: dict[str, str] = field(default_factory=dict)
    #: Where the SQLite IR is cached; ``None`` uses a throwaway temp file.
    cache_dir: str | None = None
    #: Emit pages/sections for symbols that carry no documentation comment.
    include_undocumented: bool = True
    #: Comment-parser override (a registered name or a dotted import path).
    comment_parser: str | None = None
    #: How to partition output pages: one of :data:`GROUP_BY_CHOICES`.
    group_by: str = "symbol"

    # -- toctree / root -------------------------------------------------------
    #: ``:maxdepth:`` of the generated root toctree.
    toctree_maxdepth: int = 2
    #: Stem of the generated index/toctree page within ``output_dir``.
    root_document: str = "index"

    def validate(self) -> Config:
        """Validate the configuration in place, returning ``self``.

        Raises :class:`ConfigError` with an actionable message on the first
        problem found.
        """
        if not self.input:
            msg = f"{CONFIG_PREFIX}input must list at least one C++ file to parse"
            raise ConfigError(msg)
        if not isinstance(self.input, list) or not all(isinstance(p, str) for p in self.input):
            msg = f"{CONFIG_PREFIX}input must be a list of path strings"
            raise ConfigError(msg)
        if not self.std:
            msg = f"{CONFIG_PREFIX}std must be a non-empty C++ standard, e.g. 'c++20'"
            raise ConfigError(msg)
        if self.group_by not in GROUP_BY_CHOICES:
            choices = ", ".join(GROUP_BY_CHOICES)
            msg = f"{CONFIG_PREFIX}group_by must be one of {{{choices}}}, got {self.group_by!r}"
            raise ConfigError(msg)
        if not self.output_dir:
            msg = f"{CONFIG_PREFIX}output_dir must be a non-empty directory name"
            raise ConfigError(msg)
        if self.toctree_maxdepth < 1:
            msg = f"{CONFIG_PREFIX}toctree_maxdepth must be >= 1, got {self.toctree_maxdepth}"
            raise ConfigError(msg)
        if not isinstance(self.templates, dict):
            msg = f"{CONFIG_PREFIX}templates must be a mapping of kind to template name"
            raise ConfigError(msg)
        return self

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> Config:
        """Build a :class:`Config` from a mapping keyed by ``clangquill_*`` names.

        Keys without the :data:`CONFIG_PREFIX` are ignored, so a Sphinx
        ``app.config`` (or any superset mapping) can be passed directly.
        ``input`` accepts a bare string for convenience and is normalised to a
        single-element list.
        """
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            key = CONFIG_PREFIX + f.name
            if key in values and values[key] is not None:
                kwargs[f.name] = values[key]
        if isinstance(kwargs.get("input"), str):
            kwargs["input"] = [kwargs["input"]]
        return cls(**kwargs)


def config_specs() -> Iterable[tuple[str, Any]]:
    """Yield ``(sphinx_name, default)`` pairs for every config field.

    Used by :func:`clangquill.sphinx_ext.setup` to register each value without
    duplicating the field list.
    """
    for f in fields(Config):
        if f.default is not MISSING:
            default = f.default
        elif f.default_factory is not MISSING:
            default = f.default_factory()
        else:  # pragma: no cover - every field has a default
            default = None
        yield CONFIG_PREFIX + f.name, default


#: ``(sphinx_name, default)`` for each registrable config value.
CONFIG_FIELDS = tuple(config_specs())

__all__ = [
    "CONFIG_FIELDS",
    "CONFIG_PREFIX",
    "GROUP_BY_CHOICES",
    "Config",
    "ConfigError",
    "config_specs",
]
