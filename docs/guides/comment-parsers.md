# Comment-parser override guide

clangquill stores each symbol's documentation comment **verbatim** in the IR and
parses it into a format-agnostic {py:class}`~clangquill.comments.CommentModel`
only when rendering. That parse step is pluggable, so you can support a comment
dialect other than the bundled Doxygen one — or post-process the default — by
supplying your own parser.

## The CommentModel

A `CommentModel` is a plain dataclass of structured fields the templates render:

| Field | Type | From (Doxygen) |
|-------|------|----------------|
| `brief` | `str` | `@brief` / first paragraph |
| `detail` | `list[str]` | remaining paragraphs |
| `params`, `tparams` | `list[CommentParam]` | `@param`, `@tparam` |
| `returns` | `str` | `@return` |
| `retvals` | `list[CommentRetval]` | `@retval` |
| `throws` | `list[CommentThrow]` | `@throws` / `@exception` |
| `see`, `since`, `deprecated`, `note`, `warning`, `pre`, `post` | `list[str]` | the matching commands |
| `custom` | `dict[str, list[str]]` | **any unrecognized command**, keyed by its name |

The `custom` bucket is the graceful-degradation seam: a command the parser does
not recognize is never dropped — it lands in `custom["<name>"]` so a template can
still render it.

## A parser is just a callable

```python
CommentParser = Callable[[str], CommentModel]
```

It takes the raw comment text (markers included) and returns a `CommentModel`.

## Selecting a parser

A parser override is resolved (in {py:func}`clangquill.comments.resolve_override`)
from any of, in order:

1. a **registered name** — the built-in registry ships `"doxygen"`; add your own
   with {py:func}`~clangquill.comments.register_parser`;
2. a **dotted import path** to a callable, e.g. `"my_pkg.parsers:rst_parser"`;
3. the **`CLANGQUILL_COMMENT_PARSER`** environment variable (same two forms).

Wire it through whichever front end you use:

```python
# Sphinx (conf.py)
clangquill_comment_parser = "my_pkg.parsers:rst_parser"
```

```console
$ clangquill build include/geo.hpp --comment-parser my_pkg.parsers:rst_parser
```

```python
# Python
Generator(store, comment_parser="rst").generate("docs/api")
```

## Example: register a custom parser

```python
from clangquill.comments import CommentModel, register_parser

def shouty_parser(raw: str) -> CommentModel:
    # Reuse the default and post-process, or build a CommentModel from scratch.
    from clangquill.comments import get_parser
    model = get_parser("doxygen")(raw)
    return CommentModel(brief=model.brief.upper(), detail=model.detail)

register_parser("shouty", shouty_parser)
# Now selectable as clangquill_comment_parser = "shouty"
```

Inspect what is registered with
{py:func}`~clangquill.comments.available_parsers`.

```{note}
The parser only affects *rendering*. The verbatim comment text is always
preserved in the IR, so changing parsers never requires re-parsing the C++.
```
