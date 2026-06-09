"""Tests for the MyST generator: golden output, overrides, xrefs, Sphinx build."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from clangquill.generator import Generator
from clangquill.store import Reference, RefKind, SourceFile, Store, Symbol

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


def test_include_undocumented_false_drops_leaf_but_keeps_scope(store: Store, tmp_path: Path) -> None:
    # The geo namespace itself is documented and holds documented members, so it
    # stays; the undocumented free function geo::mystery is suppressed.
    gen = Generator(store, include_undocumented=False)
    rendered = gen.render_symbol(_symbol(store, "geo"), level=1)
    assert "geo::Circle" in rendered
    assert "geo::mystery" not in rendered

    pages = gen.generate(tmp_path / "api")
    assert pages == ["geo"]


def test_group_by_file_writes_one_page_per_file(gen: Generator, tmp_path: Path) -> None:
    out = tmp_path / "api"
    pages = gen.generate(out, group_by="file")
    assert pages == ["geo_hpp"]
    page = (out / "geo_hpp.md").read_text()
    assert page.startswith("# File `geo.hpp`")
    assert "geo::Circle" in page


def test_relpath_filter_reroots_under_base(store: Store) -> None:
    gen = Generator(store, path_base="/work/repo")
    # A file under the base is shown relative, with forward slashes.
    assert gen._relpath("/work/repo/src/foo.hpp") == "src/foo.hpp"  # noqa: SLF001
    # The base directory itself collapses to ".".
    assert gen._relpath("/work/repo") == "."  # noqa: SLF001
    # A path outside the base keeps its absolute spelling (no ".." escape).
    assert gen._relpath("/work/other/bar.hpp") == "/work/other/bar.hpp"  # noqa: SLF001


def test_relpath_filter_is_identity_without_base(store: Store) -> None:
    gen = Generator(store)
    assert gen._relpath("/work/repo/src/foo.hpp") == "/work/repo/src/foo.hpp"  # noqa: SLF001


def test_file_heading_reroots_with_path_base(store: Store) -> None:
    # The IR stores absolute, build-machine paths; the bundled file.md.jinja runs
    # them through the `relpath` filter, so a path_base re-roots the "File"
    # heading to a stable, relative path with forward slashes.
    absolute = SourceFile(id=99, path="/work/repo/include/geo.hpp", sha256="x", size_bytes=0)
    gen = Generator(store, path_base="/work/repo")
    rendered = gen.render_file(absolute)
    assert rendered.startswith("# File `include/geo.hpp`")
    assert "/work/repo" not in rendered


def test_store_file_roots_skips_same_file_parents(multifile_db: Path) -> None:
    with Store.open(multifile_db) as store:
        # alpha.hpp owns the namespace record, so the namespace is its file-root;
        # the class and its method nest under it and are not file-roots.
        alpha_roots = {s.qualified_name for s in store.file_roots(1)}
        assert alpha_roots == {"app"}
        # beta.hpp declares only a class whose parent namespace lives elsewhere,
        # so the class is the file-root despite not being a global root.
        beta_roots = {s.qualified_name for s in store.file_roots(2)}
        assert beta_roots == {"app::Beta"}


def test_group_by_file_pages_every_file_of_a_spanning_namespace(multifile_db: Path, tmp_path: Path) -> None:
    # Regression: a namespace spanning two files used to leave every file but
    # the namespace's recorded home without a page (only global roots counted),
    # so whole subtrees vanished from the index. Each file must now get a page.
    with Store.open(multifile_db) as store:
        out = tmp_path / "api"
        pages = Generator(store).generate(out, group_by="file")

    assert pages == ["alpha_hpp", "beta_hpp"]
    alpha = (out / "alpha_hpp.md").read_text()
    beta = (out / "beta_hpp.md").read_text()
    # Each file lists only the class it declares, even though both share the
    # ``app`` namespace whose single record lives in alpha.hpp.
    assert "app::Alpha" in alpha
    assert "app::Beta" not in alpha
    assert "app::Beta" in beta
    assert "app::Alpha" not in beta
    # A method shares its class's file, so it renders under the class rather
    # than as a second top-of-file entry.
    assert "app::Alpha::run" in alpha


def test_templates_override_by_kind(store: Store, tmp_path: Path) -> None:
    user_dir = tmp_path / "templates"
    user_dir.mkdir()
    (user_dir / "tweaked.md.jinja").write_text("TWEAKED {{ symbol.qualified_name }}\n")

    gen = Generator(store, template_dirs=[user_dir], templates={"function": "tweaked"})
    # Free functions and methods both resolve to the "function" stem, so both
    # pick up the override keyed by kind name.
    assert gen.render_symbol(_symbol(store, "geo::scale")).strip() == "TWEAKED geo::scale"
    # Classes are unaffected.
    assert "{cpp:class} geo::Shape" in gen.render_symbol(_symbol(store, "geo::Shape"))


def test_toctree_maxdepth_is_honoured(gen: Generator, tmp_path: Path) -> None:
    out = tmp_path / "api"
    gen.generate(out, toctree_maxdepth=4)
    assert ":maxdepth: 4" in (out / "index.md").read_text()


def test_root_document_renames_index(gen: Generator, tmp_path: Path) -> None:
    out = tmp_path / "api"
    gen.generate(out, root_document="contents")
    assert (out / "contents.md").is_file()
    assert not (out / "index.md").exists()


@pytest.fixture
def m7_store(m7_db: Path) -> Iterator[Store]:
    with Store.open(m7_db) as opened:
        yield opened


@pytest.fixture
def m7_gen(m7_store: Store) -> Generator:
    return Generator(m7_store)


def test_class_template_signature_carries_head(m7_gen: Generator, m7_store: Store) -> None:
    sig = m7_gen.signature(_symbol(m7_store, "nn::Box"))
    assert sig == "template<typename T, int N = 4> nn::Box"


def test_concept_signature_carries_head(m7_gen: Generator, m7_store: Store) -> None:
    assert m7_gen.signature(_symbol(m7_store, "nn::Addable")) == "template<typename T> nn::Addable"


def test_macro_signature_is_name_or_call(m7_gen: Generator, m7_store: Store) -> None:
    assert m7_gen.signature(_symbol(m7_store, "PI")) == "PI"
    assert m7_gen.signature(_symbol(m7_store, "MAXM")) == "MAXM(a, b)"


def test_concept_and_macro_emit_domain_directives(m7_gen: Generator, m7_store: Store) -> None:
    assert "{cpp:concept} template<typename T> nn::Addable" in m7_gen.render_symbol(_symbol(m7_store, "nn::Addable"))
    assert "{c:macro} MAXM(a, b)" in m7_gen.render_symbol(_symbol(m7_store, "MAXM"))


def test_friends_block_links_documented_and_inlines_unknown(m7_gen: Generator, m7_store: Store) -> None:
    rendered = m7_gen.render_symbol(_symbol(m7_store, "nn::Pt"))
    assert "**Friends**" in rendered
    # A documented friend links via the domain; an out-of-TU friend degrades to code.
    assert "{cpp:any}`nn::helper`" in rendered
    assert "`Outsider`" in rendered


def test_group_pages_appended_and_render_members(m7_gen: Generator, tmp_path: Path) -> None:
    pages = m7_gen.generate(tmp_path / "api")
    assert "group_grp" in pages
    page = (tmp_path / "api" / "group_grp.md").read_text()
    assert page.startswith("# Grouped API")
    assert "{cpp:any}`nn::Box`" in page
    assert "{cpp:any}`nn::helper`" in page


def test_no_group_pages_when_db_has_no_groups(gen: Generator, tmp_path: Path) -> None:
    # The geo fixture defines no groups, so output is unchanged (no group pages).
    pages = gen.generate(tmp_path / "api")
    assert not any(stem.startswith("group_") for stem in pages)


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


def test_m7_kinds_build_as_domain_objects(m7_gen: Generator, tmp_path: Path) -> None:
    pytest.importorskip("sphinx")
    pytest.importorskip("myst_parser")
    from sphinx.application import Sphinx  # noqa: PLC0415

    src = tmp_path / "src"
    m7_gen.generate(src)
    (src / "conf.py").write_text('project = "m7"\nextensions = ["myst_parser"]\nmaster_doc = "index"\n')

    warnings = tmp_path / "warnings.txt"
    # warningiserror catches dangling cross-references, unknown directives, and
    # malformed C++/C-domain signatures, so a clean build validates every kind.
    app = Sphinx(
        str(src),
        str(src),
        str(tmp_path / "out"),
        str(tmp_path / "doctree"),
        "html",
        warningiserror=True,
        status=None,
        warning=warnings.open("w"),
    )
    app.build()
