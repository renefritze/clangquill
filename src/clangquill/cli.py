"""Standalone command line interface for clangquill.

``clangquill build`` runs the same pipeline as the Sphinx extension but without
Sphinx: it parses the given C++ inputs and writes MyST pages to an output
directory. It is handy for previewing output or wiring clangquill into a build
system that is not Sphinx-driven.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from clangquill.config import GROUP_BY_CHOICES, Config, ConfigError
from clangquill.pipeline import build as run_pipeline

app = typer.Typer(
    add_completion=False,
    help="Parse C++ and generate MyST Markdown API documentation.",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """clangquill: parse C++ and generate MyST Markdown API documentation.

    A no-op callback so the single ``build`` command keeps its name as a
    required subcommand instead of being collapsed into the root invocation.
    """


@app.command("build")
def build(  # noqa: PLR0913
    inputs: Annotated[list[Path], typer.Argument(help="C++ headers/sources (paths or globs) to parse.")],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Directory for generated pages.")] = Path(
        "api",
    ),
    std: Annotated[str, typer.Option("--std", help="C++ standard, e.g. c++20.")] = "c++20",
    include_dir: Annotated[
        list[Path] | None,
        typer.Option("--include-dir", "-I", help="Add an include directory."),
    ] = None,
    define: Annotated[
        list[str] | None,
        typer.Option("--define", "-D", help="Add a preprocessor definition (NAME or NAME=value)."),
    ] = None,
    compile_commands: Annotated[
        Path | None,
        typer.Option("--compile-commands", help="Directory with a compile_commands.json."),
    ] = None,
    compile_arg: Annotated[
        list[str] | None,
        typer.Option("--compile-arg", help="Extra compiler argument (repeatable)."),
    ] = None,
    clang_resource_dir: Annotated[
        Path | None,
        typer.Option("--clang-resource-dir", help="Clang resource directory (-resource-dir)."),
    ] = None,
    template_dir: Annotated[
        list[Path] | None,
        typer.Option("--template-dir", help="Directory searched before bundled templates."),
    ] = None,
    cache_dir: Annotated[
        Path | None,
        typer.Option("--cache-dir", help="Keep the SQLite IR here instead of a temp file."),
    ] = None,
    include_undocumented: Annotated[  # noqa: FBT002 - typer renders this as a --flag/--no-flag option
        bool,
        typer.Option("--include-undocumented/--no-undocumented", help="Emit symbols lacking a doc comment."),
    ] = True,
    comment_parser: Annotated[
        str | None,
        typer.Option("--comment-parser", help="Comment-parser override (name or dotted path)."),
    ] = None,
    group_by: Annotated[
        str,
        typer.Option("--group-by", help=f"Page partitioning: {' | '.join(GROUP_BY_CHOICES)}."),
    ] = "symbol",
    toctree_maxdepth: Annotated[int, typer.Option("--toctree-maxdepth", help="Generated toctree depth.")] = 2,
) -> None:
    """Parse C++ inputs and generate MyST Markdown into the output directory."""
    config = Config(
        input=[str(p) for p in inputs],
        compile_commands=str(compile_commands) if compile_commands else None,
        compile_args=list(compile_arg or []),
        include_dirs=[str(p) for p in include_dir or []],
        std=std,
        defines=list(define or []),
        clang_resource_dir=str(clang_resource_dir) if clang_resource_dir else None,
        output_dir=str(output_dir),
        template_dirs=[str(p) for p in template_dir or []],
        cache_dir=str(cache_dir) if cache_dir else None,
        include_undocumented=include_undocumented,
        comment_parser=comment_parser,
        group_by=group_by,
        toctree_maxdepth=toctree_maxdepth,
    )
    try:
        config.validate()
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc

    try:
        result = run_pipeline(config, base_dir=Path.cwd())
    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if result.db_is_temporary:
        result.db_path.unlink(missing_ok=True)

    typer.echo(f"Parsed {result.symbol_count} symbol(s) from {result.file_count} file(s).")
    typer.echo(f"Wrote {len(result.pages)} page(s) to {result.output_dir}.")
    for diagnostic in result.diagnostics:
        typer.echo(f"  diagnostic: {diagnostic}", err=True)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
