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


def test_schema_version_exposed() -> None:
    assert isinstance(_core.SCHEMA_VERSION, int)
    assert _core.SCHEMA_VERSION >= 1
