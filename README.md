clangquill
=========

![ClangQuill Logo](https://raw.githubusercontent.com/renefritze/clangquill/main/docs/_static/clangquill-logo.png)

[![image](https://github.com/renefritze/clangquill/workflows/pytest/badge.svg)](https://github.com/renefritze/clangquill/actions)


Parse Doxygen-documented C++ with libclang and generate MyST Markdown API docs for Sphinx


Features
--------

-   TODO

Building from source
--------------------

`clangquill` ships a compiled C++ core (`clangquill._core`) built with
[scikit-build-core](https://scikit-build-core.readthedocs.io/), CMake and
[nanobind](https://nanobind.readthedocs.io/). A standard install builds it:

```console
$ pip install .
$ python -c "from clangquill import _core; print(_core.have_libclang())"
```

The core optionally links **libclang**; when `libclang-dev` (or an LLVM prefix
via `LibClang_ROOT`) is available at build time the extraction backend is
enabled. Pass `-DCLANGQUILL_WITH_LIBCLANG=ON` to require it.

After generating your project
-----------------------------

- setup branch protection+automerge in [github project settings](https://github.com/renefritze/clangquill/settings/branches)
- request install for the codecov.io app in [github project settings](https://github.com/renefritze/clangquill/settings/installations)
- configure codecov.io in [codecov.io settings](https://codecov.io/gh/renefritze/clangquill/settings)
- add the `CODECOV_TOKEN` secret in [github project settings](https://github.com/renefritze/clangquill/settings/secrets/actions)


Credits
-------

This package was created with
[Cookiecutter](https://github.com/audreyr/cookiecutter) and the
[renefritze/python_cookiecutter](https://github.com/renefritze/python_cookiecutter)
project template.
