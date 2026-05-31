"""Read-only access to the SQLite intermediate artifact produced by the core.

The C++ core writes the IR; Python reads it via the standard library so queries
can evolve without recompiling. This module is a thin, typed convenience layer
over :mod:`sqlite3`.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class SymbolKind(IntEnum):
    """Mirror of ``clangquill::model::SymbolKind`` (keep in sync with the C++)."""

    UNKNOWN = 0
    NAMESPACE = 1
    CLASS = 2
    STRUCT = 3
    UNION = 4
    FUNCTION = 5
    METHOD = 6
    CONSTRUCTOR = 7
    DESTRUCTOR = 8
    FIELD = 9
    VARIABLE = 10
    ENUM = 11
    ENUMERATOR = 12
    TYPEDEF = 13
    TYPE_ALIAS = 14
    FUNCTION_TEMPLATE = 15
    CLASS_TEMPLATE = 16


@dataclass(frozen=True)
class Symbol:
    """A single row from the ``symbols`` table."""

    usr: str
    parent_usr: str
    kind: SymbolKind
    spelling: str
    qualified_name: str
    display_name: str
    signature: str
    type_repr: str
    is_definition: bool
    is_documented: bool
    content_hash: str


class Store:
    """A read-only view over a clangquill SQLite database."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Wrap an open sqlite3 connection (use :meth:`open` instead)."""
        self._con = connection
        self._con.row_factory = sqlite3.Row

    @classmethod
    @contextmanager
    def open(cls, path: str | Path) -> Iterator[Store]:
        """Open ``path`` read-only and yield a :class:`Store`."""
        uri = f"file:{Path(path)}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        try:
            yield cls(con)
        finally:
            con.close()

    def meta(self, key: str) -> str | None:
        """Return a value from the ``meta`` table, or ``None``."""
        row = self._con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def symbols(self, *, kind: SymbolKind | None = None) -> list[Symbol]:
        """Return all symbols, optionally filtered by ``kind``."""
        sql = (
            "SELECT usr, parent_usr, kind, spelling, qualified_name, "
            "display_name, signature, type_repr, is_definition, "
            "is_documented, content_hash FROM symbols"
        )
        params: tuple[object, ...] = ()
        if kind is not None:
            sql += " WHERE kind = ?"
            params = (int(kind),)
        sql += " ORDER BY qualified_name"
        return [self._to_symbol(row) for row in self._con.execute(sql, params)]

    def symbol_count(self) -> int:
        """Return the number of rows in the ``symbols`` table."""
        return int(self._con.execute("SELECT count(*) FROM symbols").fetchone()[0])

    @staticmethod
    def _to_symbol(row: sqlite3.Row) -> Symbol:
        return Symbol(
            usr=row["usr"],
            parent_usr=row["parent_usr"] or "",
            kind=SymbolKind(row["kind"]),
            spelling=row["spelling"],
            qualified_name=row["qualified_name"],
            display_name=row["display_name"],
            signature=row["signature"],
            type_repr=row["type_repr"],
            is_definition=bool(row["is_definition"]),
            is_documented=bool(row["is_documented"]),
            content_hash=row["content_hash"],
        )
