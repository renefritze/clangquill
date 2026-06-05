```{highlight} shell

```

# Installation

## Stable release

To install clangquill, run this command in your terminal:

```{code-block} console

$ pip install clangquill

```

This is the preferred method to install clangquill, as it will always install the most recent stable release.

If you don't have [pip][pip] installed, this [Python installation guide][python installation guide] can guide
you through the process.

```{note}
**Bundled libclang.** The Linux wheels bundle a self-contained **libclang 20**
(from the official LLVM release), so parsing works out of the box with no system
LLVM required — `c++20`/`c++23`/`c++26` are all supported (see the
[`std` configuration note](guides/configuration.md)). Because that libclang
needs **glibc ≥ 2.34** (manylinux_2_34), the wheels install on reasonably recent
Linux distributions; on older systems, build from source against your own
libclang instead.
```

[pip]: https://pip.pypa.io

[python installation guide]: http://docs.python-guide.org/en/latest/starting/installation/

## From sources

The sources for clangquill can be downloaded from the [Github repo][github repo].

You can either clone the public repository:

```{code-block} console

$ git clone https://github.com/renefritze/clangquill.git

```

Or download the [tarball][tarball]:

```{code-block} console

$ curl -OJL https://github.com/renefritze/clangquill/tarball/main

```

Once you have a copy of the source, you can install it with:

```{code-block} console

$ pip install .

```

[github repo]: https://github.com/renefritze/clangquill

[tarball]: https://github.com/renefritze/clangquill/tarball/main
