"""Shared pytest fixtures.

The generator reads the SQLite IR, so its tests can run against a database
built directly in Python — no libclang needed. To stay faithful to the real
schema, the DDL is lifted verbatim from the C++ ``schema.hpp`` rather than
duplicated here, then a small but representative set of symbols is inserted.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_SCHEMA_HPP = Path(__file__).resolve().parents[1] / "src" / "cpp" / "store" / "schema.hpp"


def _schema_ddl() -> str:
    """Return the IR schema DDL extracted from the C++ source of truth."""
    text = _SCHEMA_HPP.read_text(encoding="utf-8")
    return text.split('R"SQL(', 1)[1].rsplit(')SQL"', 1)[0]


def _build_fixture_db(path: Path) -> None:
    """Populate ``path`` with a small, documented ``geo`` namespace.

    Covers the cases the generator must handle: a base class and a derived
    class, a const method, a field, a free function with parameters and a
    ``@see`` cross-reference, an enum with enumerators, a typedef, a variable,
    and a deliberately undocumented function.
    """
    con = sqlite3.connect(path)
    try:
        con.executescript(_schema_ddl())
        con.execute("INSERT INTO meta(key, value) VALUES('schema_version', '1')")
        con.execute("INSERT INTO files(id, path, sha256, size_bytes) VALUES(1, 'geo.hpp', 'deadbeef', 512)")

        def sym(  # noqa: PLR0913
            usr: str,
            parent: str,
            kind: int,
            spelling: str,
            qname: str,
            *,
            signature: str = "",
            type_repr: str = "",
            access: int = 0,
            documented: bool = True,
            line: int = 0,
        ) -> None:
            con.execute(
                "INSERT INTO symbols(usr, parent_usr, kind, spelling, qualified_name, "
                "display_name, signature, type_repr, access, is_definition, "
                "is_documented, content_hash, file_id, line) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 1, ?)",
                (
                    usr,
                    parent,
                    kind,
                    spelling,
                    qname,
                    qname,
                    signature,
                    type_repr,
                    access,
                    int(documented),
                    "hash-" + usr,
                    line,
                ),
            )

        ns = "c:@N@geo"
        shape = "c:@N@geo@S@Shape"
        circle = "c:@N@geo@S@Circle"
        area = "c:@N@geo@S@Circle@F@area"
        radius = "c:@N@geo@S@Circle@FI@radius"
        scale = "c:@N@geo@F@scale"
        color = "c:@N@geo@E@Color"
        distance = "c:@N@geo@T@Distance"
        pi = "c:@N@geo@pi"
        mystery = "c:@N@geo@F@mystery"

        sym(ns, "", 1, "geo", "geo", line=1)
        sym(shape, ns, 2, "Shape", "geo::Shape", line=3)
        sym(circle, ns, 2, "Circle", "geo::Circle", line=10)
        sym(
            area,
            circle,
            6,
            "area",
            "geo::Circle::area",
            signature="double area() const",
            type_repr="double () const",
            access=1,
            line=14,
        )
        sym(radius, circle, 9, "radius", "geo::Circle::radius", type_repr="double", access=2, line=18)
        sym(
            scale,
            ns,
            5,
            "scale",
            "geo::scale",
            signature="Circle scale(const Circle &c, double factor)",
            type_repr="Circle (const Circle &, double)",
            line=22,
        )
        sym(color, ns, 11, "Color", "geo::Color", line=30)
        sym(distance, ns, 13, "Distance", "geo::Distance", type_repr="double", line=36)
        sym(pi, ns, 10, "pi", "geo::pi", type_repr="const double", line=38)
        sym(
            mystery,
            ns,
            5,
            "mystery",
            "geo::mystery",
            signature="void mystery()",
            type_repr="void ()",
            documented=False,
            line=44,
        )

        con.executemany(
            "INSERT INTO enumerators(usr, enum_usr, name, value, value_is_signed, idx) VALUES(?, ?, ?, ?, 1, ?)",
            [
                (color + "@Red", color, "Red", 0, 0),
                (color + "@Green", color, "Green", 1, 1),
                (color + "@Blue", color, "Blue", 2, 2),
            ],
        )

        # Circle : public Shape  (a resolved base-class reference)
        con.execute(
            "INSERT INTO references_(from_usr, ref_kind, to_usr, to_spelling, is_resolved, access, ordinal) "
            "VALUES(?, 0, ?, 'Shape', 1, 1, 0)",
            (circle, shape),
        )
        # typedef Distance -> double  (an unresolved underlying-type reference)
        con.execute(
            "INSERT INTO references_(from_usr, ref_kind, to_usr, to_spelling, is_resolved, access, ordinal) "
            "VALUES(?, 5, '', 'double', 0, 0, 0)",
            (distance,),
        )

        def comment(usr: str, fields: list[tuple[str, str, str]]) -> None:
            con.execute(
                "INSERT INTO comments(symbol_usr, raw_text, format, fields_json) VALUES(?, ?, 'doxygen', '')",
                (usr, "/// generated fixture comment"),
            )
            con.executemany(
                "INSERT INTO comment_fields(symbol_usr, name, arg, value, ordinal) VALUES(?, ?, ?, ?, ?)",
                [(usr, n, a, v, i) for i, (n, a, v) in enumerate(fields)],
            )

        comment(ns, [("brief", "", "Geometry primitives.")])
        comment(shape, [("brief", "", "Abstract base for shapes.")])
        comment(
            circle,
            [
                ("brief", "", "A circle."),
                ("detail", "", "Defined by its radius."),
                ("note", "", "The radius must be positive."),
            ],
        )
        comment(area, [("brief", "", "Compute the area."), ("returns", "", "the area in square units.")])
        comment(radius, [("brief", "", "The radius of the circle.")])
        comment(
            scale,
            [
                ("brief", "", "Return a scaled copy of a circle."),
                ("param", "c", "the circle to scale"),
                ("param", "factor", "the scale factor"),
                ("returns", "", "a new, scaled circle."),
                ("see", "", "geo::Circle"),
            ],
        )
        comment(color, [("brief", "", "A named drawing color.")])
        comment(distance, [("brief", "", "A distance in meters.")])
        comment(pi, [("brief", "", "The circle constant.")])
        con.commit()
    finally:
        con.close()


def _build_m7_db(path: Path) -> None:
    r"""Populate ``path`` with the M7 kinds.

    Covers a class template (with a defaulted non-type parameter), a concept,
    object- and function-like macros, a struct with documented and undocumented
    friends, and a ``\defgroup`` group with members.
    """
    con = sqlite3.connect(path)
    try:
        con.executescript(_schema_ddl())
        con.execute("INSERT INTO meta(key, value) VALUES('schema_version', '2')")
        con.execute("INSERT INTO files(id, path, sha256, size_bytes) VALUES(1, 'm7.hpp', 'cafef00d', 256)")

        def sym(  # noqa: PLR0913
            usr: str,
            parent: str,
            kind: int,
            spelling: str,
            qname: str,
            *,
            signature: str = "",
            type_repr: str = "",
        ) -> None:
            con.execute(
                "INSERT INTO symbols(usr, parent_usr, kind, spelling, qualified_name, "
                "display_name, signature, type_repr, access, is_definition, "
                "is_documented, content_hash, file_id, line) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, 1, 1, ?, 1, 0)",
                (usr, parent, kind, spelling, qname, qname, signature, type_repr, "hash-" + usr),
            )

        ns = "c:@N@nn"
        box = "c:@N@nn@ST>2#T#NI@Box"
        addable = "c:@N@nn@CT@Addable"
        pi = "c:@macro@PI"
        maxm = "c:@macro@MAXM"
        pt = "c:@N@nn@S@Pt"
        helper = "c:@N@nn@F@helper"

        sym(ns, "", 1, "nn", "nn")
        sym(box, ns, 16, "Box", "nn::Box", signature="template<typename T, int N = 4>")
        sym(addable, ns, 17, "Addable", "nn::Addable", signature="template<typename T>")
        sym(pi, "", 18, "PI", "PI", signature="PI")
        sym(maxm, "", 18, "MAXM", "MAXM", signature="MAXM(a, b)")
        sym(pt, ns, 3, "Pt", "nn::Pt")
        sym(helper, ns, 5, "helper", "nn::helper", signature="void helper()", type_repr="void ()")

        # Friends: one points at a documented symbol (nn::helper), one is an
        # out-of-TU entity that must degrade to inline code.
        con.executemany(
            "INSERT INTO references_(from_usr, ref_kind, to_usr, to_spelling, is_resolved, access, ordinal) VALUES(?, 7, ?, ?, ?, 0, ?)",
            [
                (pt, helper, "nn::helper", 1, 0),
                (pt, "", "Outsider", 0, 1),
            ],
        )

        con.executemany(
            "INSERT INTO template_parameters(owner_usr, idx, param_kind, name, type_repr, default_repr) VALUES(?, ?, ?, ?, ?, ?)",
            [
                (box, 0, 0, "T", "", ""),
                (box, 1, 1, "N", "int", "4"),
                (addable, 0, 0, "T", "", ""),
            ],
        )

        con.execute(
            "INSERT INTO groups(id, title, brief, detail, parent_group_id) VALUES('grp', 'Grouped API', 'A documented group.', '', NULL)",
        )
        con.executemany(
            "INSERT INTO group_members(group_id, member_usr, ordinal) VALUES('grp', ?, ?)",
            [(box, 0), (helper, 1)],
        )

        for usr, brief in (
            (ns, "A namespace."),
            (box, "A box."),
            (addable, "Addable types."),
            (pi, "Pi."),
            (maxm, "Max macro."),
            (pt, "A point."),
            (helper, "A helper."),
        ):
            con.execute(
                "INSERT INTO comments(symbol_usr, raw_text, format, fields_json) VALUES(?, '/// fixture', 'doxygen', '')",
                (usr,),
            )
            con.execute(
                "INSERT INTO comment_fields(symbol_usr, name, arg, value, ordinal) VALUES(?, 'brief', '', ?, 0)",
                (usr, brief),
            )
        con.commit()
    finally:
        con.close()


@pytest.fixture
def fixture_db(tmp_path: Path) -> Path:
    """Return the path to a freshly built fixture IR database."""
    path = tmp_path / "geo.sqlite"
    _build_fixture_db(path)
    return path


@pytest.fixture
def m7_db(tmp_path: Path) -> Path:
    """Return the path to a fixture IR database exercising the M7 kinds."""
    path = tmp_path / "m7.sqlite"
    _build_m7_db(path)
    return path
