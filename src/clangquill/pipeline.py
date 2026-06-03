"""The end-to-end build: parse C++ → SQLite IR → rendered MyST pages.

Both front ends (the Sphinx extension and the ``clangquill build`` CLI) drive
the same pipeline here so they behave identically. The steps are:

1. Resolve the configured inputs against a base directory.
2. Parse them with the libclang-backed core into a SQLite database.
3. Render the IR into MyST pages with the :class:`~clangquill.generator.Generator`.
4. Prune pages left over from a previous run (manifest-based stale cleanup).
"""

from __future__ import annotations

import glob
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from clangquill import _core
from clangquill.generator import Generator
from clangquill.store import Store

if TYPE_CHECKING:
    from clangquill.config import Config

# Name of the manifest tracking generated pages, written into ``output_dir`` so
# stale pages from a previous build can be pruned on the next one.
MANIFEST_NAME = ".clangquill-manifest.json"


@dataclass
class BuildResult:
    """Outcome of a :func:`build` run."""

    #: Resolved output directory holding the generated pages.
    output_dir: Path
    #: Page stems written (excluding the index), in toctree order.
    pages: list[str]
    #: Path of the SQLite IR (a temp file unless ``cache_dir`` was configured).
    db_path: Path
    #: Whether ``db_path`` is a throwaway temp file the caller should remove.
    db_is_temporary: bool = False
    #: Number of symbols written to the IR.
    symbol_count: int = 0
    #: Number of cross-reference edges written to the IR.
    reference_count: int = 0
    #: Number of source files parsed.
    file_count: int = 0
    #: Non-fatal diagnostics emitted by libclang.
    diagnostics: list[str] = field(default_factory=list)


def _resolve_inputs(patterns: list[str], base_dir: Path) -> list[str]:
    """Expand ``patterns`` (paths or globs) relative to ``base_dir``.

    Order is preserved and duplicates removed so the parse is deterministic.
    Raises :class:`FileNotFoundError` if a pattern matches nothing.
    """
    resolved: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        candidate = Path(pattern)
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        matches = sorted(glob.glob(str(candidate), recursive=True))  # noqa: PTH207
        if not matches:
            if candidate.exists():
                matches = [str(candidate)]
            else:
                msg = f"clangquill input matched no files: {pattern!r} (under {base_dir})"
                raise FileNotFoundError(msg)
        # A glob can match directories (e.g. ``include/*``); only files can be
        # parsed, so skip the rest rather than handing them to libclang.
        for match in matches:
            match_path = Path(match)
            if not match_path.is_file():
                continue
            full = str(match_path.resolve())
            if full not in seen:
                seen.add(full)
                resolved.append(full)
    return resolved


def _parse_options(config: Config, base_dir: Path) -> _core.ParseOptions:
    """Translate a :class:`Config` into core :class:`ParseOptions`."""
    opt = _core.ParseOptions()
    opt.std_flag = config.std
    opt.include_dirs = [str((base_dir / d).resolve()) for d in config.include_dirs]
    opt.defines = list(config.defines)
    extra = list(config.compile_args)
    if config.clang_resource_dir:
        extra.append(f"-resource-dir={Path(config.clang_resource_dir).expanduser()}")
    opt.extra_args = extra
    if config.compile_commands:
        opt.compile_commands_dir = str((base_dir / config.compile_commands).resolve())
    return opt


def _db_path(config: Config, base_dir: Path) -> tuple[Path, bool]:
    """Choose where the SQLite IR lives; ``True`` means it is a temp file."""
    if config.cache_dir:
        cache = (base_dir / config.cache_dir).resolve()
        cache.mkdir(parents=True, exist_ok=True)
        return cache / "clangquill.sqlite", False
    handle = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)  # noqa: SIM115
    handle.close()
    return Path(handle.name), True


def build(config: Config, *, base_dir: str | Path) -> BuildResult:
    """Run the full pipeline for ``config`` rooted at ``base_dir``.

    ``base_dir`` is the Sphinx srcdir (or the CWD for the CLI); every relative
    path in ``config`` is resolved against it. The validated config drives the
    parse and render; stale pages from a prior run are pruned afterwards.
    """
    config.validate()
    base = Path(base_dir).resolve()
    inputs = _resolve_inputs(config.input, base)
    output_dir = (base / config.output_dir).resolve()

    db_path, db_is_temporary = _db_path(config, base)
    # On any failure path, drop a throwaway IR so a failed build leaks nothing;
    # a configured cache_dir database is left in place for inspection.
    succeeded = False
    try:
        result = _core.parse_to_sqlite(inputs, str(db_path), _parse_options(config, base))
        with Store.open(db_path) as store:
            generator = Generator(
                store,
                template_dirs=[str((base / d).resolve()) for d in config.template_dirs],
                templates=config.templates,
                include_undocumented=config.include_undocumented,
                comment_parser=config.comment_parser,
            )
            pages = generator.generate(
                output_dir,
                group_by=config.group_by,
                toctree_maxdepth=config.toctree_maxdepth,
                root_document=config.root_document,
            )
        succeeded = True
    finally:
        if not succeeded and db_is_temporary:
            db_path.unlink(missing_ok=True)

    kept = [f"{config.root_document}.md", *(f"{stem}.md" for stem in pages)]
    _prune_stale(output_dir, kept)

    return BuildResult(
        output_dir=output_dir,
        pages=pages,
        db_path=db_path,
        db_is_temporary=db_is_temporary,
        symbol_count=result.symbol_count,
        reference_count=result.reference_count,
        file_count=result.file_count,
        diagnostics=list(result.diagnostics),
    )


def _prune_stale(output_dir: Path, kept: list[str]) -> None:
    """Delete pages this run did not write, then record the new manifest.

    Only files listed in the *previous* manifest are removed, so hand-written
    files that happen to share ``output_dir`` are never touched.
    """
    manifest = output_dir / MANIFEST_NAME
    if manifest.exists():
        try:
            previous = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            previous = []
        for name in previous:
            if name not in kept:
                (output_dir / name).unlink(missing_ok=True)
    manifest.write_text(json.dumps(sorted(kept), indent=2), encoding="utf-8")


__all__ = ["MANIFEST_NAME", "BuildResult", "build"]
