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

from clangquill.comments import CommentModel, CommentParser, model_from_fields, resolve_override

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
class RawComment:
    """A row from the ``comments`` table: the verbatim text plus its parse."""

    symbol_usr: str
    raw_text: str
    format: str
    fields_json: str


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
        # as_uri() percent-encodes spaces and special characters so paths with
        # e.g. "?" or "#" produce a valid file URI on every platform.
        uri = f"{Path(path).resolve().as_uri()}?mode=ro"
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

    def raw_comment(self, usr: str) -> RawComment | None:
        """Return the raw ``comments`` row for ``usr``, or ``None``."""
        row = self._con.execute(
            "SELECT symbol_usr, raw_text, format, fields_json FROM comments WHERE symbol_usr = ?",
            (usr,),
        ).fetchone()
        if row is None:
            return None
        return RawComment(
            symbol_usr=row["symbol_usr"],
            raw_text=row["raw_text"],
            format=row["format"],
            fields_json=row["fields_json"] or "",
        )

    def comment(
        self,
        usr: str,
        *,
        parser: str | CommentParser | None = None,
    ) -> CommentModel | None:
        """Return the structured :class:`CommentModel` for symbol ``usr``.

        By default the model is reconstructed from the ``comment_fields`` rows
        produced by the C++ Doxygen parser. When a parser override is supplied
        (``parser`` argument, or the ``CLANGQUILL_COMMENT_PARSER`` environment
        variable) the symbol's raw comment text is re-parsed by that callable
        instead, so the comment format stays swappable from pure Python.
        Returns ``None`` for an undocumented symbol.
        """
        raw = self.raw_comment(usr)
        if raw is None:
            return None
        override = resolve_override(parser)
        if override is not None:
            return override(raw.raw_text)
        rows = self._con.execute(
            "SELECT name, arg, value FROM comment_fields WHERE symbol_usr = ? ORDER BY ordinal",
            (usr,),
        ).fetchall()
        return model_from_fields((r["name"], r["arg"], r["value"]) for r in rows)

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
