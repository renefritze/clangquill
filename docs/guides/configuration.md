# Configuration reference

Every clangquill run — whether driven by the [Sphinx extension](../usage.md),
the `clangquill build` CLI, or the Python API — is described by a single
{py:class}`clangquill.config.Config`. The three front ends share this schema, so
they validate identically.

The field-name-to-front-end mapping is mechanical:

- **Sphinx**: a field named `output_dir` is the config value `clangquill_output_dir`.
- **CLI**: the same field is the flag `--output-dir` (`clangquill build --help`).
- **Python**: pass it as a keyword to `Config(...)`.

## Inputs

| Field | Sphinx value | Default | Description |
|-------|--------------|---------|-------------|
| `input` | `clangquill_input` | `[]` | Header/source paths (or globs) to parse, relative to the base directory (the Sphinx srcdir or CWD). |
| `compile_commands` | `clangquill_compile_commands` | `None` | Directory holding a `compile_commands.json`. When set it supplies the compiler flags and **overrides** `std`/`include_dirs`/`defines`. |
| `compile_args` | `clangquill_compile_args` | `[]` | Extra compiler arguments appended verbatim when no compile database is used. |
| `include_dirs` | `clangquill_include_dirs` | `[]` | `-I` include directories. |
| `std` | `clangquill_std` | `"c++20"` | C++ standard, passed as `-std=<std>`. |
| `defines` | `clangquill_defines` | `[]` | `-D` preprocessor definitions (`NAME` or `NAME=value`). |
| `clang_resource_dir` | `clangquill_clang_resource_dir` | `None` | Clang resource directory (`-resource-dir`); `None` lets clang decide. |

## Output

| Field | Sphinx value | Default | Description |
|-------|--------------|---------|-------------|
| `output_dir` | `clangquill_output_dir` | `"api"` | Directory (under the srcdir / CWD) the generated pages are written to. |
| `template_dirs` | `clangquill_template_dirs` | `[]` | Directories searched before the bundled templates for overrides. See the [template-override guide](templates.md). |
| `templates` | `clangquill_templates` | `{}` | Per-kind template overrides, e.g. `{"class": "my_class"}`. |
| `cache_dir` | `clangquill_cache_dir` | `None` | Directory holding the persistent incremental cache. `None` disables caching (re-parse + rewrite every page each build). See [incremental builds](../usage.md#incremental-builds). |
| `include_undocumented` | `clangquill_include_undocumented` | `True` | Emit pages/sections for symbols that carry no documentation comment. |
| `comment_parser` | `clangquill_comment_parser` | `None` | Comment-parser override: a registered name or a dotted import path. See the [comment-parser guide](comment-parsers.md). |
| `group_by` | `clangquill_group_by` | `"symbol"` | How to partition output pages: `"symbol"` (one page per top-level symbol) or `"file"` (one page per parsed source file). |

## Toctree / root

| Field | Sphinx value | Default | Description |
|-------|--------------|---------|-------------|
| `toctree_maxdepth` | `clangquill_toctree_maxdepth` | `2` | `:maxdepth:` of the generated root toctree. |
| `root_document` | `clangquill_root_document` | `"index"` | Stem of the generated index/toctree page within `output_dir`. |

```{note}
Doxygen `\defgroup` groups, when present, add one page per group after the
symbol/file pages; the toctree picks them up automatically.
```
