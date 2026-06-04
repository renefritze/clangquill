"""The end-to-end build: parse C++ → SQLite IR → rendered MyST pages.

Both front ends (the Sphinx extension and the ``clangquill build`` CLI) drive
the same pipeline here so they behave identically. The steps are:

1. Resolve the configured inputs against a base directory.
2. Parse them with the libclang-backed core into a SQLite database.
3. Render the IR into MyST pages with the :class:`~clangquill.generator.Generator`.
4. Prune pages left over from a previous run.

When ``clangquill_cache_dir`` is configured the build becomes *incremental*
(milestone M6): the SQLite IR and a small bookkeeping cache persist between
runs, so an unchanged build skips both the libclang parse and every output
write, touching one header re-parses and rewrites only the affected pages, and
symbols that disappear have their pages deleted. Without a cache directory the
build is stateless: it always re-parses into a throwaway IR, rewrites every
page, and prunes stale pages via a manifest.
"""

from __future__ import annotations

import glob
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from clangquill import _core
from clangquill.cache import BuildCache, file_sha256, fingerprint, hash_text
from clangquill.generator import Generator
from clangquill.store import Store

if TYPE_CHECKING:
    from clangquill.config import Config

# Name of the manifest tracking generated pages, written into ``output_dir`` so
# stale pages from a previous build can be pruned on the next one.
MANIFEST_NAME = ".clangquill-manifest.json"

# Filename of the persisted SQLite IR within a configured cache directory.
IR_NAME = "clangquill.sqlite"


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
    #: Whether libclang re-parsed this run (``False`` = served from the cache).
    parsed: bool = True
    #: Output filenames actually (re)written this run (incremental builds only
    #: write changed pages; a full build lists every page it wrote).
    pages_written: list[str] = field(default_factory=list)
    #: Output filenames deleted this run because their source vanished.
    pages_deleted: list[str] = field(default_factory=list)


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


def _parse_fingerprint(config: Config, base_dir: Path, inputs: list[str]) -> str:
    """Fingerprint everything that, if changed, invalidates the cached parse.

    Covers the resolved input set, the normalized compile arguments, the
    libclang toolchain version and (when used) the ``compile_commands.json``
    contents. File *contents* are tracked separately via per-file hashes, so
    this captures only the parse *configuration*.
    """
    compile_commands_hash = ""
    if config.compile_commands:
        # ``compile_commands`` names the *directory* holding compile_commands.json
        # (it is handed to clang_CompilationDatabase_fromDirectory), so hash the
        # JSON file inside it rather than the directory.
        cc = (base_dir / config.compile_commands / "compile_commands.json").resolve()
        try:
            compile_commands_hash = file_sha256(cc)
        except OSError:
            compile_commands_hash = "missing"
    return fingerprint(
        {
            "inputs": sorted(inputs),
            "std": config.std,
            "include_dirs": [str((base_dir / d).resolve()) for d in config.include_dirs],
            "defines": list(config.defines),
            "compile_args": list(config.compile_args),
            "clang_resource_dir": config.clang_resource_dir or "",
            "compile_commands": compile_commands_hash,
            "core_version": getattr(_core, "__core_version__", ""),
            "libclang_version": _core.libclang_version(),
        },
    )


def _make_generator(config: Config, base_dir: Path, store: Store) -> Generator:
    """Build a :class:`Generator` wired from ``config`` against ``store``."""
    return Generator(
        store,
        template_dirs=[str((base_dir / d).resolve()) for d in config.template_dirs],
        templates=config.templates,
        include_undocumented=config.include_undocumented,
        comment_parser=config.comment_parser,
    )


def _rendered_files(generator: Generator, config: Config) -> list[tuple[str, str]]:
    """Render every output into ``(filename, text)`` pairs, index last."""
    pages = generator.render_pages(group_by=config.group_by)
    index_text = generator.render_index(pages, toctree_maxdepth=config.toctree_maxdepth)
    rendered = [(f"{page.stem}.md", page.text) for page in pages]
    rendered.append((f"{config.root_document}.md", index_text))
    return rendered


def build(config: Config, *, base_dir: str | Path) -> BuildResult:
    """Run the pipeline for ``config`` rooted at ``base_dir``.

    ``base_dir`` is the Sphinx srcdir (or the CWD for the CLI); every relative
    path in ``config`` is resolved against it. A configured ``cache_dir`` makes
    the build incremental (see the module docstring); otherwise it is stateless.
    """
    config.validate()
    base = Path(base_dir).resolve()
    inputs = _resolve_inputs(config.input, base)
    output_dir = (base / config.output_dir).resolve()
    if config.cache_dir:
        cache_dir = (base / config.cache_dir).resolve()
        return _incremental_build(config, base, inputs, output_dir, cache_dir)
    return _full_build(config, base, inputs, output_dir)


def _new_temp_db(directory: Path | None = None) -> Path:
    """Create an empty temp file for a throwaway IR and return its path."""
    handle = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False, dir=directory)  # noqa: SIM115
    handle.close()
    return Path(handle.name)


def _full_build(config: Config, base: Path, inputs: list[str], output_dir: Path) -> BuildResult:
    """Stateless build: parse into a throwaway IR and rewrite every page."""
    db_path = _new_temp_db()

    succeeded = False
    try:
        result = _core.parse_to_sqlite(inputs, str(db_path), _parse_options(config, base))
        with Store.open(db_path) as store:
            pages = _make_generator(config, base, store).generate(
                output_dir,
                group_by=config.group_by,
                toctree_maxdepth=config.toctree_maxdepth,
                root_document=config.root_document,
            )
        succeeded = True
    finally:
        if not succeeded:
            db_path.unlink(missing_ok=True)

    written = [f"{config.root_document}.md", *(f"{stem}.md" for stem in pages)]
    deleted = _prune_stale(output_dir, written)

    return BuildResult(
        output_dir=output_dir,
        pages=pages,
        db_path=db_path,
        db_is_temporary=True,
        symbol_count=result.symbol_count,
        reference_count=result.reference_count,
        file_count=result.file_count,
        diagnostics=list(result.diagnostics),
        parsed=True,
        pages_written=sorted(written),
        pages_deleted=deleted,
    )


def _incremental_build(
    config: Config,
    base: Path,
    inputs: list[str],
    output_dir: Path,
    cache_dir: Path,
) -> BuildResult:
    """Reuse the cached parse where possible and write only changed pages."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    ir_path = cache_dir / IR_NAME
    parse_fp = _parse_fingerprint(config, base, inputs)

    with BuildCache.open(cache_dir) as cache:
        parsed = not (ir_path.is_file() and cache.parse_is_current(parse_fp))
        counts: _core.ParseResult | None = None
        diagnostics: list[str] = []
        if parsed:
            counts = _parse_into(inputs, ir_path, _parse_options(config, base))
            diagnostics = list(counts.diagnostics)

        with Store.open(ir_path) as store:
            if parsed:
                cache.record_parse(parse_fp, {f.path: f.sha256 for f in store.files()})
            generator = _make_generator(config, base, store)
            rendered = _rendered_files(generator, config)
            symbol_count = store.symbol_count()
            reference_count = store.reference_count()
            file_count = store.file_count()

        page_stems = [name[: -len(".md")] for name, _ in rendered[:-1]]
        written, deleted = _apply_outputs(output_dir, rendered, cache)

    return BuildResult(
        output_dir=output_dir,
        pages=page_stems,
        db_path=ir_path,
        db_is_temporary=False,
        symbol_count=counts.symbol_count if counts else symbol_count,
        reference_count=counts.reference_count if counts else reference_count,
        file_count=counts.file_count if counts else file_count,
        diagnostics=diagnostics,
        parsed=parsed,
        pages_written=written,
        pages_deleted=deleted,
    )


def _parse_into(inputs: list[str], ir_path: Path, options: _core.ParseOptions) -> _core.ParseResult:
    """Parse into a sibling temp DB, then atomically replace ``ir_path``.

    The core cannot append to an existing IR (its ``files`` rows are unique), so
    a fresh database is built next to the target and moved into place only on
    success; a failed parse leaves any previously cached IR untouched.
    """
    tmp = _new_temp_db(ir_path.parent)
    try:
        result = _core.parse_to_sqlite(inputs, str(tmp), options)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(ir_path)
    return result


def _apply_outputs(
    output_dir: Path,
    rendered: list[tuple[str, str]],
    cache: BuildCache,
) -> tuple[list[str], list[str]]:
    """Write changed pages, delete vanished ones, and refresh the cache index.

    Returns ``(written, deleted)`` filenames. A page is rewritten only when its
    content hash differs from the cached one (or the file is missing on disk),
    so an unchanged build leaves every page untouched.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    previous = cache.outputs()
    new_index: dict[str, str] = {}
    written: list[str] = []
    for name, text in rendered:
        content_hash = hash_text(text)
        new_index[name] = content_hash
        target = output_dir / name
        if previous.get(name) != content_hash or not target.exists():
            target.write_text(text, encoding="utf-8")
            written.append(name)

    deleted: list[str] = []
    for name in previous:
        if name not in new_index:
            (output_dir / name).unlink(missing_ok=True)
            deleted.append(name)

    cache.record_outputs(new_index)
    # Keep the manifest in sync so a later switch to a stateless build prunes
    # these pages correctly.
    (output_dir / MANIFEST_NAME).write_text(json.dumps(sorted(new_index), indent=2), encoding="utf-8")
    return sorted(written), sorted(deleted)


def _prune_stale(output_dir: Path, kept: list[str]) -> list[str]:
    """Delete pages this run did not write, then record the new manifest.

    Only files listed in the *previous* manifest are removed, so hand-written
    files that happen to share ``output_dir`` are never touched. Returns the
    filenames that were deleted.
    """
    deleted: list[str] = []
    manifest = output_dir / MANIFEST_NAME
    if manifest.exists():
        try:
            previous = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            previous = []
        for name in previous:
            if name not in kept:
                (output_dir / name).unlink(missing_ok=True)
                deleted.append(name)
    manifest.write_text(json.dumps(sorted(kept), indent=2), encoding="utf-8")
    return sorted(deleted)


__all__ = ["IR_NAME", "MANIFEST_NAME", "BuildResult", "build"]
