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


class AccessKind(IntEnum):
    """Mirror of ``clangquill::model::AccessKind`` (C++ access specifier)."""

    NONE = 0
    PUBLIC = 1
    PROTECTED = 2
    PRIVATE = 3


class RefKind(IntEnum):
    """Mirror of ``clangquill::model::RefKind`` (kind of cross-reference edge)."""

    BASE_CLASS = 0
    PARAM_TYPE = 1
    RETURN_TYPE = 2
    FIELD_TYPE = 3
    VARIABLE_TYPE = 4
    UNDERLYING_TYPE = 5
    ENUM_INTEGER_TYPE = 6


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
    access: AccessKind
    is_definition: bool
    is_documented: bool
    content_hash: str
    file_id: int | None
    line: int


@dataclass(frozen=True)
class Parameter:
    """A row from ``function_parameters``: one positional function parameter."""

    idx: int
    name: str
    type_repr: str
    default_value: str


@dataclass(frozen=True)
class TemplateParameter:
    """A row from ``template_parameters``: one template parameter of a symbol."""

    idx: int
    param_kind: int
    name: str
    type_repr: str
    default_repr: str


@dataclass(frozen=True)
class Enumerator:
    """A row from ``enumerators``: one constant of an enumeration."""

    usr: str
    name: str
    value: int
    value_is_signed: bool
    idx: int


@dataclass(frozen=True)
class Reference:
    """A row from ``references_``: a directed cross-reference edge.

    ``to_usr`` is empty when the target is a builtin, a template parameter, or a
    declaration absent from the parsed translation units; ``to_spelling`` always
    holds the written type text.
    """

    from_usr: str
    ref_kind: RefKind
    to_usr: str
    to_spelling: str
    is_resolved: bool
    access: AccessKind
    ordinal: int


@dataclass(frozen=True)
class SourceFile:
    """A row from the ``files`` table."""

    id: int
    path: str
    sha256: str
    size_bytes: int


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

    _SYMBOL_COLUMNS = (
        "usr, parent_usr, kind, spelling, qualified_name, display_name, "
        "signature, type_repr, access, is_definition, is_documented, "
        "content_hash, file_id, line"
    )

    # The interpolated column list below is the constant ``_SYMBOL_COLUMNS``,
    # never user input, so the ``S608`` SQL-injection warnings are spurious.
    def symbols(self, *, kind: SymbolKind | None = None) -> list[Symbol]:
        """Return all symbols, optionally filtered by ``kind``."""
        sql = f"SELECT {self._SYMBOL_COLUMNS} FROM symbols"  # noqa: S608
        params: tuple[object, ...] = ()
        if kind is not None:
            sql += " WHERE kind = ?"
            params = (int(kind),)
        sql += " ORDER BY qualified_name"
        return [self._to_symbol(row) for row in self._con.execute(sql, params)]

    def symbol(self, usr: str) -> Symbol | None:
        """Return the symbol with ``usr``, or ``None`` if it is unknown."""
        row = self._con.execute(
            f"SELECT {self._SYMBOL_COLUMNS} FROM symbols WHERE usr = ?",  # noqa: S608
            (usr,),
        ).fetchone()
        return self._to_symbol(row) if row is not None else None

    def roots(self) -> list[Symbol]:
        """Return top-level symbols (those with no enclosing parent)."""
        sql = (
            f"SELECT {self._SYMBOL_COLUMNS} FROM symbols "  # noqa: S608
            "WHERE parent_usr IS NULL OR parent_usr = '' "
            "ORDER BY kind, qualified_name"
        )
        return [self._to_symbol(row) for row in self._con.execute(sql)]

    def children(self, parent_usr: str) -> list[Symbol]:
        """Return the direct children of ``parent_usr`` in declaration-friendly order."""
        sql = (
            f"SELECT {self._SYMBOL_COLUMNS} FROM symbols "  # noqa: S608
            "WHERE parent_usr = ? ORDER BY kind, line, qualified_name"
        )
        return [self._to_symbol(row) for row in self._con.execute(sql, (parent_usr,))]

    def symbol_count(self) -> int:
        """Return the number of rows in the ``symbols`` table."""
        return int(self._con.execute("SELECT count(*) FROM symbols").fetchone()[0])

    def reference_count(self) -> int:
        """Return the number of rows in the ``references_`` table."""
        return int(self._con.execute("SELECT count(*) FROM references_").fetchone()[0])

    def file_count(self) -> int:
        """Return the number of rows in the ``files`` table."""
        return int(self._con.execute("SELECT count(*) FROM files").fetchone()[0])

    def parameters(self, function_usr: str) -> list[Parameter]:
        """Return the parameters of a function/method in positional order."""
        rows = self._con.execute(
            "SELECT idx, name, type_repr, default_value FROM function_parameters WHERE function_usr = ? ORDER BY idx",
            (function_usr,),
        ).fetchall()
        return [Parameter(r["idx"], r["name"], r["type_repr"], r["default_value"]) for r in rows]

    def template_parameters(self, owner_usr: str) -> list[TemplateParameter]:
        """Return the template parameters of ``owner_usr`` in positional order."""
        rows = self._con.execute(
            "SELECT idx, param_kind, name, type_repr, default_repr "
            "FROM template_parameters WHERE owner_usr = ? ORDER BY idx",
            (owner_usr,),
        ).fetchall()
        return [
            TemplateParameter(r["idx"], r["param_kind"], r["name"], r["type_repr"], r["default_repr"]) for r in rows
        ]

    def enumerators(self, enum_usr: str) -> list[Enumerator]:
        """Return the enumerators of an enum in declaration order."""
        rows = self._con.execute(
            "SELECT usr, name, value, value_is_signed, idx FROM enumerators WHERE enum_usr = ? ORDER BY idx",
            (enum_usr,),
        ).fetchall()
        return [Enumerator(r["usr"], r["name"], r["value"], bool(r["value_is_signed"]), r["idx"]) for r in rows]

    def references(
        self,
        from_usr: str,
        *,
        kind: RefKind | None = None,
    ) -> list[Reference]:
        """Return outgoing cross-references of ``from_usr`` in stable order."""
        sql = (
            "SELECT from_usr, ref_kind, to_usr, to_spelling, is_resolved, access, ordinal "
            "FROM references_ WHERE from_usr = ?"
        )
        params: tuple[object, ...] = (from_usr,)
        if kind is not None:
            sql += " AND ref_kind = ?"
            params = (from_usr, int(kind))
        sql += " ORDER BY ref_kind, ordinal"
        return [self._to_reference(row) for row in self._con.execute(sql, params)]

    def bases(self, usr: str) -> list[Reference]:
        """Return the base-class references of ``usr`` in declaration order."""
        return self.references(usr, kind=RefKind.BASE_CLASS)

    def files(self) -> list[SourceFile]:
        """Return all parsed source files ordered by path."""
        rows = self._con.execute(
            "SELECT id, path, sha256, size_bytes FROM files ORDER BY path",
        ).fetchall()
        return [SourceFile(r["id"], r["path"], r["sha256"], r["size_bytes"]) for r in rows]

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
            access=AccessKind(row["access"]),
            is_definition=bool(row["is_definition"]),
            is_documented=bool(row["is_documented"]),
            content_hash=row["content_hash"],
            file_id=row["file_id"],
            line=row["line"],
        )

    @staticmethod
    def _to_reference(row: sqlite3.Row) -> Reference:
        return Reference(
            from_usr=row["from_usr"],
            ref_kind=RefKind(row["ref_kind"]),
            to_usr=row["to_usr"] or "",
            to_spelling=row["to_spelling"],
            is_resolved=bool(row["is_resolved"]),
            access=AccessKind(row["access"]),
            ordinal=row["ordinal"],
        )
