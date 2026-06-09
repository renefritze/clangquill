# clangquill

![ClangQuill Logo](https://raw.githubusercontent.com/renefritze/clangquill/main/docs/_static/clangquill-logo.png)

[![image](https://github.com/renefritze/clangquill/workflows/pytest/badge.svg)](https://github.com/renefritze/clangquill/actions)

**Parse Doxygen-documented C++ with libclang and generate MyST Markdown API docs for Sphinx.**

clangquill reads your C++ headers with [libclang](https://clang.llvm.org/),
extracts classes, functions, namespaces, enums and their documentation comments
into a SQLite intermediate representation, and renders [MyST
Markdown](https://myst-parser.readthedocs.io/) pages. Every symbol becomes a real
Sphinx C++ domain object (`{cpp:class}`, `{cpp:function}`, …) — so the generated
API appears in `objects.inv` and cross-references like any hand-written page,
with inter-symbol links resolved through `{cpp:any}`.

## Features

- **libclang-based parsing** of real C++ (`c++20` / `c++23` / `c++26`), including
  Doxygen comments and `compile_commands.json` support.
- **First-class Sphinx integration** — output is MyST Markdown backed by the
  Sphinx C++ domain, so symbols cross-reference and show up in the search index.
- **Three front-ends** for the same pipeline: a Sphinx extension, a `clangquill`
  CLI, and a Python API.
- **Incremental builds** — a persistent SQLite IR plus a hash cache skip
  re-parsing unchanged inputs, rewrite only pages whose content changed, and
  delete pages for symbols that disappeared.
- **Customizable output** via per-kind Jinja2 templates you can override one file
  at a time.
- **Pluggable comment parsers** (Doxygen by default).

## Installation

clangquill is published on PyPI. Install it with [uv](https://docs.astral.sh/uv/):

```console
$ uv pip install clangquill
```

(Plain `pip install clangquill` works too.)

The Linux wheels bundle a self-contained **libclang 22** from the official LLVM
release, so parsing works out of the box with no system LLVM required. That
bundled libclang needs **glibc ≥ 2.34** (manylinux_2_34); on older distributions,
[build from source](#building-from-source) against your own libclang instead.

## Quick start

### Sphinx extension

For the common case you do not need to drive the parser yourself: enable the
bundled extension and it runs the whole pipeline — parse → SQLite → MyST — at
build time, regenerating pages into your source tree before Sphinx reads them.

```python
# conf.py
extensions = ["clangquill.sphinx_ext"]  # pulls in myst_parser automatically

clangquill_input = ["../include/**/*.hpp"]
clangquill_output_dir = "api"          # written under the Sphinx srcdir
clangquill_std = "c++20"
clangquill_include_dirs = ["../include"]
```

Then reference the generated toctree from your root document:

````markdown
```{toctree}
api/index
```
````

Every knob is a `clangquill_*` config value mirroring a field of
`clangquill.config.Config` — including `clangquill_compile_commands`,
`clangquill_template_dirs`, `clangquill_include_undocumented`,
`clangquill_comment_parser` and `clangquill_group_by`. See the
[configuration guide](https://github.com/renefritze/clangquill/blob/main/docs/guides/configuration.md)
for the full reference.

### Command line

The same pipeline is available standalone, handy for previewing output or wiring
clangquill into a non-Sphinx build:

```console
$ clangquill build include/geo.hpp -o docs/api --std c++20 -I include
Parsed 7 symbol(s) from 1 file(s).
Wrote 1 page(s) to /path/to/docs/api.
```

Run `clangquill build --help` for the full set of options, which mirror the
`clangquill_*` config values.

### Python API

Once a project has been parsed into the SQLite IR, the generator renders it into
MyST Markdown: one page per top-level symbol plus an `index.md` toctree.

```python
from clangquill.generator import Generator
from clangquill.store import Store

with Store.open("api.sqlite") as store:
    Generator(store).generate("docs/api")
```

## Incremental builds

Set `clangquill_cache_dir` (or the matching CLI/API option) to make rebuilds
incremental. clangquill keeps the SQLite IR and a small bookkeeping cache between
runs and:

- **skips the parse** when no input — or transitively `#include`d header —
  changed, reusing the cached IR instead of invoking libclang again;
- **rewrites only the pages whose content changed**; and
- **deletes pages whose symbols disappeared**.

Without a cache directory the build is stateless: it re-parses into a throwaway
database and rewrites every page each time.

## Templates

Templates are the customization point. The Jinja environment looks up
`{kind}.md.jinja` (e.g. `class.md.jinja`, `function.md.jinja`) in your own
template directories *before* the bundled defaults, so dropping in a file of the
same name overrides just that kind:

```python
Generator(store, template_dirs=["my_templates"]).generate("docs/api")
```

See the
[templates guide](https://github.com/renefritze/clangquill/blob/main/docs/guides/templates.md)
for the available templates and context variables.

## Building from source

`clangquill` ships a compiled C++ core (`clangquill._core`) built with
[scikit-build-core](https://scikit-build-core.readthedocs.io/), CMake and
[nanobind](https://nanobind.readthedocs.io/). A standard install builds it:

```console
$ uv pip install .
$ uv run python -c "from clangquill import _core; print(_core.have_libclang())"
```

The core optionally links **libclang**; when `libclang-dev` (or an LLVM prefix
via `LibClang_ROOT`) is available at build time the extraction backend is
enabled. Pass `-DCLANGQUILL_WITH_LIBCLANG=ON` to require it.

## Documentation

- [Usage](https://github.com/renefritze/clangquill/blob/main/docs/usage.md) — generator, Sphinx extension, CLI and incremental builds
- [Installation](https://github.com/renefritze/clangquill/blob/main/docs/installation.md)
- [Configuration reference](https://github.com/renefritze/clangquill/blob/main/docs/guides/configuration.md)
- [Templates](https://github.com/renefritze/clangquill/blob/main/docs/guides/templates.md)
- [Comment parsers](https://github.com/renefritze/clangquill/blob/main/docs/guides/comment-parsers.md)

## Contributing

Contributions are welcome — see
[CONTRIBUTING.md](https://github.com/renefritze/clangquill/blob/main/CONTRIBUTING.md).
In short:

```console
$ uv sync --extra dev
$ uvx pre-commit install
$ uv run pytest      # Python test suite
$ make cpp-test      # C++ (Catch2) unit tests
```

## License

clangquill is released under the BSD 2-Clause License — see
[LICENSE](https://github.com/renefritze/clangquill/blob/main/LICENSE).
The Linux wheels additionally bundle libclang, distributed under the
Apache-2.0 WITH LLVM-exception license.

## Credits

This package was created with
[Cookiecutter](https://github.com/audreyr/cookiecutter) and the
[renefritze/python_cookiecutter](https://github.com/renefritze/python_cookiecutter)
project template.
