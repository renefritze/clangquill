"""Tests for the parse -> SQLite -> MyST pipeline and the CLI that drives it."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from clangquill import _core, cli, pipeline
from clangquill.config import Config
from clangquill.pipeline import MANIFEST_NAME, build

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


M7_FIXTURE = Path(__file__).parent / "cpp" / "fixtures" / "m7.hpp"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "demo.hpp").write_text(FIXTURE)
    return tmp_path


@requires_libclang
def test_build_renders_all_m7_kinds(tmp_path: Path) -> None:
    (tmp_path / "m7.hpp").write_text(M7_FIXTURE.read_text())
    result = build(Config(input=["m7.hpp"], output_dir="api"), base_dir=tmp_path)
    assert "group_math" in result.pages

    api = tmp_path / "api"
    ns = (api / "m7.md").read_text()
    # Concept and class template render with their `template<...>` heads.
    assert "{cpp:concept} template<typename T> m7::Addable" in ns
    assert "{cpp:class} template<typename T, int N = 4> m7::Buffer" in ns
    assert "{cpp:function} template <typename T> T m7::max_value" in ns
    # Friends and operators.
    assert "**Friends**" in ns
    assert "{cpp:function} int m7::Vec::operator[]" in ns
    # `\ingroup` bookkeeping never leaks into the rendered prose.
    assert "\nmath\n" not in ns

    # Macros become C-domain objects on their own pages, with attached docs.
    macro = (api / "CQ_MAX.md").read_text()
    assert "{c:macro} CQ_MAX(a, b)" in macro
    assert "function-like macro" in macro

    # The group page lists its `\ingroup` members.
    grp = (api / "group_math.md").read_text()
    assert grp.startswith("# Math utilities")
    assert "{cpp:any}`m7::add`" in grp


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
def test_build_path_base_reroots_file_headings(project: Path) -> None:
    # With group_by="file" the heading renders the source path; path_base="."
    # re-roots it against the project so the absolute build-machine path the IR
    # stores never leaks into the output.
    config = Config(input=["demo.hpp"], output_dir="api", group_by="file", path_base=".")
    build(config, base_dir=project)

    page = (project / "api" / "demo_hpp.md").read_text()
    assert page.startswith("# File `demo.hpp`")
    assert str(project.resolve()) not in page


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
def test_incremental_noop_skips_rendering(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config(input=["demo.hpp"], output_dir="api", cache_dir=".cache")
    first = build(config, base_dir=project)
    assert first.parsed

    # A noop rebuild must not render at all: the second run short-circuits before
    # _rendered_files (the Jinja pass) is ever reached.
    def boom(*_args: object, **_kwargs: object) -> list[tuple[str, str]]:
        msg = "rendering should be skipped on a noop build"
        raise AssertionError(msg)

    monkeypatch.setattr(pipeline, "_rendered_files", boom)

    second = build(config, base_dir=project)
    assert not second.parsed
    assert second.pages_written == []
    assert second.pages_deleted == []
    # Counts and page list are replayed faithfully from the cache.
    assert second.pages == first.pages
    assert second.symbol_count == first.symbol_count
    assert second.reference_count == first.reference_count
    assert second.file_count == first.file_count


@requires_libclang
def test_incremental_render_config_change_rerenders_without_reparse(project: Path) -> None:
    config = Config(input=["demo.hpp"], output_dir="api", cache_dir=".cache")
    build(config, base_dir=project)

    # Changing a render-only option leaves the parse cached but must still
    # re-render: the noop skip is keyed on the render fingerprint too.
    deeper = Config(input=["demo.hpp"], output_dir="api", cache_dir=".cache", toctree_maxdepth=4)
    result = build(deeper, base_dir=project)
    assert not result.parsed
    assert "index.md" in result.pages_written
    assert ":maxdepth: 4" in (project / "api" / "index.md").read_text()


@requires_libclang
def test_incremental_template_edit_busts_noop_skip(project: Path) -> None:
    templates = project / "templates"
    templates.mkdir()
    override = templates / "namespace.md.jinja"
    override.write_text("# OVERRIDE {{ symbol.qualified_name }}\n")
    config = Config(
        input=["demo.hpp"],
        output_dir="api",
        cache_dir=".cache",
        template_dirs=["templates"],
    )
    first = build(config, base_dir=project)
    assert "OVERRIDE demo" in (project / "api" / "demo.md").read_text()
    assert first.parsed

    # Editing the override template (IR untouched) must re-render rather than
    # serve the stale page from the noop cache.
    override.write_text("# CHANGED {{ symbol.qualified_name }}\n")
    result = build(config, base_dir=project)
    assert not result.parsed
    assert "demo.md" in result.pages_written
    assert "CHANGED demo" in (project / "api" / "demo.md").read_text()


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


def test_parse_fingerprint_tracks_compile_commands_file(tmp_path: Path) -> None:
    # ``compile_commands`` is a directory; the fingerprint must follow the JSON
    # file inside it so edits to the compile DB invalidate the cached parse.
    cc_dir = tmp_path / "build"
    cc_dir.mkdir()
    db = cc_dir / "compile_commands.json"
    db.write_text("[]", encoding="utf-8")
    config = Config(input=["a.hpp"], compile_commands="build")

    before = pipeline._parse_fingerprint(config, tmp_path, ["a.hpp"])  # noqa: SLF001
    db.write_text('[{"directory": ".", "command": "c++ a.cpp", "file": "a.cpp"}]', encoding="utf-8")
    after = pipeline._parse_fingerprint(config, tmp_path, ["a.hpp"])  # noqa: SLF001
    assert before != after


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
