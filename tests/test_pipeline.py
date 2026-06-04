"""Tests for the parse -> SQLite -> MyST pipeline and the CLI that drives it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from clangquill import _core, cli, pipeline
from clangquill.config import Config
from clangquill.pipeline import MANIFEST_NAME, build

if TYPE_CHECKING:
    from pathlib import Path

requires_libclang = pytest.mark.skipif(
    not _core.have_libclang(),
    reason="core built without libclang",
)

FIXTURE = """
/// A documented namespace.
namespace demo {
/// A documented widget.
struct Widget {
  /// the width
  int width;
};
/// A documented free function.
int twice(int x);
}
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "demo.hpp").write_text(FIXTURE)
    return tmp_path


@requires_libclang
def test_build_generates_pages_and_index(project: Path) -> None:
    config = Config(input=["demo.hpp"], output_dir="api")
    result = build(config, base_dir=project)

    assert result.symbol_count > 0
    assert result.pages == ["demo"]
    api = project / "api"
    assert (api / "demo.md").is_file()
    assert (api / "index.md").read_text().startswith("# API Reference")
    assert (api / MANIFEST_NAME).is_file()
    # The throwaway IR is reported as temporary so the caller can clean it up.
    assert result.db_is_temporary


@requires_libclang
def test_build_caches_db_when_cache_dir_set(project: Path) -> None:
    config = Config(input=["demo.hpp"], cache_dir=".cache")
    result = build(config, base_dir=project)
    assert not result.db_is_temporary
    assert result.db_path.is_file()
    assert result.db_path.parent == (project / ".cache").resolve()


def _mtimes(api: Path) -> dict[str, float]:
    return {p.name: p.stat().st_mtime_ns for p in api.glob("*.md")}


@requires_libclang
def test_incremental_unchanged_build_regenerates_nothing(project: Path) -> None:
    config = Config(input=["demo.hpp"], output_dir="api", cache_dir=".cache")
    first = build(config, base_dir=project)
    assert first.parsed
    assert first.pages_written  # the first run writes every page

    api = project / "api"
    before = _mtimes(api)
    second = build(config, base_dir=project)

    # Nothing changed: the parse is served from cache and no page is rewritten.
    assert not second.parsed
    assert second.pages_written == []
    assert second.pages_deleted == []
    assert _mtimes(api) == before


@requires_libclang
def test_incremental_touch_header_regenerates_only_affected(project: Path) -> None:
    (project / "alpha.hpp").write_text("/// alpha ns\nnamespace alpha { /// f\nint f(); }\n")
    (project / "beta.hpp").write_text("/// beta ns\nnamespace beta { /// g\nint g(); }\n")
    config = Config(input=["alpha.hpp", "beta.hpp"], output_dir="api", cache_dir=".cache")
    build(config, base_dir=project)

    api = project / "api"
    before = _mtimes(api)

    # Edit only alpha.hpp's documentation; beta and the toctree are untouched.
    (project / "alpha.hpp").write_text("/// alpha ns edited\nnamespace alpha { /// f\nint f(); }\n")
    result = build(config, base_dir=project)

    assert result.parsed
    assert result.pages_written == ["alpha.md"]
    assert result.pages_deleted == []
    after = _mtimes(api)
    assert after["alpha.md"] != before["alpha.md"]
    assert after["beta.md"] == before["beta.md"]
    assert after["index.md"] == before["index.md"]


@requires_libclang
def test_incremental_deletes_pages_for_removed_symbols(project: Path) -> None:
    header = project / "two.hpp"
    header.write_text("/// alpha\nnamespace alpha { /// f\nint f(); }\n/// beta\nnamespace beta { /// g\nint g(); }\n")
    config = Config(input=["two.hpp"], output_dir="api", cache_dir=".cache")
    build(config, base_dir=project)
    api = project / "api"
    assert (api / "alpha.md").is_file()
    assert (api / "beta.md").is_file()

    # Drop the beta namespace entirely; its page must be deleted.
    header.write_text("/// alpha\nnamespace alpha { /// f\nint f(); }\n")
    result = build(config, base_dir=project)

    assert result.pages_deleted == ["beta.md"]
    assert not (api / "beta.md").exists()
    assert (api / "alpha.md").is_file()
    # The toctree shrank, so the index is rewritten; alpha's page did not change.
    assert "index.md" in result.pages_written
    assert "alpha.md" not in result.pages_written


@requires_libclang
def test_incremental_reparses_when_included_header_changes(project: Path) -> None:
    (project / "detail.hpp").write_text("#pragma once\nusing Width = int;\n")
    (project / "main.hpp").write_text('#include "detail.hpp"\n/// uses detail\nnamespace m { /// w\nWidth w(); }\n')
    config = Config(input=["main.hpp"], output_dir="api", cache_dir=".cache")

    first = build(config, base_dir=project)
    assert first.parsed
    # The transitive include is tracked, so it counts as a parsed source file.
    assert first.file_count >= 2

    # Rebuild with nothing touched -> cache hit, no parse.
    assert not build(config, base_dir=project).parsed

    # Touching the *included* header invalidates the cached parse.
    (project / "detail.hpp").write_text("#pragma once\nusing Width = unsigned;\n")
    assert build(config, base_dir=project).parsed


@requires_libclang
def test_build_prunes_stale_pages(project: Path) -> None:
    # First build with one input produces demo.md.
    build(Config(input=["demo.hpp"], output_dir="api"), base_dir=project)
    api = project / "api"
    assert (api / "demo.md").is_file()

    # Replace the input with a differently-named namespace and rebuild; the old
    # page must be pruned via the manifest while a hand-written file survives.
    (api / "handwritten.md").write_text("keep me\n")
    (project / "demo.hpp").write_text("/// other\nnamespace other { /// f\nint f(); }\n")
    build(Config(input=["demo.hpp"], output_dir="api"), base_dir=project)

    assert (api / "other.md").is_file()
    assert not (api / "demo.md").exists()
    assert (api / "handwritten.md").is_file()


@requires_libclang
def test_build_missing_input_raises(project: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build(Config(input=["nope.hpp"]), base_dir=project)


@requires_libclang
def test_build_skips_directories_matched_by_glob(project: Path) -> None:
    # A glob like ``*`` matches the subdirectory alongside the header; only the
    # header should be parsed, and the directory must not reach libclang.
    (project / "sub").mkdir()
    result = build(Config(input=["*"], output_dir="api"), base_dir=project)
    assert result.file_count == 1
    assert not result.diagnostics


@requires_libclang
def test_temp_db_cleaned_up_when_generation_fails(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pin the temp IR to a known path, then make generation fail; the finally
    # block must remove the throwaway database rather than leak it.
    db = tmp_path / "scratch.sqlite"
    monkeypatch.setattr(pipeline, "_new_temp_db", lambda *_, **__: db)

    # An override pointing at a missing template makes generate() raise.
    config = Config(input=["demo.hpp"], templates={"namespace": "missing_template"})
    with pytest.raises(Exception, match="missing_template"):
        build(config, base_dir=project)
    assert not db.exists()


@requires_libclang
def test_cli_build_from_cwd(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(project)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["build", "demo.hpp", "-o", "out"])
    assert result.exit_code == 0, result.output
    assert (project / "out" / "demo.md").is_file()
    assert "Wrote 1 page(s)" in result.output


def test_cli_build_missing_input_exits_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A no-match input fails with a clean message, not a raw traceback.
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["build", "absent.hpp"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Error:" in result.output
