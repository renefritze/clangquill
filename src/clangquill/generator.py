"""Render the SQLite IR into MyST Markdown with C++ domain cross-references.

The generator is the user-facing customization point. It wires a Jinja2
environment whose loader is a :class:`~jinja2.ChoiceLoader` of any user template
directories followed by the package's own ``templates/``; a user file named
``{kind}.md.jinja`` therefore overrides the bundled default *by name*.

Templates render real Sphinx C++ domain directives (``cpp:class``,
``cpp:function``, …) so every symbol becomes an indexed domain object, and
inter-symbol links use ``{cpp:any}`` roles resolved from the ``references``
table. The Python side of this module supplies the context helpers templates
call: :meth:`Generator.xref`, :meth:`Generator.render_comment`, the signature
builders, and the child/relation queries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, StrictUndefined

from clangquill.store import AccessKind, RefKind, SymbolKind

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from clangquill.comments import CommentModel
    from clangquill.store import Enumerator, Group, Parameter, Reference, SourceFile, Store, Symbol

# Per-kind Jinja template (the ``{kind}.md.jinja`` override seam). Several
# SymbolKinds share a rendering, e.g. struct/union reuse the class template.
_TEMPLATE_FOR: dict[SymbolKind, str] = {
    SymbolKind.NAMESPACE: "namespace",
    SymbolKind.CLASS: "class",
    SymbolKind.STRUCT: "class",
    SymbolKind.UNION: "class",
    SymbolKind.CLASS_TEMPLATE: "class",
    SymbolKind.FUNCTION: "function",
    SymbolKind.METHOD: "function",
    SymbolKind.CONSTRUCTOR: "function",
    SymbolKind.DESTRUCTOR: "function",
    SymbolKind.FUNCTION_TEMPLATE: "function",
    SymbolKind.ENUM: "enum",
    SymbolKind.VARIABLE: "variable",
    SymbolKind.FIELD: "variable",
    SymbolKind.TYPEDEF: "typedef",
    SymbolKind.TYPE_ALIAS: "typedef",
    SymbolKind.CONCEPT: "concept",
    SymbolKind.MACRO: "macro",
}

# The C++ domain object directive emitted for each kind.
_DIRECTIVE_FOR: dict[SymbolKind, str] = {
    SymbolKind.NAMESPACE: "cpp:namespace",
    SymbolKind.CLASS: "cpp:class",
    SymbolKind.STRUCT: "cpp:struct",
    SymbolKind.UNION: "cpp:union",
    SymbolKind.CLASS_TEMPLATE: "cpp:class",
    SymbolKind.FUNCTION: "cpp:function",
    SymbolKind.METHOD: "cpp:function",
    SymbolKind.CONSTRUCTOR: "cpp:function",
    SymbolKind.DESTRUCTOR: "cpp:function",
    SymbolKind.FUNCTION_TEMPLATE: "cpp:function",
    SymbolKind.ENUM: "cpp:enum",
    SymbolKind.ENUMERATOR: "cpp:enumerator",
    SymbolKind.VARIABLE: "cpp:var",
    SymbolKind.FIELD: "cpp:member",
    SymbolKind.TYPEDEF: "cpp:type",
    SymbolKind.TYPE_ALIAS: "cpp:type",
    SymbolKind.CONCEPT: "cpp:concept",
    SymbolKind.MACRO: "c:macro",
}

# Human-readable label used in section headings.
_LABEL_FOR: dict[SymbolKind, str] = {
    SymbolKind.NAMESPACE: "Namespace",
    SymbolKind.CLASS: "Class",
    SymbolKind.STRUCT: "Struct",
    SymbolKind.UNION: "Union",
    SymbolKind.CLASS_TEMPLATE: "Class template",
    SymbolKind.FUNCTION: "Function",
    SymbolKind.METHOD: "Method",
    SymbolKind.CONSTRUCTOR: "Constructor",
    SymbolKind.DESTRUCTOR: "Destructor",
    SymbolKind.FUNCTION_TEMPLATE: "Function template",
    SymbolKind.ENUM: "Enum",
    SymbolKind.VARIABLE: "Variable",
    SymbolKind.FIELD: "Field",
    SymbolKind.TYPEDEF: "Typedef",
    SymbolKind.TYPE_ALIAS: "Type alias",
    SymbolKind.CONCEPT: "Concept",
    SymbolKind.MACRO: "Macro",
}

_ACCESS_KEYWORD: dict[AccessKind, str] = {
    AccessKind.PUBLIC: "public",
    AccessKind.PROTECTED: "protected",
    AccessKind.PRIVATE: "private",
}

_FUNCTION_KINDS = frozenset(
    {
        SymbolKind.FUNCTION,
        SymbolKind.METHOD,
        SymbolKind.CONSTRUCTOR,
        SymbolKind.DESTRUCTOR,
        SymbolKind.FUNCTION_TEMPLATE,
    },
)

_SLUG_RE = re.compile(r"[^0-9A-Za-z]+")
_BLANKS_RE = re.compile(r"\n{3,}")


def _slug(name: str) -> str:
    """Turn a qualified name into a filesystem-safe page stem."""
    slug = _SLUG_RE.sub("_", name).strip("_")
    return slug or "global"


def _normalize(text: str) -> str:
    """Collapse runs of blank lines and guarantee a single trailing newline."""
    return _BLANKS_RE.sub("\n\n", text).strip("\n") + "\n"


@dataclass(frozen=True)
class RenderedPage:
    """One rendered output page held in memory before it is written.

    ``stem`` is the filename without extension, ``label`` the human-readable
    toctree caption, and ``text`` the full MyST content. Keeping the content
    separate from the write lets the pipeline hash it and skip unchanged pages.
    """

    stem: str
    label: str
    text: str


class Generator:
    """Render symbols from a :class:`~clangquill.store.Store` into MyST Markdown.

    ``template_dirs`` are searched before the bundled templates, so a user file
    named like a bundled one (``class.md.jinja`` …) transparently replaces it.
    """

    def __init__(
        self,
        store: Store,
        *,
        template_dirs: Sequence[str | Path] | None = None,
        templates: Mapping[str, str] | None = None,
        include_undocumented: bool = True,
        comment_parser: str | None = None,
    ) -> None:
        """Bind a store and build the Jinja environment with overrides first.

        ``templates`` maps a symbol kind (its lowercase :class:`SymbolKind`
        name, e.g. ``"method"``, or the bundled template stem, e.g. ``"class"``)
        to a replacement template stem. ``include_undocumented`` controls
        whether symbols lacking a documentation comment are emitted.
        ``comment_parser`` overrides the comment format (a registered name or a
        dotted import path) for every symbol.
        """
        self.store = store
        self.include_undocumented = include_undocumented
        self.comment_parser = comment_parser
        self._template_overrides = {k.lower(): v for k, v in (templates or {}).items()}
        self._documented_descendant: dict[str, bool] = {}
        loaders: list[FileSystemLoader | PackageLoader] = []
        if template_dirs:
            loaders.append(FileSystemLoader([str(d) for d in template_dirs]))
        loaders.append(PackageLoader("clangquill", "templates"))
        self.env = Environment(
            loader=ChoiceLoader(loaders),
            autoescape=False,  # noqa: S701 - output is Markdown, not HTML; escaping would corrupt it
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            undefined=StrictUndefined,
        )
        self._install_context()

    # -- environment wiring ---------------------------------------------------

    def _install_context(self) -> None:
        """Expose the helpers/globals templates rely on."""
        g = self.env.globals
        g["gen"] = self
        g["store"] = self.store
        g["SymbolKind"] = SymbolKind
        g["RefKind"] = RefKind
        g["xref"] = self.xref
        g["render_comment"] = self.render_comment
        g["field_list"] = self.field_list

    # -- relation / child queries (thin pass-throughs for templates) ----------

    def children(self, symbol: Symbol) -> list[Symbol]:
        """Return the visible direct children of ``symbol``."""
        return [c for c in self.store.children(symbol.usr) if self._visible(c)]

    def roots(self) -> list[Symbol]:
        """Return the visible top-level symbols of the database."""
        return [r for r in self.store.roots() if self._visible(r)]

    def _visible(self, symbol: Symbol) -> bool:
        """Whether ``symbol`` should appear, honouring ``include_undocumented``.

        An undocumented container is still shown when it transitively contains a
        documented symbol, so suppressing undocumented leaves never hides the
        scope that holds documented members.
        """
        if self.include_undocumented or symbol.is_documented:
            return True
        return self._has_documented_descendant(symbol.usr)

    def _has_documented_descendant(self, usr: str) -> bool:
        cached = self._documented_descendant.get(usr)
        if cached is not None:
            return cached
        # Guard against pathological cycles in malformed IR.
        self._documented_descendant[usr] = False
        result = any(
            child.is_documented or self._has_documented_descendant(child.usr) for child in self.store.children(usr)
        )
        self._documented_descendant[usr] = result
        return result

    def parameters(self, symbol: Symbol) -> list[Parameter]:
        """Return the function parameters of ``symbol``."""
        return self.store.parameters(symbol.usr)

    def enumerators(self, symbol: Symbol) -> list[Enumerator]:
        """Return the enumerators of an enum ``symbol``."""
        return self.store.enumerators(symbol.usr)

    def bases(self, symbol: Symbol) -> list[Reference]:
        """Return the base-class references of ``symbol``."""
        return self.store.bases(symbol.usr)

    def friends(self, symbol: Symbol) -> list[Reference]:
        """Return the friend references of a record ``symbol``."""
        return self.store.friends(symbol.usr)

    def group_symbols(self, group: Group) -> list[Symbol]:
        """Return the member symbols of ``group`` (skipping any now absent)."""
        return self.store.group_symbols(group.id)

    def subgroups(self, group: Group) -> list[Group]:
        """Return the groups nested directly under ``group``."""
        return self.store.subgroups(group.id)

    @staticmethod
    def group_stem(group: Group) -> str:
        """Return the page stem used for ``group`` (matches :meth:`_render_group_pages`)."""
        return _slug(f"group_{group.id}")

    def comment(self, symbol: Symbol) -> CommentModel | None:
        """Return the structured comment for ``symbol``, or ``None``."""
        return self.store.comment(symbol.usr, parser=self.comment_parser)

    # -- presentation helpers -------------------------------------------------

    def directive(self, symbol: Symbol) -> str:
        """Return the C++ domain directive name for ``symbol`` (e.g. ``cpp:class``)."""
        return _DIRECTIVE_FOR.get(symbol.kind, "cpp:type")

    def label(self, symbol: Symbol) -> str:
        """Return the human-readable kind label used in headings."""
        return _LABEL_FOR.get(symbol.kind, "Symbol")

    def template_name(self, symbol: Symbol) -> str:
        """Return the ``{kind}.md.jinja`` template selected for ``symbol``.

        A ``templates`` override keyed by the kind name (e.g. ``"method"``)
        wins; failing that one keyed by the bundled stem (e.g. ``"class"``)
        applies, so an override can target a single kind or a whole family.
        """
        base = _TEMPLATE_FOR.get(symbol.kind, "variable")
        if not self._template_overrides:
            return base
        return self._template_overrides.get(symbol.kind.name.lower()) or self._template_overrides.get(base, base)

    def base_clause(self, symbol: Symbol) -> str:
        """Return the ``: public Base, …`` clause for a class, or ``""``."""
        bases = self.bases(symbol)
        if not bases:
            return ""
        parts = []
        for base in bases:
            keyword = _ACCESS_KEYWORD.get(base.access)
            spelling = base.to_spelling
            parts.append(f"{keyword} {spelling}" if keyword else spelling)
        return " : " + ", ".join(parts)

    def signature(self, symbol: Symbol) -> str:  # noqa: PLR0911
        """Return the directive argument (the text after ``{cpp:...}``).

        The argument carries the *qualified* name so the C++ domain attaches an
        out-of-line declaration to the right parent scope without any directive
        nesting.
        """
        if symbol.kind in _FUNCTION_KINDS:
            sig = symbol.signature or f"{symbol.spelling}()"
            return self._qualify(sig, symbol)
        if symbol.kind in (SymbolKind.VARIABLE, SymbolKind.FIELD):
            type_repr = symbol.type_repr.strip()
            return f"{type_repr} {symbol.qualified_name}".strip()
        if symbol.kind in (SymbolKind.TYPEDEF, SymbolKind.TYPE_ALIAS):
            target = self._underlying(symbol)
            return f"{symbol.qualified_name} = {target}" if target else symbol.qualified_name
        if symbol.kind == SymbolKind.MACRO:
            # ``signature`` is the function-like macro's ``NAME(a, b)`` (or the
            # bare name for an object-like macro).
            return symbol.signature or symbol.spelling
        if symbol.kind == SymbolKind.CONCEPT:
            # ``signature`` holds the ``template<...>`` head; the cpp:concept
            # directive wants ``template<...> Name`` (no ``= constraint``).
            head = f"{symbol.signature} " if symbol.signature else ""
            return head + symbol.qualified_name
        if symbol.kind in (SymbolKind.CLASS, SymbolKind.STRUCT, SymbolKind.UNION, SymbolKind.CLASS_TEMPLATE):
            # For a class template ``signature`` is the leading ``template<...>``
            # head; prepend it so the directive indexes a template object.
            head = f"{symbol.signature} " if symbol.signature else ""
            return head + symbol.qualified_name + self.base_clause(symbol)
        return symbol.qualified_name

    def _qualify(self, signature: str, symbol: Symbol) -> str:
        """Inject the qualified name into a bare pretty-printed signature."""
        if symbol.qualified_name == symbol.spelling or not symbol.spelling:
            return signature
        pattern = re.compile(rf"(?<![\w:]){re.escape(symbol.spelling)}(?=\s*\()")
        new, count = pattern.subn(symbol.qualified_name, signature, count=1)
        return new if count else signature

    def _underlying(self, symbol: Symbol) -> str:
        """Return the typedef/alias target spelling, or ``""``."""
        refs = self.store.references(symbol.usr, kind=RefKind.UNDERLYING_TYPE)
        return refs[0].to_spelling if refs else ""

    # -- cross-references -----------------------------------------------------

    def xref(self, target: str | Symbol | Reference, *, role: str = "any") -> str:
        """Return a MyST C++ domain cross-reference role for ``target``.

        ``target`` may be a name/USR string, a :class:`~clangquill.store.Symbol`,
        or a :class:`~clangquill.store.Reference`. The role links by *name* (which
        is how the C++ domain resolves ``{cpp:any}``): a USR is first resolved to
        its qualified name via the ``symbols`` table, a :class:`Reference` uses its
        target's qualified name, and a bare string is taken to be a name already.
        An *unresolved* reference (a builtin, template parameter, or out-of-TU
        type) degrades to inline code of its written spelling, since there is no
        domain object to point at.
        """
        if isinstance(target, str):
            resolved = self.store.symbol(target)
            name = resolved.qualified_name if resolved is not None else target
            return f"{{cpp:{role}}}`{name}`" if name else ""
        to_usr = getattr(target, "to_usr", None)
        if to_usr is not None:  # a Reference
            resolved = self.store.symbol(to_usr) if to_usr else None
            if resolved is not None:
                return f"{{cpp:{role}}}`{resolved.qualified_name}`"
            # No documented target to point at (a builtin, an out-of-TU type, or
            # a befriended entity declared elsewhere): degrade to inline code so
            # the output carries no dangling cross-reference.
            return f"`{target.to_spelling}`" if target.to_spelling else ""
        name = target.qualified_name or target.spelling
        return f"{{cpp:{role}}}`{name}`" if name else ""

    # -- comment rendering ----------------------------------------------------

    def render_comment(self, model: CommentModel | None) -> str:
        """Render the prose block of a comment (brief, detail, admonitions).

        ``None`` (an undocumented symbol) renders a clear, present placeholder
        rather than nothing so the symbol still appears in the output.
        """
        macro = self.env.get_template("partials/comment-block.md.jinja").module.body
        return str(macro(model)).strip()

    def field_list(self, model: CommentModel | None) -> str:
        """Render the Sphinx field list (``:param:``, ``:returns:`` …) of a comment."""
        if model is None:
            return ""
        macro = self.env.get_template("partials/param-table.md.jinja").module.fields
        return str(macro(model)).strip()

    # -- rendering ------------------------------------------------------------

    def render_symbol(self, symbol: Symbol, *, level: int = 1) -> str:
        """Render ``symbol`` (and, for containers, its descendants) to MyST.

        ``level`` is the Markdown heading depth used for section symbols.
        """
        template = self.env.get_template(f"{self.template_name(symbol)}.md.jinja")
        return _normalize(template.render(symbol=symbol, level=level))

    def render_file(self, source_file: SourceFile, *, level: int = 1) -> str:
        """Render every top-level symbol declared in ``source_file``."""
        template = self.env.get_template("file.md.jinja")
        symbols = [s for s in self.roots() if s.file_id == source_file.id]
        return _normalize(template.render(file=source_file, symbols=symbols, level=level))

    def render_group(self, group: Group, *, level: int = 1) -> str:
        """Render a single documentation group page (members + subgroups)."""
        template = self.env.get_template("group.md.jinja")
        return _normalize(template.render(group=group, level=level))

    def render_pages(self, *, group_by: str = "symbol") -> list[RenderedPage]:
        r"""Render every page in memory without writing, in toctree order.

        ``group_by`` selects the page partitioning: ``"symbol"`` yields one page
        per top-level symbol, ``"file"`` one page per parsed source file. Pages
        for any Doxygen ``\defgroup`` groups are appended after the symbol/file
        pages; when there are no groups nothing is appended, so output for
        group-free projects is unchanged. The caller decides how (and whether)
        to persist each :class:`RenderedPage`, which is what lets the
        incremental pipeline skip unchanged outputs.
        """
        pages = self._render_file_pages() if group_by == "file" else self._render_symbol_pages()
        return pages + self._render_group_pages()

    def render_index(
        self,
        pages: Sequence[RenderedPage],
        *,
        toctree_maxdepth: int = 2,
    ) -> str:
        """Render the toctree index page that links ``pages`` in order."""
        index = self.env.get_template("index.md.jinja")
        return index.render(pages=[(p.stem, p.label) for p in pages], maxdepth=toctree_maxdepth)

    def generate(
        self,
        out_dir: str | Path,
        *,
        group_by: str = "symbol",
        toctree_maxdepth: int = 2,
        root_document: str = "index",
    ) -> list[str]:
        """Render the IR into ``out_dir`` and write a toctree index.

        ``group_by`` selects the page partitioning: ``"symbol"`` writes one page
        per top-level symbol, ``"file"`` one page per parsed source file.
        ``toctree_maxdepth`` and ``root_document`` shape the generated index
        page (written as ``<root_document>.md``). Returns the page stems written
        (excluding the index), in toctree order.
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        pages = self.render_pages(group_by=group_by)
        for page in pages:
            (out / f"{page.stem}.md").write_text(page.text, encoding="utf-8")
        (out / f"{root_document}.md").write_text(
            self.render_index(pages, toctree_maxdepth=toctree_maxdepth),
            encoding="utf-8",
        )
        return [page.stem for page in pages]

    def _render_symbol_pages(self) -> list[RenderedPage]:
        """Render one page per visible root symbol."""
        pages: list[RenderedPage] = []
        seen: set[str] = set()
        for root in self.roots():
            stem = self._unique_stem(_slug(root.qualified_name or root.spelling), seen)
            pages.append(RenderedPage(stem, root.qualified_name or root.spelling, self.render_symbol(root, level=1)))
        return pages

    def _render_file_pages(self) -> list[RenderedPage]:
        """Render one page per parsed source file that declares a root symbol."""
        pages: list[RenderedPage] = []
        seen: set[str] = set()
        roots_by_file: dict[int | None, list[Symbol]] = {}
        for root in self.roots():
            roots_by_file.setdefault(root.file_id, []).append(root)
        for source_file in self.store.files():
            if not roots_by_file.get(source_file.id):
                continue
            # The IR stores resolved (absolute) paths; page on the basename so
            # filenames stay short and do not leak the build machine layout.
            name = Path(source_file.path).name
            stem = self._unique_stem(_slug(name), seen)
            pages.append(RenderedPage(stem, name, self.render_file(source_file, level=1)))
        return pages

    def _render_group_pages(self) -> list[RenderedPage]:
        """Render one page per documentation group, top-level groups first.

        Returns an empty list when the IR defines no groups, leaving output for
        group-free projects byte-identical to before.
        """
        groups = self.store.groups()
        if not groups:
            return []
        pages: list[RenderedPage] = []
        seen: set[str] = set()
        # Top-level groups first, then nested ones, for a stable toctree order.
        ordered = self.store.root_groups()
        ordered_ids = {g.id for g in ordered}
        ordered += [g for g in groups if g.id not in ordered_ids]
        for group in ordered:
            stem = self._unique_stem(_slug(f"group_{group.id}"), seen)
            pages.append(RenderedPage(stem, group.title or group.id, self.render_group(group, level=1)))
        return pages

    @staticmethod
    def _unique_stem(stem: str, seen: set[str]) -> str:
        """Disambiguate ``stem`` against ``seen``, recording the result."""
        while stem in seen:
            stem += "_"
        seen.add(stem)
        return stem


def render_symbol(store: Store, symbol: Symbol, **kwargs: object) -> str:
    """Render a single symbol with a throwaway generator (convenience wrapper)."""
    return Generator(store).render_symbol(symbol, **kwargs)  # type: ignore[arg-type]


def generate(store: Store, out_dir: str | Path, **kwargs: object) -> list[str]:
    """Render ``store`` into ``out_dir`` with a throwaway generator (convenience wrapper)."""
    return Generator(store, **kwargs).generate(out_dir)  # type: ignore[arg-type]


__all__ = ["Generator", "RenderedPage", "generate", "render_symbol"]
