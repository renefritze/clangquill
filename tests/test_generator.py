"""Tests for the MyST generator: golden output, overrides, xrefs, Sphinx build."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from clangquill.generator import Generator
from clangquill.store import Reference, RefKind, Store, Symbol

if TYPE_CHECKING:
    from collections.abc import Iterator

GOLDEN_DIR = Path(__file__).parent / "golden"
REGEN_ENV = "CLANGQUILL_REGEN_GOLDENS"


def _assert_golden(name: str, text: str) -> None:
    """Compare ``text`` to ``golden/<name>``; regenerate it when REGEN is set."""
    path = GOLDEN_DIR / name
    if os.environ.get(REGEN_ENV):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    expected = path.read_text(encoding="utf-8")
    assert text == expected


@pytest.fixture
def store(fixture_db: Path) -> Iterator[Store]:
    with Store.open(fixture_db) as opened:
        yield opened


@pytest.fixture
def gen(store: Store) -> Generator:
    return Generator(store)


def _symbol(store: Store, qualified_name: str) -> Symbol:
    sym = next((s for s in store.symbols() if s.qualified_name == qualified_name), None)
    assert sym is not None, f"missing fixture symbol {qualified_name!r}"
    return sym


def test_namespace_golden(gen: Generator, store: Store) -> None:
    rendered = gen.render_symbol(_symbol(store, "geo"), level=1)
    _assert_golden("geo.md", rendered)


def test_generate_writes_pages_and_index(gen: Generator, tmp_path: Path) -> None:
    out = tmp_path / "api"
    pages = gen.generate(out)

    assert pages == ["geo"]
    assert (out / "geo.md").is_file()
    _assert_golden("index.md", (out / "index.md").read_text())
    # The generated page is the same content the per-symbol render produces.
    assert (out / "geo.md").read_text().startswith("# Namespace `geo`")


def test_emitted_directives_cover_each_kind(gen: Generator, store: Store) -> None:
    rendered = gen.render_symbol(_symbol(store, "geo"), level=1)
    for directive in ("{cpp:class}", "{cpp:function}", "{cpp:member}", "{cpp:enum}", "{cpp:enumerator}"):
        assert directive in rendered


def test_undocumented_symbol_is_present_but_marked(gen: Generator, store: Store) -> None:
    rendered = gen.render_symbol(_symbol(store, "geo::mystery"), level=2)
    assert "{cpp:function} void geo::mystery()" in rendered
    assert "*No documentation provided.*" in rendered


def test_signature_carries_qualified_name(gen: Generator, store: Store) -> None:
    # Out-of-line member declarations must be qualified so the C++ domain can
    # attach them to the right parent without nesting directives.
    assert gen.signature(_symbol(store, "geo::Circle::area")) == "double geo::Circle::area() const"
    assert gen.signature(_symbol(store, "geo::Circle::radius")) == "double geo::Circle::radius"


def test_base_clause_from_references(gen: Generator, store: Store) -> None:
    assert gen.signature(_symbol(store, "geo::Circle")) == "geo::Circle : public Shape"


def test_typedef_signature_uses_underlying_reference(gen: Generator, store: Store) -> None:
    assert gen.signature(_symbol(store, "geo::Distance")) == "geo::Distance = double"


def test_xref_resolves_usr_symbol_and_name(gen: Generator, store: Store) -> None:
    shape = _symbol(store, "geo::Shape")
    assert gen.xref(shape.usr) == "{cpp:any}`geo::Shape`"
    assert gen.xref(shape) == "{cpp:any}`geo::Shape`"
    assert gen.xref("geo::Circle", role="class") == "{cpp:class}`geo::Circle`"


def test_xref_unresolved_reference_degrades_to_code(gen: Generator) -> None:
    ref = Reference(
        from_usr="x",
        ref_kind=RefKind.PARAM_TYPE,
        to_usr="",
        to_spelling="std::size_t",
        is_resolved=False,
        access=gen.store.symbol("c:@N@geo").access,  # AccessKind.NONE
        ordinal=0,
    )
    assert gen.xref(ref) == "`std::size_t`"


def test_user_template_overrides_default_by_name(store: Store, tmp_path: Path) -> None:
    user_dir = tmp_path / "templates"
    user_dir.mkdir()
    (user_dir / "function.md.jinja").write_text("CUSTOM {{ symbol.qualified_name }}\n")

    overridden = Generator(store, template_dirs=[user_dir])
    rendered = overridden.render_symbol(_symbol(store, "geo::scale"))
    assert rendered.strip() == "CUSTOM geo::scale"

    # Other kinds still fall through to the bundled defaults.
    klass = overridden.render_symbol(_symbol(store, "geo::Shape"))
    assert "{cpp:class} geo::Shape" in klass


def test_rendered_myst_builds_as_cpp_domain_objects(gen: Generator, tmp_path: Path) -> None:
    sphinx = pytest.importorskip("sphinx")
    pytest.importorskip("myst_parser")
    from sphinx.application import Sphinx  # noqa: PLC0415

    src = tmp_path / "src"
    gen.generate(src)
    (src / "conf.py").write_text('project = "fix"\nextensions = ["myst_parser"]\nmaster_doc = "index"\n')

    out = tmp_path / "out"
    warnings = tmp_path / "warnings.txt"
    app = Sphinx(
        str(src),
        str(src),
        str(out),
        str(tmp_path / "doctree"),
        "html",
        warningiserror=True,
        status=None,
        warning=warnings.open("w"),
    )
    app.build()

    html = (out / "geo.html").read_text()
    # The C++ domain produced mangled object ids and the {cpp:any} role linked to one.
    assert "_CPPv4N3geo6CircleE" in html
    assert 'href="#_CPPv4N3geo6CircleE"' in html
    assert sphinx.__version__  # silence unused-import concerns
