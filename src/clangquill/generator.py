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
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, StrictUndefined

from clangquill.store import AccessKind, RefKind, SymbolKind

if TYPE_CHECKING:
    from collections.abc import Sequence

    from clangquill.comments import CommentModel
    from clangquill.store import Enumerator, Parameter, Reference, SourceFile, Store, Symbol

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
    ) -> None:
        """Bind a store and build the Jinja environment with overrides first."""
        self.store = store
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
        """Return the direct children of ``symbol``."""
        return self.store.children(symbol.usr)

    def roots(self) -> list[Symbol]:
        """Return the top-level symbols of the database."""
        return self.store.roots()

    def parameters(self, symbol: Symbol) -> list[Parameter]:
        """Return the function parameters of ``symbol``."""
        return self.store.parameters(symbol.usr)

    def enumerators(self, symbol: Symbol) -> list[Enumerator]:
        """Return the enumerators of an enum ``symbol``."""
        return self.store.enumerators(symbol.usr)

    def bases(self, symbol: Symbol) -> list[Reference]:
        """Return the base-class references of ``symbol``."""
        return self.store.bases(symbol.usr)

    def comment(self, symbol: Symbol) -> CommentModel | None:
        """Return the structured comment for ``symbol``, or ``None``."""
        return self.store.comment(symbol.usr)

    # -- presentation helpers -------------------------------------------------

    def directive(self, symbol: Symbol) -> str:
        """Return the C++ domain directive name for ``symbol`` (e.g. ``cpp:class``)."""
        return _DIRECTIVE_FOR.get(symbol.kind, "cpp:type")

    def label(self, symbol: Symbol) -> str:
        """Return the human-readable kind label used in headings."""
        return _LABEL_FOR.get(symbol.kind, "Symbol")

    def template_name(self, symbol: Symbol) -> str:
        """Return the ``{kind}.md.jinja`` template selected for ``symbol``."""
        return _TEMPLATE_FOR.get(symbol.kind, "variable")

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

    def signature(self, symbol: Symbol) -> str:
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
        if symbol.kind in (SymbolKind.CLASS, SymbolKind.STRUCT, SymbolKind.UNION, SymbolKind.CLASS_TEMPLATE):
            return symbol.qualified_name + self.base_clause(symbol)
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
            if not target.is_resolved and not to_usr:
                return f"`{target.to_spelling}`" if target.to_spelling else ""
            resolved = self.store.symbol(to_usr) if to_usr else None
            name = resolved.qualified_name if resolved is not None else target.to_spelling
            return f"{{cpp:{role}}}`{name}`" if name else ""
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

    def generate(self, out_dir: str | Path) -> list[str]:
        """Render every root symbol to ``out_dir`` and write a toctree index.

        Returns the list of page stems written (excluding ``index``).
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        pages: list[tuple[str, Symbol]] = []
        seen: set[str] = set()
        for root in self.roots():
            stem = _slug(root.qualified_name or root.spelling)
            while stem in seen:
                stem += "_"
            seen.add(stem)
            (out / f"{stem}.md").write_text(self.render_symbol(root, level=1), encoding="utf-8")
            pages.append((stem, root))
        index = self.env.get_template("index.md.jinja")
        (out / "index.md").write_text(index.render(pages=pages), encoding="utf-8")
        return [stem for stem, _ in pages]


def render_symbol(store: Store, symbol: Symbol, **kwargs: object) -> str:
    """Render a single symbol with a throwaway generator (convenience wrapper)."""
    return Generator(store).render_symbol(symbol, **kwargs)  # type: ignore[arg-type]


def generate(store: Store, out_dir: str | Path, **kwargs: object) -> list[str]:
    """Render ``store`` into ``out_dir`` with a throwaway generator (convenience wrapper)."""
    return Generator(store, **kwargs).generate(out_dir)  # type: ignore[arg-type]


__all__ = ["Generator", "generate", "render_symbol"]
