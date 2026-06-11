"""End-to-end test of the C++ parse -> SQLite -> Python read boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from clangquill import _core
from clangquill.store import Store, SymbolKind

if TYPE_CHECKING:
    from pathlib import Path

FIXTURE = """
/// A documented namespace.
namespace demo {
/// A documented widget.
struct Widget {
  /// the width
  int width;
};
int undocumented_free_function(int x);
}
"""


@pytest.mark.skipif(not _core.have_libclang(), reason="core built without libclang")
def test_parse_to_sqlite_round_trip(tmp_path: Path) -> None:
    header = tmp_path / "demo.hpp"
    header.write_text(FIXTURE)
    db = tmp_path / "out.sqlite"

    result = _core.parse_to_sqlite([str(header)], str(db), _core.ParseOptions())

    assert result.symbol_count > 0
    assert result.file_count == 1
    assert not result.diagnostics

    with Store.open(db) as store:
        assert store.meta("schema_version") == str(_core.SCHEMA_VERSION)

        by_name = {s.qualified_name: s for s in store.symbols()}
        assert "demo" in by_name
        assert by_name["demo"].kind == SymbolKind.NAMESPACE

        widget = by_name["demo::Widget"]
        assert widget.kind == SymbolKind.STRUCT
        assert widget.is_documented

        undoc = by_name["demo::undocumented_free_function"]
        assert not undoc.is_documented

        # Every symbol gets a content hash for later incremental caching.
        assert all(s.content_hash for s in store.symbols())


@pytest.mark.skipif(not _core.have_libclang(), reason="core built without libclang")
@pytest.mark.parametrize("jobs", [1, 2, 4])
def test_parse_to_sqlite_parallel_matches_serial(tmp_path: Path, jobs: int) -> None:
    # A handful of independent headers so the work fans out across threads.
    headers = []
    for i in range(6):
        header = tmp_path / f"h{i}.hpp"
        header.write_text(
            f"/// widget {i}\nnamespace n{i} {{ struct W{i} {{ int field{i}; }}; int fn{i}(int a); }}\n",
        )
        headers.append(str(header))

    def parse(db_name: str, n_jobs: int) -> tuple[int, int, int, list[tuple]]:
        opts = _core.ParseOptions()
        opts.jobs = n_jobs
        db = tmp_path / db_name
        result = _core.parse_to_sqlite(headers, str(db), opts)
        with Store.open(db) as store:
            rows = sorted((s.usr, s.qualified_name, s.kind) for s in store.symbols())
        return result.symbol_count, result.reference_count, result.file_count, rows

    serial = parse("serial.sqlite", 1)
    parallel = parse(f"parallel{jobs}.sqlite", jobs)

    # Parallelism must not change the extracted IR — same counts, same symbols.
    assert parallel == serial


@pytest.mark.skipif(not _core.have_libclang(), reason="core built without libclang")
def test_parse_to_sqlite_reports_per_tu_files(tmp_path: Path) -> None:
    detail = tmp_path / "detail.hpp"
    detail.write_text("#pragma once\nusing Width = int;\n")
    a = tmp_path / "a.hpp"
    a.write_text('#include "detail.hpp"\n/// ns a\nnamespace a { /// f\nWidth f(); }\n')
    b = tmp_path / "b.hpp"
    b.write_text("/// ns b\nnamespace b { /// g\nint g(); }\n")
    db = tmp_path / "out.sqlite"

    result = _core.parse_to_sqlite([str(a), str(b)], str(db), _core.ParseOptions())

    deps = {tu.input: set(tu.files) for tu in result.translation_units}
    # Each input reports its own file set: a pulls in detail.hpp, b does not.
    assert deps[str(a)] == {str(a), str(detail)}
    assert deps[str(b)] == {str(b)}


@pytest.mark.skipif(not _core.have_libclang(), reason="core built without libclang")
def test_parse_tu_to_sqlite_replaces_only_that_unit(tmp_path: Path) -> None:
    a = tmp_path / "a.hpp"
    a.write_text("/// ns a\nnamespace a { /// f\nint f(); }\n")
    b = tmp_path / "b.hpp"
    b.write_text("/// ns b\nnamespace b { /// g\nint g(); }\n")
    db = tmp_path / "out.sqlite"
    _core.parse_to_sqlite([str(a), str(b)], str(db), _core.ParseOptions())

    # Edit a.hpp: drop f, add h. Re-parse only that translation unit.
    a.write_text("/// ns a\nnamespace a { /// h\nint h(); }\n")
    result = _core.parse_tu_to_sqlite(str(a), str(db), _core.ParseOptions())
    assert [tu.input for tu in result.translation_units] == [str(a)]

    with Store.open(db) as store:
        names = {s.qualified_name for s in store.symbols()}
    # a's removed symbol is gone, its new symbol is present, and b is untouched.
    assert "a::f" not in names
    assert "a::h" in names
    assert "b::g" in names


@pytest.mark.skipif(not _core.have_libclang(), reason="core built without libclang")
def test_parse_tu_failure_does_not_wipe_existing_rows(tmp_path: Path) -> None:
    a = tmp_path / "a.hpp"
    a.write_text("/// ns a\nnamespace a { /// f\nint f(); }\n")
    db = tmp_path / "out.sqlite"
    _core.parse_to_sqlite([str(a)], str(db), _core.ParseOptions())

    # A hard parse failure (no translation unit at all) must raise rather than
    # delete a.hpp's rows and replace them with an empty re-parse.
    with pytest.raises(RuntimeError, match="failed to parse"):
        _core.parse_tu_to_sqlite(str(tmp_path / "missing.hpp"), str(db), _core.ParseOptions())

    with Store.open(db) as store:
        assert {s.qualified_name for s in store.symbols()} >= {"a", "a::f"}


def test_schema_version_exposed() -> None:
    assert isinstance(_core.SCHEMA_VERSION, int)
    assert _core.SCHEMA_VERSION >= 1
